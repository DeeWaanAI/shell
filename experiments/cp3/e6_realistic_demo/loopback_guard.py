#!/usr/bin/env python3
"""Loopback-only NetworkGuard for E6.

The CP2/CP3 ``fake_transport.NetworkGuard`` blocks EVERY socket connection —
right for an offline gate, wrong for E6, which must make a REAL local model call
to ollama on ``127.0.0.1:11434``. This guard PERMITS loopback and BLOCKS (and
counts) any non-loopback connection, so the run proves "only loopback was
touched — no cloud, no paid call" (E6 instructions §2, §5).

It intercepts the two entry points that matter for ``http.client`` (which L5's
``transport.py`` uses):

* ``socket.create_connection((host, port), ...)`` — what
  ``http.client.HTTPConnection.connect`` calls;
* ``socket.socket.connect(address)`` — raw sockets.

Every permitted loopback target is recorded; every blocked non-loopback target
is counted and raises. At the end the caller asserts
``non_loopback_calls == 0``.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _host_of(address) -> str:
    """Extract the host from a socket address argument."""
    if isinstance(address, tuple) and address:
        return str(address[0])
    if isinstance(address, (bytes, bytearray)):
        # AF_UNIX path — treat as local, not a network egress.
        return "unix:" + address.decode("utf-8", "replace")
    if isinstance(address, str):
        return "unix:" + address
    return ""


def _is_loopback(host: str) -> bool:
    if host in LOOPBACK_HOSTS:
        return True
    if host.startswith("unix:"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class LoopbackGuard:
    """Permit loopback, block + count everything else."""

    def __init__(self):
        self.loopback_calls: list[dict] = []
        self.non_loopback_calls = 0
        self.blocked: list[str] = []
        self._orig_create_connection = None
        self._orig_socket_connect = None

    def __enter__(self):
        self._orig_create_connection = socket.create_connection
        self._orig_socket_connect = socket.socket.connect

        def _guarded_create_connection(address, *a, **k):
            host = _host_of(address)
            if _is_loopback(host):
                self.loopback_calls.append({"host": host, "via": "create_connection",
                                              "port": (address[1] if isinstance(address, tuple)
                                                         and len(address) > 1 else None)})
                return self._orig_create_connection(address, *a, **k)
            self.non_loopback_calls += 1
            self.blocked.append(f"create_connection:{host}")
            raise AssertionError(f"non-loopback connection blocked: {host!r}")

        def _guarded_socket_connect(sock, address):
            host = _host_of(address)
            if _is_loopback(host):
                self.loopback_calls.append({"host": host, "via": "socket.connect",
                                              "port": (address[1] if isinstance(address, tuple)
                                                         and len(address) > 1 else None)})
                return self._orig_socket_connect(sock, address)
            self.non_loopback_calls += 1
            self.blocked.append(f"socket.connect:{host}")
            raise AssertionError(f"non-loopback connection blocked: {host!r}")

        socket.create_connection = _guarded_create_connection
        socket.socket.connect = _guarded_socket_connect
        return self

    def __exit__(self, *exc):
        socket.create_connection = self._orig_create_connection
        socket.socket.connect = self._orig_socket_connect
        return False

    def report(self) -> dict:
        ports = sorted({c["port"] for c in self.loopback_calls if c.get("port")})
        return {
            "loopback_call_count": len(self.loopback_calls),
            "loopback_ports_touched": ports,
            "non_loopback_calls": self.non_loopback_calls,
            "blocked": self.blocked,
            "only_loopback_touched": self.non_loopback_calls == 0,
        }
