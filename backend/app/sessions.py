"""In-memory sessions. One backend worker only; a restart clears everything."""

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from .schemas import Draft, Policy

MAX_SESSIONS = 50
MAX_TIMELINE = 300


class TimelineFull(RuntimeError):
    pass


@dataclass
class Pending:
    """A send waiting for a human, bound to an exact draft snapshot."""
    action_id: str
    draft_id: str
    content_hash: str
    label: str
    policy_version: int
    run_id: int
    expires_at: float


@dataclass
class Session:
    id: str
    # The runner calls the dispatcher while holding this lock, so it must be reentrant.
    lock: threading.RLock = field(default_factory=threading.RLock)
    run_id: int = 0
    scenario_id: str = ""
    variant_id: str = "default"
    mode: str = "replay"
    injection: Optional[str] = None      # text appended to club-notes for this run
    custom_attack: Optional[str] = None  # the visitor's own text, if this run uses it
    policy: Optional[Policy] = None
    session_label: str = "public"
    label_history: list = field(default_factory=list)
    drafts: dict[str, Draft] = field(default_factory=dict)
    outbox: list = field(default_factory=list)
    pending: dict[str, Pending] = field(default_factory=dict)
    timeline: list = field(default_factory=list)
    seq: int = 0
    replay_index: int = 0
    replay_total: int = 0
    aliases: dict[str, str] = field(default_factory=dict)
    conversation: list = field(default_factory=list)
    notes_for_model: list = field(default_factory=list)   # e.g. approval outcomes
    status: str = "ready"
    error: Optional[str] = None
    model_calls: int = 0
    proposals: int = 0
    step_in_flight: bool = False
    last_summary: Optional[dict] = None


def add_event(session: Session, kind: str, **data) -> dict:
    """Append a timeline entry. Action entries are later updated in place."""
    if len(session.timeline) >= MAX_TIMELINE:
        raise TimelineFull("Timeline is full; reset the scenario.")
    session.seq += 1
    entry = {"seq": session.seq, "kind": kind, "time": time.time(), **data}
    session.timeline.append(entry)
    return entry


def find_action(session: Session, action_id: str) -> Optional[dict]:
    return next((e for e in session.timeline if e.get("action_id") == action_id), None)


class SessionStore:
    def __init__(self):
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self) -> Session:
        with self._lock:
            if len(self._sessions) >= MAX_SESSIONS:
                raise RuntimeError("Too many sessions; restart the demo server.")
            session = Session(id=secrets.token_urlsafe(16))
            self._sessions[session.id] = session
            return session

    def get(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)
