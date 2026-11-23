#!/usr/bin/env python3
"""router.connection_ops — Layer 5's public connection-mutation surface (contract v0.2).

Layer 3's connection adapter (``03-action-layer/.../adapters/connection.py``) executes
``connection.add`` / ``connection.retire`` / ``connection.privacy_change`` by calling three
public operations on an object handed to ``ActionEngine(root, connection_ops=<obj>)``. This
module is that object. It is the ONLY public mutation surface L3 uses; read-only ``list`` /
``status`` stay in ``connect.py``.

Everything here reuses the mechanics already proven in ``connect.py`` (--add, --set-privacy,
--retire-broken) and writes through the sanctioned Qafiya path in ``store.py`` (append +
chained history + atomic set_status). It obeys the FROZEN spec v1.1:

* **Ids are immutable; content edits never change an id** (spec §1.1, line 507). A privacy
  change is therefore *succession*, not an in-place edit: ``set_privacy_class`` appends a NEW
  record with the new class and retires the old one with ``superseded_by = new_id`` — exactly
  what ``connect.py --set-privacy`` does (spec §9.1: "succession, not quarantine"). There is
  deliberately NO in-place update primitive here; adding one would violate frozen v1.1 and
  disturb the published immutability claims.
* **No secret is ever stored** (RC-1.2). A record carries ``auth.key_env`` — the NAME of an
  environment variable — never its value. ``add_connection`` refuses a config that carries an
  actual key/token/password.
* **No live/network call.** ``add_connection`` does NOT gate on ``remote_models`` / ``--list``;
  the acceptance battery runs offline. Routing still never fetches anything.

Because succession allocates a NEW id, the successor is exposed two ways for the caller:
``last_successor_id`` (the id minted by the most recent ``set_privacy_class``) and
``get_active_successor(mdl_id)`` (follow ``superseded_by`` from a retired id to the active
record it was superseded into). Under connection-actions v0.2 (frozen) L3 classifies
``connection.privacy_change`` as COMPENSABLE, captures its undo recipe late from execute, and
re-addresses the successor through these accessors — so the two layers agree and the privacy
undo succeeds by minting a further record. L5's succession model is unchanged; it was never
bent toward an in-place edit.
"""
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import connections as X  # noqa: E402  (PRIVACY_ALIASES, CONNECTORS, REQUIRED, normalise)
from store import Store, StoreError, new_id, now  # noqa: E402

SPEC_VERSION = "1.1"                 # the frozen ds:models spec this record conforms to
DEFAULT_CONTEXT_WINDOW = 32768       # connect.py --add default
DEFAULT_OUTPUT_BUDGET = 1024
DEFAULT_TIMEOUT_S = 60.0

# The flat config shape L3's contract sends (adapters/connection.py CONFIG_FIELDS).
CONFIG_FIELDS = {"label", "connector", "base_url", "model", "locus",
                 "privacy_class", "prices", "key_env"}

# Field names that would carry a secret VALUE rather than an env-var NAME. A superset of L3's
# SECRET_FIELDS: L5 is the last boundary, so it refuses independently (defence in depth).
SECRET_FIELDS = {"api_key", "apikey", "secret", "secret_key", "token", "access_token",
                 "refresh_token", "password", "passwd", "credential", "credentials",
                 "key_value", "authorization", "auth_header", "bearer", "private_key"}

# An env-var NAME is a bare identifier. Anything else (e.g. "sk-test-...") is a VALUE, refused.
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ConnectionOpError(ValueError):
    """A config/argument violates the contract (missing field, secret value, bad enum).

    Raised by ``add_connection`` — a hard contract violation, not a soft miss. L3's adapter
    catches it in ``connection_execute`` / ``connection_undo`` and records the action as failed.
    """


def _normalise_connector(value):
    """Accept the contract's connector spelling and map it onto the frozen enum.

    ``connections.CONNECTORS`` is ``("openai_compatible", "ollama")``. The L3 contract example
    writes ``"openai-compatible"`` (hyphen). This is a spelling normalisation of the SAME
    connector, not a widening of accepted semantics: after folding case and turning ``-``/space
    into ``_``, the value must still be a member of the frozen enum or it is refused.
    """
    if not isinstance(value, str) or not value.strip():
        raise ConnectionOpError("connector is required")
    folded = value.strip().lower().replace("-", "_").replace(" ", "_")
    if folded not in X.CONNECTORS:
        raise ConnectionOpError(f"unknown_connector:{value!r} (expected one of {X.CONNECTORS})")
    return folded


def _reject_secrets(config, key_env):
    """Refuse a config that carries an actual secret VALUE rather than an env-var NAME."""
    forbidden = {k.lower() for k in config} & SECRET_FIELDS
    if forbidden:
        raise ConnectionOpError(
            f"config carries secret field(s) {sorted(forbidden)}; pass key_env (a NAME), never a value")
    if key_env is not None:
        if not isinstance(key_env, str) or not _ENV_NAME.match(key_env):
            # Not a valid env-var NAME -> it is a value (e.g. "sk-..."), which we never accept.
            raise ConnectionOpError(
                "key_env must be a bare environment-variable NAME, not a secret value")
        resolved = os.environ.get(key_env)
        if resolved:
            # The secret's VALUE must never appear anywhere in the stored config.
            for field, value in config.items():
                if isinstance(value, str) and resolved in value:
                    raise ConnectionOpError(
                        f"secret value for {key_env} leaked into config field {field!r}")
                if isinstance(value, dict):
                    for sub, sval in value.items():
                        if isinstance(sval, str) and resolved in sval:
                            raise ConnectionOpError(
                                f"secret value for {key_env} leaked into config {field}.{sub}")


class ConnectionOperations:
    """The three public connection mutations, bound to a Layer-5 ``Store``.

    Ready to hand to L3 as ``ActionEngine(root, connection_ops=ConnectionOperations(store))``.
    """

    def __init__(self, store):
        if not isinstance(store, Store):
            raise TypeError("ConnectionOperations requires a router.store.Store")
        self.store = store
        # The id minted by the most recent successful set_privacy_class (succession), else None.
        self.last_successor_id = None

    # ------------------------------------------------------------------ add
    def add_connection(self, config):
        """Append a user-declared connection to ``ds:models``. Returns the new ``mdl_*`` id.

        Makes NO live/network call (no ``remote_models`` / ``--list`` gate). Refuses secret
        values. Mirrors ``connect.py --add``'s record exactly, minus the network gate.
        """
        if not isinstance(config, dict):
            raise ConnectionOpError("connection config must be an object")
        unknown = set(config) - CONFIG_FIELDS
        if unknown:
            raise ConnectionOpError(
                f"config carries undeclared field(s) {sorted(unknown)}; accepted: {sorted(CONFIG_FIELDS)}")

        key_env = config.get("key_env")
        _reject_secrets(config, key_env)

        model = config.get("model")
        label = config.get("label") or model
        connector = _normalise_connector(config.get("connector"))
        base_url = config.get("base_url")
        locus = config.get("locus")
        privacy = X.PRIVACY_ALIASES.get(str(config.get("privacy_class")))

        # Required, non-empty declarations (connections.REQUIRED minus the derived price/id).
        for name, value in (("label", label), ("base_url", base_url),
                            ("model", model), ("locus", locus)):
            if value in (None, ""):
                raise ConnectionOpError(f"missing_field:{name}")
        if locus not in ("local", "cloud"):
            raise ConnectionOpError(f"bad_locus:{locus!r} (expected 'local' or 'cloud')")
        if privacy is None:
            raise ConnectionOpError(
                f"bad_privacy_class:{config.get('privacy_class')!r} "
                f"(expected one of {sorted(X.PRIVACY_ALIASES)})")

        # Declared prices stay declarations; a missing price is 'unknown', never invented (RC-1.4).
        prices = config.get("prices") or {}
        if not isinstance(prices, dict):
            raise ConnectionOpError("prices must be an object {input, output}")
        pin, pout = prices.get("input"), prices.get("output")
        unknown_price = pin is None or pout is None
        for name, value in (("input", pin), ("output", pout)):
            if value is None:
                continue
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ConnectionOpError(f"price_not_number:{name}={value!r}")
            if value < 0:
                raise ConnectionOpError(f"price_negative:{name}={value}")
            if value > 1000.0:
                raise ConnectionOpError(f"price_suspected_unit_error:{name}={value}")

        rec = {
            "id": new_id("mdl"), "created_at": now(), "spec_version": SPEC_VERSION,
            "status": "active", "superseded_by": None, "source_ref": ["user"],
            "label": label, "connector": connector,
            "base_url": base_url, "model": model,
            "auth": {"scheme": "bearer" if key_env else "none",
                     "key_env": key_env if key_env else None},
            "locus": locus,
            "privacy_class": privacy,
            "price": {"input_per_mtok": float(pin or 0.0),
                      "output_per_mtok": float(pout or 0.0),
                      "source": "unknown" if unknown_price else "user_declared"},
            "context_window": DEFAULT_CONTEXT_WINDOW,
            "output_budget_tokens": DEFAULT_OUTPUT_BUDGET, "tokenizer_ref": None,
            "request_params": None, "timeout_s": DEFAULT_TIMEOUT_S, "local_resources": None,
            "health": None, "declared_at": now(),
        }
        # The record must be routable on arrival; refuse rather than write a broken connection.
        conn, problems = X.normalise(rec)
        if conn is None:
            # A missing env var is NOT a reason to refuse the declaration (RC-1.2: it is
            # reported at call time), so only structural problems block the write.
            structural = [p for p in problems if not p.startswith("missing_env:")]
            if structural:
                raise ConnectionOpError("record failed validation: " + "; ".join(structural))
        self.store.append("models", rec)
        return rec["id"]

    # --------------------------------------------------------------- retire
    def retire_connection(self, mdl_id):
        """Retire (do NOT delete) an existing connection. Literal True on success.

        False if the id is missing or already inactive. Mirrors ``connect.py --retire-broken``:
        ``store.set_status("models", id, "retired", superseded_by=None)``.
        """
        if not isinstance(mdl_id, str) or not mdl_id:
            return False
        rec = self.store.get("models", mdl_id)
        if rec is None:
            return False
        if rec.get("status") != "active":
            return False           # already retired/discredited: nothing to do
        try:
            self.store.set_status("models", mdl_id, "retired", superseded_by=None)
        except StoreError:
            return False
        return True

    # -------------------------------------------------------- privacy change
    def set_privacy_class(self, mdl_id, new_class):
        """Change a connection's declared privacy class by SUCCESSION (frozen v1.1).

        Appends a NEW record with the updated class and retires the old one with
        ``superseded_by = new_id`` — exactly ``connect.py --set-privacy``. The old id is never
        mutated in place. Literal True on success; False if the id is missing/inactive or the
        class is invalid. The successor id is exposed via ``last_successor_id`` and
        ``get_active_successor(mdl_id)``.
        """
        normalized = X.PRIVACY_ALIASES.get(str(new_class))
        if normalized is None:
            return False           # accept P0/P1/P2 and public/confidential/private only
        if not isinstance(mdl_id, str) or not mdl_id:
            return False
        rec = self.store.get("models", mdl_id)
        if rec is None or rec.get("status") != "active":
            return False           # missing, or already superseded/retired (the L3 undo case)
        successor = json.loads(json.dumps(rec))     # deep copy; ids are immutable
        successor.update(
            id=new_id("mdl"), created_at=now(), superseded_by=None,
            source_ref=[rec["id"]], declared_at=now(), privacy_class=normalized)
        try:
            self.store.append("models", successor)
            self.store.set_status("models", rec["id"], "retired", superseded_by=successor["id"])
        except StoreError:
            return False
        self.last_successor_id = successor["id"]
        return True

    # ------------------------------------------------------- successor lookup
    def get_active_successor(self, mdl_id):
        """Follow ``superseded_by`` from a (typically retired) id to the ACTIVE record it was
        superseded into. Returns that id, or None if ``mdl_id`` is active/unknown or the chain
        has no active tail. This is what L3's privacy-undo needs once it stops re-addressing
        the SAME (now retired) id.
        """
        rec = self.store.get("models", mdl_id) if isinstance(mdl_id, str) and mdl_id else None
        if rec is None:
            return None
        cur = rec.get("superseded_by")
        seen = {mdl_id}
        while cur and cur not in seen:
            seen.add(cur)
            r = self.store.get("models", cur)
            if r is None:
                return None
            if r.get("status") == "active":
                return cur
            cur = r.get("superseded_by")
        return None


def build_ops(root=None, store=None):
    """Convenience factory: ``build_ops(ROOT)`` or ``build_ops(store=Store(ROOT))``."""
    if store is None:
        store = Store(root if root is not None else ROOT)
    return ConnectionOperations(store)


if __name__ == "__main__":
    ops = build_ops()
    active = [m["id"] for m in ops.store.records("models", status="active") if "connector" in m]
    print(f"connection_ops ready against {ops.store.root}")
    print(f"  active connections: {len(active)}")
    print("  public mutations: add_connection(config)->str, "
          "retire_connection(id)->bool, set_privacy_class(id,class)->bool")
