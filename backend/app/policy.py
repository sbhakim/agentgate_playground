"""Policy decisions only: no I/O or state changes."""

from dataclasses import dataclass
from typing import Optional

from pydantic import ValidationError

from .schemas import (
    LABEL_ORDER, MAX_BODY_CHARS, MAX_SUBJECT_CHARS, TOOL_ARGS,
    Decision, Draft, Policy,
)

# Extra restrictions for valid labels and recipient classes.
LABEL_RULES = {
    ("confidential", "external"): ("deny", "confidential_external"),
    ("confidential", "internal"): ("require_approval", "confidential_internal"),
    ("internal", "external"): ("require_approval", "internal_external"),
}

RULE_TEXT = {
    "unknown_tool": "Only read_document, create_draft and send_draft exist.",
    "invalid_arguments": "The tool arguments do not match the expected schema.",
    "unknown_document": "No document with that ID exists.",
    "document_not_permitted": "This document is not on the read allowlist.",
    "document_permitted": "The document is on the read allowlist.",
    "invalid_recipient": "A recipient must be exactly one plain ASCII email address.",
    "invalid_classification": "The document, draft, or recipient has an unknown classification.",
    "recipient_not_allowlisted": "This recipient is not on the recipient allowlist.",
    "content_limit": f"Subject must be 1-{MAX_SUBJECT_CHARS} characters and body at most {MAX_BODY_CHARS}.",
    "draft_permitted": "The recipient is allowlisted. The draft is saved, not sent.",
    "unknown_draft": "No draft with that ID exists in this session.",
    "already_sent": "This draft was already sent.",
    "already_pending": "This draft is already waiting for human approval.",
    "confidential_external": "Confidential data can never go to an external recipient.",
    "confidential_internal": "Confidential data needs human approval, even for internal recipients.",
    "internal_external": "Internal data needs human approval before leaving the club.",
    "approval_required_by_policy": "The policy requires a human to approve every send.",
    "approved_by_human": "A human approved this exact draft.",
    "send_permitted": "The recipient is allowlisted and the data label allows this send.",
}

FORBIDDEN_RECIPIENT_CHARS = set(' <>,;:"()[]\\')


@dataclass
class PolicyContext:
    policy: Policy
    doc_labels: dict[str, str]    # document id -> label
    contacts: dict[str, str]      # email -> "internal" | "external"
    drafts: dict[str, Draft]      # only this session's drafts


def normalize_recipient(raw: str) -> Optional[str]:
    """The demo treats its synthetic addresses as case-insensitive."""
    value = raw.strip()
    if (not value or not value.isascii() or not value.isprintable()
            or any(c in FORBIDDEN_RECIPIENT_CHARS for c in value)):
        return None
    if value.count("@") != 1:
        return None
    local, domain = value.split("@")
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        return None
    return value.lower()


def raise_label(current: str, new: str) -> str:
    return new if LABEL_ORDER[new] > LABEL_ORDER[current] else current


def _decide(rules: list[tuple[str, str]], approved: bool, ok_rule: str) -> Decision:
    """Combine individual rule results. Hard denials always win."""
    denies = [r for d, r in rules if d == "deny"]
    if denies:
        return Decision("deny", denies[0], [RULE_TEXT[r] for r in denies])
    needs = [r for d, r in rules if d == "require_approval"]
    if needs:
        if approved:
            return Decision("allow", "approved_by_human",
                            [RULE_TEXT["approved_by_human"]] + [RULE_TEXT[r] for r in needs])
        return Decision("require_approval", needs[0], [RULE_TEXT[r] for r in needs])
    return Decision("allow", ok_rule, [RULE_TEXT[ok_rule]])


def evaluate_action(tool: str, raw_args: dict, ctx: PolicyContext, approved: bool = False) -> Decision:
    """Decide whether one proposed tool call may run."""
    if tool not in TOOL_ARGS:
        return Decision("deny", "unknown_tool", [RULE_TEXT["unknown_tool"]])
    try:
        args = TOOL_ARGS[tool].model_validate(raw_args)
    except ValidationError:
        return Decision("deny", "invalid_arguments", [RULE_TEXT["invalid_arguments"]])

    policy = ctx.policy

    if tool == "read_document":
        if args.document_id not in ctx.doc_labels:
            return Decision("deny", "unknown_document", [RULE_TEXT["unknown_document"]])
        if ctx.doc_labels[args.document_id] not in LABEL_ORDER:
            return Decision("deny", "invalid_classification", [RULE_TEXT["invalid_classification"]])
        if args.document_id not in policy.allowed_documents:
            return Decision("deny", "document_not_permitted", [RULE_TEXT["document_not_permitted"]])
        return Decision("allow", "document_permitted", [RULE_TEXT["document_permitted"]])

    if tool == "create_draft":
        recipient = normalize_recipient(args.recipient)
        if recipient is None:
            return Decision("deny", "invalid_recipient", [RULE_TEXT["invalid_recipient"]])
        rules = []
        if recipient not in policy.allowed_recipients or recipient not in ctx.contacts:
            rules.append(("deny", "recipient_not_allowlisted"))
        elif ctx.contacts[recipient] not in ("internal", "external"):
            rules.append(("deny", "invalid_classification"))
        if not (1 <= len(args.subject.strip()) <= MAX_SUBJECT_CHARS) or len(args.body) > MAX_BODY_CHARS:
            rules.append(("deny", "content_limit"))
        return _decide(rules, approved, "draft_permitted")

    # Sending needs fresh checks; saving the draft did not grant permission to send.
    draft = ctx.drafts.get(args.draft_id)
    if draft is None:
        return Decision("deny", "unknown_draft", [RULE_TEXT["unknown_draft"]])
    if draft.sent:
        return Decision("deny", "already_sent", [RULE_TEXT["already_sent"]])
    rules = []
    if draft.label not in LABEL_ORDER:
        rules.append(("deny", "invalid_classification"))
    # Re-check the recipient: the allowlist may have changed since the draft was made.
    if draft.recipient not in policy.allowed_recipients or draft.recipient not in ctx.contacts:
        rules.append(("deny", "recipient_not_allowlisted"))
    elif ctx.contacts[draft.recipient] not in ("internal", "external"):
        rules.append(("deny", "invalid_classification"))
    else:
        label_rule = LABEL_RULES.get((draft.label, ctx.contacts[draft.recipient]))
        if label_rule:
            rules.append(label_rule)
    if policy.always_require_approval:
        rules.append(("require_approval", "approval_required_by_policy"))
    return _decide(rules, approved, "send_permitted")
