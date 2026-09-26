"""Local HTTP routes. Run one worker; sessions live in memory."""

from copy import deepcopy
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from . import model_adapter, runner
from .dispatcher import apply_policy_change, resolve_approval
from .scenarios import get_variant, load_catalog
from .schemas import ApprovalRequest, PolicyRequest, ResetRequest, RunRequest
from .sessions import Session, SessionStore, TimelineFull

app = FastAPI(title="AgentGate Playground")
# Same-origin app bound to localhost: no CORS, and only local Host headers.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])

store = SessionStore()
load_catalog()   # fail at startup if a fixture is invalid


def get_session(session_id: str | None) -> Session:
    session = store.get(session_id or "")
    if session is None:
        raise HTTPException(401, "Unknown or missing session. Reload the page.")
    return session


def check_run(session: Session, expected_run_id: int) -> None:
    if expected_run_id != session.run_id:
        raise HTTPException(409, "This tab is out of date: the run was reset elsewhere. Refreshing.")


def snapshot(session: Session) -> dict:
    # Copy now: the session may change before FastAPI serializes the response.
    with session.lock:
        return deepcopy(_snapshot(session))


def _snapshot(session: Session) -> dict:
    catalog = load_catalog()
    classes = catalog.contact_classes
    actions = [e for e in session.timeline if e["kind"] == "action"]
    next_tool = None
    if session.mode == "replay" and session.scenario_id and session.replay_index < session.replay_total:
        _, variant = get_variant(session.scenario_id, session.variant_id)
        next_tool = variant["replay"][session.replay_index]["tool"]
    pending = []
    for p in session.pending.values():
        d = session.drafts[p.draft_id]
        pending.append({"action_id": p.action_id, "draft_id": d.id, "recipient": d.recipient,
                        "recipient_class": classes.get(d.recipient), "subject": d.subject,
                        "body": d.body, "label": d.label, "expires_at": p.expires_at})
    return {
        "run_id": session.run_id, "scenario_id": session.scenario_id, "variant_id": session.variant_id,
        "mode": session.mode, "status": session.status, "error": session.error,
        "step_in_flight": session.step_in_flight,
        "policy": session.policy.model_dump() if session.policy else None,
        "session_label": session.session_label, "label_history": session.label_history,
        "injected": bool(session.injection),
        "custom_attack": session.custom_attack,
        "drafts": [{"id": d.id, "recipient": d.recipient, "recipient_class": classes.get(d.recipient),
                    "subject": d.subject, "body": d.body, "label": d.label, "sent": d.sent}
                   for d in session.drafts.values()],
        "outbox": session.outbox,
        "pending": pending,
        "timeline": session.timeline,
        "replay": {"index": session.replay_index, "total": session.replay_total, "next_tool": next_tool},
        "counts": {
            "proposed": len(actions),
            "denied": sum(e["status"] == "denied" for e in actions),
            "awaiting": sum(e["status"] == "awaiting_approval" for e in actions),
            "executed": sum(e["status"] == "executed" for e in actions),
        },
        "live": {"configured": model_adapter.live_configured(), "model": model_adapter.MODEL,
                 "effort": model_adapter.EFFORT, "calls": session.model_calls,
                 "max_calls": runner.MAX_MODEL_CALLS, "max_proposals": runner.MAX_TOOL_PROPOSALS},
        "last_summary": session.last_summary,
    }


@app.get("/api/health")
def health():
    return {"ok": True, "live_configured": model_adapter.live_configured(), "model": model_adapter.MODEL}


@app.exception_handler(TimelineFull)
def timeline_full(_request, exc):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.get("/api/catalog")
def catalog():
    c = load_catalog()
    return {
        "documents": list(c.documents.values()),
        "attacks": c.attacks,
        "contacts": list(c.contacts.values()),
        "scenarios": [{**{k: s[k] for k in ("id", "title", "summary", "preset")},
                       "variants": [{"id": v["id"], "label": v["label"], "task": v["task"],
                                     "inject": v["inject"], "document": v["document"], "steps": len(v["replay"])} for v in s["variants"]]}
                      for s in c.scenarios.values()],
        "label_rules": [
            {"label": "public", "internal": "allow", "external": "allow"},
            {"label": "internal", "internal": "allow", "external": "require_approval"},
            {"label": "confidential", "internal": "require_approval", "external": "deny"},
        ],
    }


@app.post("/api/sessions")
def create_session():
    try:
        session = store.create()
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    first = next(iter(load_catalog().scenarios))
    runner.reset_run(session, first, "default", "replay")
    return {"session_id": session.id, "state": snapshot(session)}


@app.get("/api/state")
def state(x_session_id: str | None = Header(default=None)):
    return snapshot(get_session(x_session_id))


@app.post("/api/reset")
def reset(body: ResetRequest, x_session_id: str | None = Header(default=None)):
    session = get_session(x_session_id)
    if body.mode == "live" and not model_adapter.live_configured():
        raise HTTPException(400, "Live mode is not configured. Set your provider credentials and restart.")
    try:
        with session.lock:
            check_run(session, body.expected_run_id)
            runner.reset_run(session, body.scenario_id, body.variant_id, body.mode, body.attack_text)
            return snapshot(session)
    except (KeyError, StopIteration):
        raise HTTPException(404, "Unknown scenario or variant.")


@app.patch("/api/policy")
def update_policy(body: PolicyRequest, x_session_id: str | None = Header(default=None)):
    session = get_session(x_session_id)
    try:
        with session.lock:
            check_run(session, body.expected_run_id)
            apply_policy_change(session, body.allowed_documents, body.allowed_recipients, body.always_require_approval)
            return snapshot(session)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.post("/api/step")
def step(body: RunRequest, x_session_id: str | None = Header(default=None)):
    session = get_session(x_session_id)
    try:
        runner.step(session, expected_run_id=body.expected_run_id)
    except runner.RunConflict as exc:
        raise HTTPException(409, str(exc))
    return snapshot(session)


@app.post("/api/actions/{action_id}/approval")
def approval(action_id: str, body: ApprovalRequest, x_session_id: str | None = Header(default=None)):
    session = get_session(x_session_id)
    try:
        with session.lock:
            check_run(session, body.expected_run_id)
            resolve_approval(session, action_id, body.approve)
            return snapshot(session)
    except KeyError:
        raise HTTPException(404, "Unknown action.")


# Serve the built frontend (npm run build) from the same origin.
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.is_dir():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
