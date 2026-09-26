"""Typed tool arguments, policy, decisions, and API request bodies."""

from dataclasses import dataclass, field
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Label = Literal["public", "internal", "confidential"]
DecisionKind = Literal["allow", "deny", "require_approval"]

LABEL_ORDER = {"public": 0, "internal": 1, "confidential": 2}

MAX_SUBJECT_CHARS = 120
MAX_BODY_CHARS = 4000
MAX_ATTACK_CHARS = 1000


class StrictArgs(BaseModel):
    # Unknown fields are an error, not something to ignore silently.
    model_config = ConfigDict(extra="forbid")


class ReadDocumentArgs(StrictArgs):
    document_id: str = Field(min_length=1, max_length=64)


class CreateDraftArgs(StrictArgs):
    recipient: str = Field(min_length=1, max_length=254)
    subject: str = Field(max_length=10_000)
    body: str = Field(max_length=50_000)


class SendDraftArgs(StrictArgs):
    draft_id: str = Field(min_length=1, max_length=64)


TOOL_ARGS = {
    "read_document": ReadDocumentArgs,
    "create_draft": CreateDraftArgs,
    "send_draft": SendDraftArgs,
}


class Policy(BaseModel):
    version: int = 1
    allowed_documents: list[str]
    allowed_recipients: list[str]
    always_require_approval: bool


@dataclass
class Decision:
    decision: DecisionKind
    rule_id: str
    reasons: list[str] = field(default_factory=list)


@dataclass
class Draft:
    id: str
    recipient: str
    subject: str
    body: str
    label: Label
    sent: bool = False


class RunRequest(BaseModel):
    expected_run_id: int


class ResetRequest(RunRequest):
    scenario_id: str
    variant_id: str = "default"
    mode: Literal["replay", "live"] = "replay"
    attack_text: Optional[str] = Field(default=None, max_length=MAX_ATTACK_CHARS)


class PolicyRequest(RunRequest):
    allowed_documents: list[str]
    allowed_recipients: list[str]
    always_require_approval: bool


class ApprovalRequest(RunRequest):
    approve: bool
