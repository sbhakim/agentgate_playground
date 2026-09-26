"""Check and execute tools under the same lock as approvals and policy edits."""

import hashlib
import json
import secrets
import time

from . import simulator
from .policy import RULE_TEXT, PolicyContext, evaluate_action, normalize_recipient, raise_label
from .scenarios import load_catalog
from .schemas import LABEL_ORDER, Decision, Draft, Policy
from .sessions import Pending, Session, add_event, find_action

APPROVAL_TTL_SECONDS = 10 * 60   # generous, so an approval does not expire mid-pitch


def policy_context(session: Session) -> PolicyContext:
    catalog = load_catalog()
    return PolicyContext(session.policy, catalog.doc_labels, catalog.contact_classes, session.drafts)


def content_hash(draft: Draft) -> str:
    snapshot = {"recipient": draft.recipient, "subject": draft.subject, "body": draft.body}
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _display_args(raw_args) -> dict:
    """Keep large or malformed arguments from flooding the timeline."""
    if not isinstance(raw_args, dict):
        return {"(invalid)": str(raw_args)[:200]}
    shown = {}
    for key, value in list(raw_args.items())[:10]:
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        shown[str(key)[:40]] = text[:600]
    return shown


def _finish_if_idle(session: Session) -> None:
    if session.pending:
        session.status = "awaiting_approval"
    elif session.mode == "replay" and session.replay_index >= session.replay_total:
        session.status = "finished"
    else:
        session.status = "running"


def _mark_stale(session: Session, action_id: str, reason: str) -> None:
    session.pending.pop(action_id, None)
    entry = find_action(session, action_id)
    if entry:
        entry["status"] = "stale"
        entry["stale_reason"] = reason
    session.notes_for_model.append(f"The pending send {action_id} was cancelled: {reason}")


def _raise_session_label(session: Session, document_id: str, doc_label: str) -> None:
    new_label = raise_label(session.session_label, doc_label)
    if new_label == session.session_label:
        return
    session.session_label = new_label
    session.label_history.append({"label": new_label, "because": document_id, "seq": session.seq})
    # A draft made before this read still needs the higher label.
    for draft in session.drafts.values():
        if not draft.sent and LABEL_ORDER[draft.label] < LABEL_ORDER[new_label]:
            draft.label = new_label
    for pending in list(session.pending.values()):
        if session.drafts[pending.draft_id].label != pending.label:
            _mark_stale(session, pending.action_id, "the draft's data label was raised after approval was requested")


def dispatch_action(session: Session, tool: str, raw_args, source: str) -> tuple[dict, dict]:
    """Return the timeline entry and the tool result seen by the model."""
    with session.lock:
        session.proposals += 1
        args = raw_args if isinstance(raw_args, dict) else {}
        decision = evaluate_action(tool, args, policy_context(session))

        # Retrying a send must not open a second approval for the same draft.
        if (decision.decision != "deny" and tool == "send_draft"
                and any(p.draft_id == args.get("draft_id") for p in session.pending.values())):
            decision = Decision("deny", "already_pending", [RULE_TEXT["already_pending"]])

        entry = add_event(
            session, "action", action_id=f"act-{secrets.token_hex(8)}", source=source,
            tool=tool, args=_display_args(raw_args), decision=decision.decision,
            rule_id=decision.rule_id, reasons=decision.reasons,
            policy_version=session.policy.version, label_before=session.session_label,
            status="proposed", result=None,
        )

        if decision.decision == "deny":
            entry["status"] = "denied"
            # For the audience only; never included in the result the model sees.
            entry["without_gate"] = simulator.describe_prevented(session, tool, args, decision.rule_id)
            result = {"status": "denied", "rule": decision.rule_id, "reason": decision.reasons[0]}
        elif decision.decision == "require_approval":
            draft = session.drafts[args["draft_id"]]
            session.pending[entry["action_id"]] = Pending(
                action_id=entry["action_id"], draft_id=draft.id, content_hash=content_hash(draft),
                label=draft.label, policy_version=session.policy.version, run_id=session.run_id,
                expires_at=time.time() + APPROVAL_TTL_SECONDS,
            )
            entry["status"] = "awaiting_approval"
            entry["result"] = {"draft_id": draft.id}
            result = {"status": "awaiting_approval", "action_id": entry["action_id"],
                      "note": "A human must approve this send in the AgentGate interface. Do not retry it."}
        else:
            try:
                result = _execute(session, tool, args, entry)
                entry["status"] = "executed"
            except (KeyError, ValueError):
                entry["status"] = "failed"
                entry["result"] = {"error": "The simulated tool failed."}
                result = {"status": "failed", "reason": "The simulated tool failed."}

        entry["label_after"] = session.session_label
        _finish_if_idle(session)
        return entry, result


def _execute(session: Session, tool: str, args: dict, entry: dict) -> dict:
    if tool == "read_document":
        doc = load_catalog().documents[args["document_id"]]
        body = simulator.read_document(session, doc["id"])
        _raise_session_label(session, doc["id"], doc["label"])
        entry["result"] = {"document_id": doc["id"], "label": doc["label"], "chars": len(body)}
        return {"status": "ok", "document_id": doc["id"], "title": doc["title"],
                "label": doc["label"], "content": body}

    if tool == "create_draft":
        draft = simulator.create_draft(session, normalize_recipient(args["recipient"]),
                                       args["subject"], args["body"])
        entry["result"] = {"draft_id": draft.id, "label": draft.label}
        return {"status": "ok", "draft_id": draft.id, "label": draft.label,
                "note": "Draft saved in the mock workspace. It has not been sent."}

    receipt = simulator.send_draft(session, session.drafts[args["draft_id"]])
    entry["result"] = {"receipt_id": receipt["receipt_id"], "draft_id": receipt["draft_id"]}
    return {"status": "sent", "receipt_id": receipt["receipt_id"],
            "note": "Simulated send: a record was added to the mock outbox. No real email exists."}


def resolve_approval(session: Session, action_id: str, approve: bool) -> dict:
    """Apply a human decision from the trusted UI. Safe to call twice."""
    with session.lock:
        entry = find_action(session, action_id)
        if entry is None:
            raise KeyError(action_id)
        pending = session.pending.get(action_id)
        if pending is None:
            return entry   # already executed, rejected or stale: repeat clicks change nothing

        draft = session.drafts.get(pending.draft_id)
        stale_reason = None
        if pending.run_id != session.run_id:
            stale_reason = "the scenario was reset"
        elif pending.policy_version != session.policy.version:
            stale_reason = "the policy changed after approval was requested"
        elif draft is None or draft.sent:
            stale_reason = "the draft no longer exists or was already sent"
        elif content_hash(draft) != pending.content_hash:
            stale_reason = "the draft content changed"
        elif draft.label != pending.label:
            stale_reason = "the draft's data label changed"
        elif time.time() > pending.expires_at:
            stale_reason = "the approval request expired"

        if stale_reason:
            _mark_stale(session, action_id, stale_reason)
        elif not approve:
            session.pending.pop(action_id)
            entry["status"] = "rejected"
            session.notes_for_model.append(f"A human rejected the send {action_id}. Do not retry it.")
        else:
            session.pending.pop(action_id)
            decision = evaluate_action("send_draft", {"draft_id": draft.id}, policy_context(session), approved=True)
            entry["approval"] = {"rule_id": decision.rule_id, "reasons": decision.reasons}
            if decision.decision == "allow":
                receipt = simulator.send_draft(session, draft)
                entry["status"] = "executed"
                entry["result"] = {"receipt_id": receipt["receipt_id"], "draft_id": draft.id}
                session.notes_for_model.append(
                    f"A human approved {action_id}; draft {draft.id} was sent (simulated), receipt {receipt['receipt_id']}.")
            else:   # a hard denial can never be approved away
                entry["status"] = "denied"
                entry["rule_id"] = decision.rule_id
                entry["reasons"] = decision.reasons
                entry["without_gate"] = simulator.describe_prevented(session, "send_draft", {"draft_id": draft.id}, decision.rule_id)

        _finish_if_idle(session)
        return entry


def apply_policy_change(session: Session, allowed_documents: list[str],
                        allowed_recipients: list[str], always_require_approval: bool) -> None:
    """A trusted edit from the Permissions panel. Invalidates every pending approval."""
    catalog = load_catalog()
    unknown = (set(allowed_documents) - catalog.documents.keys()) | (set(allowed_recipients) - catalog.contacts.keys())
    if unknown:
        raise ValueError(f"Unknown documents or recipients: {sorted(unknown)}")
    with session.lock:
        old = session.policy
        new = Policy(version=old.version + 1, allowed_documents=sorted(set(allowed_documents)),
                     allowed_recipients=sorted(set(allowed_recipients)),
                     always_require_approval=always_require_approval)
        # If the timeline is full, leave the policy and approvals alone.
        add_event(session, "policy_change", version=new.version, summary=_policy_diff(old, new))
        session.policy = new
        for action_id in list(session.pending):
            _mark_stale(session, action_id, "the policy changed after approval was requested")
        _finish_if_idle(session)


def _policy_diff(old: Policy, new: Policy) -> list[str]:
    changes = []
    for doc in sorted(set(new.allowed_documents) - set(old.allowed_documents)):
        changes.append(f"Allowed reading {doc}")
    for doc in sorted(set(old.allowed_documents) - set(new.allowed_documents)):
        changes.append(f"Blocked reading {doc}")
    for r in sorted(set(new.allowed_recipients) - set(old.allowed_recipients)):
        changes.append(f"Allowed recipient {r}")
    for r in sorted(set(old.allowed_recipients) - set(new.allowed_recipients)):
        changes.append(f"Removed recipient {r}")
    if new.always_require_approval != old.always_require_approval:
        changes.append("Approval required for every send" if new.always_require_approval
                       else "Approval only when a label rule asks for it")
    return changes or ["No effective change"]
