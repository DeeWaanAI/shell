"""Connection mutations through L5's public operations (contract v0.2 Rev.3).

The adapter never imports L5 internals. ActionEngine receives an object exposing
add_connection(config) -> str, retire_connection(id) -> bool, and
set_privacy_class(id, class) -> bool, plus the successor accessors
get_active_successor(id) -> str | None and last_successor_id. Only non-secret
configuration is accepted. key_env is OPTIONAL (Rev.3): absent, None, or "" means
"no auth" (L5 sets auth.scheme="none", key_env=null, routable without a secret);
when present it must be a bare environment-variable NAME, never a raw value.

Under frozen L5 spec v1.1 record ids are immutable, so a privacy change is applied
by SUCCESSION: set_privacy_class returns True and mints a NEW active id while the
old id is retired with superseded_by. Because the new id is unknown until execute
runs, connection.privacy_change is COMPENSABLE and captures its undo recipe LATE
from execute (like file.delete), addressing the successor the accessors expose.
"""
from ..qafiya_shim import now_iso
import copy
import re

CONNECTION_ACTIONS = {"connection.add", "connection.retire", "connection.privacy_change"}
CONFIG_FIELDS = {"label", "connector", "base_url", "model", "locus",
                 "privacy_class", "prices", "key_env", "scheme"}
SECRET_FIELDS = {"api_key", "apikey", "secret", "secret_key", "token",
                 "password", "credential", "credentials", "key_value"}
# A key_env, when present, is a bare env-var NAME (same rule L5 enforces). A raw
# value like "sk-..." fails this and is refused — the secret rule is unchanged.
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
REDACTED_KEY_ENV = "<redacted:not-an-env-var-name>"


def redact_normalized_intent(normalized):
    """Return a record-safe copy; never persist an invalid key_env value."""
    safe = copy.deepcopy(normalized)
    if safe.get("action_type") not in CONNECTION_ACTIONS:
        return safe
    config = safe.get("params", {}).get("config")
    if isinstance(config, dict) and "key_env" in config:
        key_env = config["key_env"]
        if key_env not in (None, "") and not (isinstance(key_env, str)
                                              and _ENV_NAME.fullmatch(key_env)):
            config["key_env"] = REDACTED_KEY_ENV
    return safe


def _operations(store):
    ops = getattr(store, "connection_ops", None)
    if ops is None or not all(callable(getattr(ops, name, None)) for name in
                             ("add_connection", "retire_connection", "set_privacy_class")):
        raise RuntimeError("L5 public connection operations are not configured")
    return ops


def _config(params):
    config = params.get("config")
    if not isinstance(config, dict):
        raise ValueError("connection config must be an object")
    unknown = set(config) - CONFIG_FIELDS
    forbidden = {key.lower() for key in config} & SECRET_FIELDS
    if unknown or forbidden:
        raise ValueError("connection config contains undeclared or secret fields")
    # Rev.3: key_env is OPTIONAL. Absent / None / "" means "no auth" (L5 derives
    # auth.scheme="none", key_env=null — routable without a secret). If present it
    # must be a bare env-var NAME; a raw value (or non-string) is refused.
    key_env = config.get("key_env")
    if key_env not in (None, "") and not (isinstance(key_env, str)
                                          and _ENV_NAME.match(key_env)):
        raise ValueError(
            "key_env must be a bare environment-variable NAME, not a secret value")
    # Explicit keyless registrations use scheme="none" only for local locus and
    # cannot simultaneously name a credential. Omitting scheme remains equivalent.
    if "scheme" in config:
        if config["scheme"] != "none" or config.get("locus") != "local":
            raise ValueError('scheme="none" is accepted only for local connections')
        if key_env not in (None, ""):
            raise ValueError('scheme="none" connections must not carry key_env')
    return dict(config)


def connection_targets(n):
    p = n["params"]
    if n["action_type"] == "connection.add":
        # The id is allocated by L5; a model-id-shaped target matches mdl_* grants.
        return [p.get("target", "mdl_new")]
    return [p["connection_id"]]


def connection_classify(n):
    # add = EXACT (retire the allocated id). retire and privacy_change = COMPENSABLE:
    # both are reversed by minting a further record, never by an in-place edit.
    return "EXACT" if n["action_type"] == "connection.add" else "COMPENSABLE"


def connection_preconditions(n, store):
    try:
        _operations(store)
        if n["action_type"] in ("connection.add", "connection.retire"):
            _config(n["params"])
        if n["action_type"] == "connection.privacy_change":
            p = n["params"]
            if not p.get("new_class") or not p.get("previous_class"):
                raise ValueError("new_class and previous_class are required")
        return [{"check": "l5_connection_contract", "params": {}, "result": "pass"}]
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        return [{"check": "l5_connection_contract", "params": {},
                 "result": "fail", "detail": str(exc)}]


def connection_capture_undo(n, store):
    p = n["params"]
    at = n["action_type"]
    if at == "connection.add":
        return {"ops": [{"op": "connection_retire", "connection_id": "__FROM_EXEC__"}]}
    if at == "connection.retire":
        return {"ops": [{"op": "connection_add", "config": _config(p)}]}
    if at == "connection.privacy_change":
        # Successor id is unknown until execute (L5 mints it by succession);
        # capture the recipe LATE from execute, exactly like file.delete.
        return None
    return None


def connection_execute(n, store):
    ops = _operations(store)
    p = n["params"]
    at = n["action_type"]
    recipe = None
    try:
        if at == "connection.add":
            connection_id = ops.add_connection(_config(p))
            if not isinstance(connection_id, str) or not connection_id:
                raise RuntimeError("L5 add_connection did not return a connection id")
            recipe = {"ops": [{"op": "connection_retire", "connection_id": connection_id}]}
            detail = f"added {connection_id}"
        elif at == "connection.retire":
            if ops.retire_connection(p["connection_id"]) is not True:
                raise RuntimeError("L5 retire_connection returned failure")
            detail = f"retired {p['connection_id']}"
        elif at == "connection.privacy_change":
            if ops.set_privacy_class(p["connection_id"], p["new_class"]) is not True:
                raise RuntimeError("L5 set_privacy_class returned failure")
            succ = ops.get_active_successor(p["connection_id"]) or ops.last_successor_id
            if not succ:
                raise RuntimeError("L5 set_privacy_class succeeded but exposed no successor id")
            recipe = {"ops": [{"op": "connection_privacy", "connection_id": succ,
                               "privacy_class": p["previous_class"]}]}
            detail = f"privacy {p['connection_id']} -> {p['new_class']} (successor {succ})"
        else:
            raise RuntimeError("unknown connection action")
        return True, [{"ts": now_iso(), "step": detail, "result": "ok"}], [], recipe
    except Exception as exc:
        return False, [{"ts": now_iso(), "step": f"{at} failed: {exc}",
                        "result": "error"}], [], None


def connection_undo(recipe, store):
    ops = _operations(store)
    try:
        for op in recipe["ops"]:
            if op["op"] == "connection_retire":
                if ops.retire_connection(op["connection_id"]) is not True:
                    return False, "L5 retire_connection returned failure"
                return True, f"retired {op['connection_id']}"
            if op["op"] == "connection_add":
                connection_id = ops.add_connection(dict(op["config"]))
                if not isinstance(connection_id, str) or not connection_id:
                    return False, "L5 add_connection did not return a connection id"
                return True, f"re-added as {connection_id}"
            if op["op"] == "connection_privacy":
                if ops.set_privacy_class(op["connection_id"], op["privacy_class"]) is not True:
                    return False, "L5 set_privacy_class returned failure"
                return True, f"restored privacy on {op['connection_id']}"
            return False, f"unknown undo op: {op['op']}"
    except Exception as exc:
        return False, str(exc)
    return True, "ok"
