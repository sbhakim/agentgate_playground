import pytest

from app.policy import PolicyContext, evaluate_action, normalize_recipient
from app.schemas import Draft, Policy

DOCS = {"club-notes": "public", "member-roster": "internal", "club-budget": "confidential"}
CONTACTS = {"coordinator@umbc-club.test": "internal", "sponsor@partner.test": "external"}


def make_ctx(drafts=None, approval=False, docs=("club-notes",),
             recipients=("coordinator@umbc-club.test", "sponsor@partner.test")):
    policy = Policy(allowed_documents=list(docs), allowed_recipients=list(recipients),
                    always_require_approval=approval)
    return PolicyContext(policy, DOCS, CONTACTS, drafts or {})


def draft(label, recipient, sent=False):
    return {"d1": Draft("d1", recipient, "Hi", "Body", label, sent)}


def test_allowed_read():
    assert evaluate_action("read_document", {"document_id": "club-notes"}, make_ctx()).decision == "allow"


def test_restricted_read_denied():
    d = evaluate_action("read_document", {"document_id": "member-roster"}, make_ctx())
    assert (d.decision, d.rule_id) == ("deny", "document_not_permitted")


def test_unknown_document_denied():
    d = evaluate_action("read_document", {"document_id": "passwords"}, make_ctx())
    assert (d.decision, d.rule_id) == ("deny", "unknown_document")


def test_unknown_tool_denied():
    d = evaluate_action("run_shell", {"cmd": "ls"}, make_ctx())
    assert (d.decision, d.rule_id) == ("deny", "unknown_tool")


@pytest.mark.parametrize("args", [
    {},                                              # missing field
    {"document_id": "club-notes", "admin": True},    # unexpected field
    {"document_id": 42},                             # wrong type
])
def test_malformed_arguments_denied(args):
    d = evaluate_action("read_document", args, make_ctx())
    assert (d.decision, d.rule_id) == ("deny", "invalid_arguments")


@pytest.mark.parametrize("raw,expected", [
    ("coordinator@umbc-club.test", "coordinator@umbc-club.test"),
    ("  Coordinator@UMBC-club.test ", "coordinator@umbc-club.test"),
    ("Coordinator <coordinator@umbc-club.test>", None),   # display name
    ("a@x.test, b@x.test", None),                         # multiple
    ("coordinаtor@umbc-club.test", None),                 # Cyrillic 'а'
    ("no-at-sign.test", None),
    ("a@@x.test", None),
    ("a@localhost", None),
    ("a\tb@x.test", None),
    ("a@x\ntest.test", None),
])
def test_normalize_recipient(raw, expected):
    assert normalize_recipient(raw) == expected


def test_draft_to_unlisted_recipient_denied():
    args = {"recipient": "recruiter@outside-mail.test", "subject": "Member list", "body": "..."}
    d = evaluate_action("create_draft", args, make_ctx())
    assert (d.decision, d.rule_id) == ("deny", "recipient_not_allowlisted")


def test_allowlist_is_exact_not_suffix():
    args = {"recipient": "evil.coordinator@umbc-club.test", "subject": "x", "body": "x"}
    assert evaluate_action("create_draft", args, make_ctx()).decision == "deny"


def test_draft_content_limits():
    too_long = {"recipient": "coordinator@umbc-club.test", "subject": "x" * 121, "body": "b"}
    empty = {"recipient": "coordinator@umbc-club.test", "subject": "  ", "body": "b"}
    for args in (too_long, empty):
        d = evaluate_action("create_draft", args, make_ctx())
        assert (d.decision, d.rule_id) == ("deny", "content_limit")


def test_draft_to_allowed_recipient():
    args = {"recipient": "coordinator@umbc-club.test", "subject": "Summary", "body": "Hi"}
    assert evaluate_action("create_draft", args, make_ctx()).decision == "allow"


@pytest.mark.parametrize("label,recipient,expected", [
    ("public", "coordinator@umbc-club.test", ("allow", "send_permitted")),
    ("public", "sponsor@partner.test", ("allow", "send_permitted")),
    ("internal", "coordinator@umbc-club.test", ("allow", "send_permitted")),
    ("internal", "sponsor@partner.test", ("require_approval", "internal_external")),
    ("confidential", "coordinator@umbc-club.test", ("require_approval", "confidential_internal")),
    ("confidential", "sponsor@partner.test", ("deny", "confidential_external")),
])
def test_label_matrix(label, recipient, expected):
    d = evaluate_action("send_draft", {"draft_id": "d1"}, make_ctx(drafts=draft(label, recipient)))
    assert (d.decision, d.rule_id) == expected


def test_global_approval_applies_to_public_send():
    ctx = make_ctx(drafts=draft("public", "coordinator@umbc-club.test"), approval=True)
    d = evaluate_action("send_draft", {"draft_id": "d1"}, ctx)
    assert (d.decision, d.rule_id) == ("require_approval", "approval_required_by_policy")


def test_approval_satisfies_requirement():
    ctx = make_ctx(drafts=draft("confidential", "coordinator@umbc-club.test"))
    d = evaluate_action("send_draft", {"draft_id": "d1"}, ctx, approved=True)
    assert (d.decision, d.rule_id) == ("allow", "approved_by_human")


def test_approval_never_overrides_hard_denial():
    ctx = make_ctx(drafts=draft("confidential", "sponsor@partner.test"), approval=True)
    d = evaluate_action("send_draft", {"draft_id": "d1"}, ctx, approved=True)
    assert (d.decision, d.rule_id) == ("deny", "confidential_external")


def test_send_rechecks_recipient_after_policy_change():
    ctx = make_ctx(drafts=draft("public", "sponsor@partner.test"),
                   recipients=("coordinator@umbc-club.test",))
    d = evaluate_action("send_draft", {"draft_id": "d1"}, ctx)
    assert (d.decision, d.rule_id) == ("deny", "recipient_not_allowlisted")


def test_unknown_and_sent_drafts_denied():
    assert evaluate_action("send_draft", {"draft_id": "nope"}, make_ctx()).rule_id == "unknown_draft"
    ctx = make_ctx(drafts=draft("public", "coordinator@umbc-club.test", sent=True))
    assert evaluate_action("send_draft", {"draft_id": "d1"}, ctx).rule_id == "already_sent"


def test_unknown_classifications_are_denied():
    ctx = make_ctx(drafts=draft("unknown", "sponsor@partner.test"))
    assert evaluate_action("send_draft", {"draft_id": "d1"}, ctx).rule_id == "invalid_classification"
    ctx.doc_labels = {"club-notes": "unknown"}
    assert evaluate_action("read_document", {"document_id": "club-notes"}, ctx).decision == "deny"
    ctx.contacts = {"sponsor@partner.test": "unknown"}
    args = {"recipient": "sponsor@partner.test", "subject": "Hi", "body": "Hi"}
    assert evaluate_action("create_draft", args, ctx).rule_id == "invalid_classification"
    ctx.drafts["d1"].label = "public"
    assert evaluate_action("send_draft", {"draft_id": "d1"}, ctx).decision == "deny"
