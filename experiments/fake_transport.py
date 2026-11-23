#!/usr/bin/env python3
"""Local fake transport for CP2 gates F2, F6 and F8.

L5's ``Router`` accepts any object exposing ``call(conn, prompt, expected_out)``
as its transport. This module is that object. It NEVER touches the network —
``NetworkGuard`` monkey-patches ``urllib.request.urlopen``, ``socket.socket.connect``
and ``socket.create_connection`` for the whole run and asserts zero calls at the
end (same pattern as L5's own acceptance battery in
``router/test_connection_ops.py``).

Honesty rule (CP1 clearance answer 2): a simulated cost is a SIMULATED cost. Every
result carries ``meter = "simulated_local_fake"`` so the shell's route indicator
can label it as such, and ``actual_metered_cost_usd`` is never populated from a
fake number without that label travelling with it.

Three variants are exposed so gates can exercise the honest outcomes:

* ``answered`` — ok=True with a deterministic text, tokens and a simulated meter
* ``call_failed`` — ok=False with a typed ``error_class`` (auth/timeout/connection/…)
* ``refused_all`` — the router sees every candidate fail and commits
  ``outcome="refused", refusal_reason="all_connections_failed"``
"""
from __future__ import annotations

import socket
import time
import urllib.request
from dataclasses import dataclass


METER_LABEL = "simulated_local_fake"
"""Every simulated result carries this in ``meter`` so the shell can label it."""


class NetworkGuard:
    """Fail loudly on ANY outbound network attempt, and count them.

    Copy of the guard L5's own acceptance battery uses — kept here so the CP2
    battery can assert "zero network calls" without importing L5 test code.
    """

    def __init__(self):
        self.calls = 0
        self._urlopen = None
        self._connect = None
        self._create_connection = None

    def __enter__(self):
        self._urlopen = urllib.request.urlopen
        self._connect = socket.socket.connect
        self._create_connection = socket.create_connection

        def _blocked_urlopen(*a, **k):
            self.calls += 1
            raise AssertionError("network call attempted: urllib.request.urlopen")

        def _blocked_connect(*a, **k):
            self.calls += 1
            raise AssertionError("network call attempted: socket.connect")

        def _blocked_create_connection(*a, **k):
            self.calls += 1
            raise AssertionError("network call attempted: socket.create_connection")

        urllib.request.urlopen = _blocked_urlopen
        socket.socket.connect = _blocked_connect
        socket.create_connection = _blocked_create_connection
        return self

    def __exit__(self, *exc):
        urllib.request.urlopen = self._urlopen
        socket.socket.connect = self._connect
        socket.create_connection = self._create_connection
        return False


@dataclass(frozen=True)
class FakeReply:
    """One deterministic reply the fake transport will produce.

    ``kind`` selects the shape:

    * ``answered``     → ok=True with text/tokens/finish_reason
    * ``call_failed``  → ok=False with a typed ``error_class``
    """
    kind: str                       # 'answered' | 'call_failed'
    text: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    finish_reason: str | None = None
    error_class: str | None = None
    latency_ms: int = 3
    confidence: float | None = None
    structural_check: bool | None = None


ANSWERED = FakeReply(
    kind="answered",
    text=("SIMULATED local-fake answer for the CP2 gates. This text was produced "
          "by experiments/fake_transport.py, not by a provider."),
    tokens_in=18, tokens_out=24, finish_reason="stop", confidence=0.94,
)

CALL_FAILED_TIMEOUT = FakeReply(kind="call_failed", error_class="timeout",
                                  latency_ms=1200)
CALL_FAILED_AUTH = FakeReply(kind="call_failed", error_class="auth", latency_ms=15)
CALL_FAILED_CONNECTION = FakeReply(kind="call_failed", error_class="connection",
                                      latency_ms=8)


class FakeTransport:
    """Module-like object L5's ``Router`` can consume via ``transport=<this>``.

    ``script`` maps a connection id (``mdl_*``) to the reply that connection
    should produce. Any connection not in the script gets ``ANSWERED`` so a
    gate does not have to enumerate every seed row. Set ``default`` to override
    that fallback (used by F8's "all connections fail" case).
    """

    def __init__(self, script: dict[str, FakeReply] | None = None,
                 default: FakeReply = ANSWERED):
        self.script: dict[str, FakeReply] = dict(script or {})
        self.default = default
        self.history: list[dict] = []        # one row per call, for audit

    def call(self, conn: dict, prompt: str, expected_out: int) -> dict:
        reply = self.script.get(conn["id"], self.default)
        self.history.append({"connection_id": conn["id"],
                              "prompt_len": len(prompt or ""),
                              "expected_out": expected_out,
                              "reply_kind": reply.kind,
                              "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        base = {
            "connector": conn["connector"],
            "latency_ms": reply.latency_ms,
            "tries": [{"n": 1, "error_class": reply.error_class,
                        "status": 200 if reply.kind == "answered" else None,
                        "latency_ms": reply.latency_ms,
                        "usage": ({"tokens_in": reply.tokens_in,
                                     "tokens_out": reply.tokens_out,
                                     "meter": METER_LABEL}
                                    if reply.kind == "answered" else None),
                        "detail": ""}],
        }
        if reply.kind == "answered":
            return {
                **base,
                "ok": True,
                "error_class": None,
                "text": reply.text,
                "tokens_in": reply.tokens_in,
                "tokens_out": reply.tokens_out,
                "finish_reason": reply.finish_reason,
                "meter": METER_LABEL,
                "confidence": reply.confidence,
                "structural_check": reply.structural_check,
            }
        return {
            **base,
            "ok": False,
            "error_class": reply.error_class,
            "text": None,
            "tokens_in": None, "tokens_out": None,
            "finish_reason": None,
            "meter": None,
            "confidence": None,
            "structural_check": None,
        }

    def probe(self, conn: dict) -> dict:
        """Health probe — never uses the user's prompt (L5 RC-4.8 discipline)."""
        return self.call(conn, "ping", 1)


# Convenience: a module-level ``call`` so callers can pass the MODULE itself as
# the transport if they prefer (matches L5's ``transport=TX`` default shape).
_DEFAULT = FakeTransport()


def call(conn: dict, prompt: str, expected_out: int) -> dict:
    return _DEFAULT.call(conn, prompt, expected_out)


def probe(conn: dict) -> dict:
    return _DEFAULT.probe(conn)
