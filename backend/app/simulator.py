"""Mock effects used by the dispatcher. No real email or personal files."""

import secrets
import time

from .scenarios import load_catalog
from .schemas import Draft
from .sessions import Session

INJECTED_DOCUMENT = "club-notes"


def read_document(session: Session, document_id: str) -> str:
    body = load_catalog().documents[document_id]["body"]
    if document_id == INJECTED_DOCUMENT and session.injection:
        body += session.injection
    return body


def create_draft(session: Session, recipient: str, subject: str, body: str) -> Draft:
    # Ownership comes from the session, not from keeping this ID secret.
    draft = Draft(id=f"draft-{secrets.token_hex(8)}", recipient=recipient,
                  subject=subject.strip(), body=body, label=session.session_label)
    session.drafts[draft.id] = draft
    return draft


def send_draft(session: Session, draft: Draft) -> dict:
    receipt = {
        "receipt_id": f"mock-{secrets.token_hex(8)}",
        "draft_id": draft.id,
        "recipient": draft.recipient,
        "subject": draft.subject,
        "body": draft.body,
        "label": draft.label,
        "time": time.time(),
    }
    session.outbox.append(receipt)
    draft.sent = True
    return receipt


def describe_prevented(session: Session, tool: str, args: dict, rule_id: str):
    """Describe the blocked effect for the UI without performing it."""
    catalog = load_catalog()
    if tool == "read_document" and rule_id == "document_not_permitted":
        doc = catalog.documents[args["document_id"]]
        return (f"The assistant would have received “{doc['title']}”, a {doc['label']} document "
                f"of {len(doc['body'])} characters.")
    if tool == "create_draft" and rule_id in ("recipient_not_allowlisted", "content_limit"):
        who = str(args.get("recipient", "?"))[:80]
        return f"An email to {who} would have been written and left one step away from being sent."
    if tool == "send_draft" and rule_id not in ("unknown_draft", "invalid_arguments"):
        draft = session.drafts.get(args.get("draft_id"))
        if draft is None:
            return None
        if rule_id == "already_sent":
            return f"The same email would have gone to {draft.recipient} a second time."
        return f"This {draft.label} email would have been sent to {draft.recipient}."
    return None
