"""Session and request references (``s_*`` / ``req_*``).

The shell mints prefixed sortable ids per the OS identity convention
(INTERFACES.md). A session groups every audit event for one journey; a
request is one prompt inside that session. Neither id carries authority:
they exist so lower-layer records and shell audit events can be joined
deterministically.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field


def _sortable(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000):013d}{secrets.token_hex(3)}"


@dataclass
class Request:
    """One user prompt with its attachments, verbatim."""
    id: str
    session_id: str
    prompt_verbatim: str
    attachments: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda:
                            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


@dataclass
class Session:
    """A journey: one prompt in, an auditable sequence of states out."""
    id: str
    user_id: str
    requests: list[Request] = field(default_factory=list)
    created_at: str = field(default_factory=lambda:
                            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def new_request(self, prompt_verbatim: str,
                    attachments: list[str] | None = None) -> Request:
        req = Request(id=_sortable("req"), session_id=self.id,
                      prompt_verbatim=prompt_verbatim,
                      attachments=list(attachments or []))
        self.requests.append(req)
        return req


def new_session(user_id: str) -> Session:
    return Session(id=_sortable("s"), user_id=user_id)
