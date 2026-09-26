// Mirrors the small API contract in backend/app/main.py.

export type Label = "public" | "internal" | "confidential";
export type DecisionKind = "allow" | "deny" | "require_approval";
export type ActionStatus = "proposed" | "denied" | "awaiting_approval" | "executed" | "failed" | "stale" | "rejected";
export type RunStatus = "ready" | "running" | "awaiting_approval" | "finished" | "error";
export type Mode = "replay" | "live";

export interface DocumentInfo { id: string; title: string; label: Label; body: string; injection?: string }
export interface Contact { email: string; name: string; class: "internal" | "external" }
export interface Variant { id: string; label: string; task: string; inject: boolean; document: string; steps: number }
export interface Scenario { id: string; title: string; summary: string; preset: string; variants: Variant[] }
export interface LabelRule { label: Label; internal: DecisionKind; external: DecisionKind }
export interface Attack { id: string; label: string; text: string }
export interface Catalog { documents: DocumentInfo[]; attacks: Attack[]; contacts: Contact[]; scenarios: Scenario[]; label_rules: LabelRule[] }

export interface Policy {
  version: number;
  allowed_documents: string[];
  allowed_recipients: string[];
  always_require_approval: boolean;
}

export interface ActionEntry {
  kind: "action";
  seq: number;
  action_id: string;
  source: "replay" | "live";
  tool: string;
  args: Record<string, string>;
  decision: DecisionKind;
  rule_id: string;
  reasons: string[];
  policy_version: number;
  label_before: Label;
  label_after?: Label;
  status: ActionStatus;
  result: Record<string, string | number> | null;
  stale_reason?: string;
  approval?: { rule_id: string; reasons: string[] };
  from_injection?: boolean;
  without_gate?: string | null;
}

export interface OtherEntry {
  kind: "run_start" | "policy_change" | "model_message" | "note";
  seq: number;
  text?: string;
  summary?: string[];
  version?: number;
  scenario?: string;
  variant?: string;
  mode?: Mode;
  task?: string;
  custom_attack?: boolean;
}

export type TimelineEntry = ActionEntry | OtherEntry;

export interface Draft {
  id: string; recipient: string; recipient_class: string | null; subject: string;
  body: string; label: Label; sent: boolean;
}
export interface Receipt { receipt_id: string; draft_id: string; recipient: string; subject: string; body: string; label: Label }
export interface PendingApproval {
  action_id: string; draft_id: string; recipient: string; recipient_class: string | null;
  subject: string; body: string; label: Label; expires_at: number;
}
export interface RunSummary {
  scenario: string; variant: string; mode: Mode; session_label: Label;
  send_status: ActionStatus | null; send_rule: string | null; outbox: number; denied: number;
}

export interface State {
  run_id: number;
  scenario_id: string;
  variant_id: string;
  mode: Mode;
  status: RunStatus;
  error: string | null;
  step_in_flight: boolean;
  policy: Policy;
  session_label: Label;
  label_history: { label: Label; because: string; seq: number }[];
  injected: boolean;
  custom_attack: string | null;
  drafts: Draft[];
  outbox: Receipt[];
  pending: PendingApproval[];
  timeline: TimelineEntry[];
  replay: { index: number; total: number; next_tool: string | null };
  counts: { proposed: number; denied: number; awaiting: number; executed: number };
  live: { configured: boolean; model: string; effort: string; calls: number; max_calls: number; max_proposals: number };
  last_summary: RunSummary | null;
}
