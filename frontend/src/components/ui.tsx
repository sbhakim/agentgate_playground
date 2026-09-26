import type { ActionEntry, ActionStatus, Label } from "../types";

const PATHS: Record<string, string> = {
  shield: "M12 3l8 3v6c0 5-3.5 8.5-8 9.5C7.5 20.5 4 17 4 12V6l8-3z",
  check: "M5 12.5l4.5 4.5L19 7.5",
  x: "M6 6l12 12M18 6L6 18",
  pause: "M9 5v14M15 5v14",
  clock: "M12 7v5l3 2M12 21a9 9 0 110-18 9 9 0 010 18z",
  doc: "M7 3h7l5 5v13H7zM14 3v5h5",
  mail: "M4 6h16v12H4zM4 7l8 6 8-6",
  send: "M4 12l16-8-6 16-3-7-7-1z",
  play: "M7 5l12 7-12 7z",
  reset: "M4 12a8 8 0 1 0 2.5-5.8M4 4v4h4",
  lock: "M7 11V8a5 5 0 0110 0v3M6 11h12v9H6z",
  building: "M5 21V5l7-2v18M12 8h7v13M8 9h1M8 13h1M8 17h1M15 12h1M15 16h1",
  globe: "M12 21a9 9 0 100-18 9 9 0 000 18zM3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18",
  alert: "M12 4l9 16H3zM12 10v4M12 17.5v.5",
  bot: "M6 9h12v10H6zM12 5v4M9 13h.01M15 13h.01M9 16.5h6",
  sliders: "M4 7h10M18 7h2M4 17h4M12 17h8M14 5v4M8 15v4",
  info: "M12 21a9 9 0 110-18 9 9 0 010 18zM12 11v5M12 8v.5",
};

export function Icon({ name, size = 16 }: { name: keyof typeof PATHS | string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={PATHS[name] ?? PATHS.info} />
    </svg>
  );
}

const LABEL_ICON: Record<Label, string> = { public: "globe", internal: "building", confidential: "lock" };

export function LabelChip({ label }: { label: Label }) {
  return (
    <span className={`label-chip label-${label}`}>
      <Icon name={LABEL_ICON[label]} size={12} />
      {label}
    </span>
  );
}

const STATUS: Record<ActionStatus, { text: string; cls: string; icon: string }> = {
  proposed: { text: "Proposed", cls: "badge-stale", icon: "clock" },
  executed: { text: "Allowed", cls: "badge-allow", icon: "check" },
  denied: { text: "Denied", cls: "badge-deny", icon: "x" },
  awaiting_approval: { text: "Needs approval", cls: "badge-wait", icon: "pause" },
  stale: { text: "Stale", cls: "badge-stale", icon: "clock" },
  rejected: { text: "Rejected", cls: "badge-stale", icon: "x" },
  failed: { text: "Failed", cls: "badge-stale", icon: "alert" },
};

export function StatusBadge({ entry }: { entry: ActionEntry }) {
  const s = STATUS[entry.status];
  // A send should say what happened, not just that it was allowed.
  const text = entry.status === "executed" && entry.tool === "send_draft" ? "Sent (mock)" : s.text;
  return (
    <span className={`badge ${s.cls}`}>
      <Icon name={s.icon} size={12} />
      {text}
    </span>
  );
}

export function describeAction(e: ActionEntry): string {
  const a = e.args;
  if (e.tool === "read_document") return `Read document “${a.document_id ?? "?"}”`;
  if (e.tool === "create_draft") return `Draft email to ${a.recipient ?? "?"}`;
  if (e.tool === "send_draft") return `Send email (${a.draft_id ?? "?"})`;
  return `Unknown tool “${e.tool}”`;
}

export function toolIcon(tool: string): string {
  return tool === "read_document" ? "doc" : tool === "create_draft" ? "mail" : tool === "send_draft" ? "send" : "alert";
}

export function effectText(e: ActionEntry): string {
  const r = e.result ?? {};
  switch (e.status) {
    case "denied": return "Nothing happened. The tool never ran.";
    case "awaiting_approval": return "Paused. Waiting for a human in the approval dialog.";
    case "stale": return `Cancelled: ${e.stale_reason ?? "the approval request is out of date"}.`;
    case "rejected": return "A human rejected the send. Nothing was sent.";
    case "failed": return "The simulated tool failed.";
    case "executed":
      if (e.tool === "read_document") return `Returned ${r.chars} characters of a ${r.label} document.`;
      if (e.tool === "create_draft") return `Saved draft ${r.draft_id} (${r.label}). Not sent.`;
      if (e.tool === "send_draft") return `Added ${r.receipt_id} to the mock outbox.`;
      return "Done.";
    default: return "";
  }
}

export const RULE_TITLES: Record<string, string> = {
  document_permitted: "Document on allowlist",
  document_not_permitted: "Document not on allowlist",
  unknown_document: "Unknown document",
  unknown_tool: "Unknown tool",
  invalid_arguments: "Invalid arguments",
  invalid_recipient: "Invalid recipient format",
  invalid_classification: "Unknown data classification",
  recipient_not_allowlisted: "Recipient not on allowlist",
  content_limit: "Content size limit",
  draft_permitted: "Recipient on allowlist",
  unknown_draft: "Unknown draft",
  already_sent: "Already sent",
  already_pending: "Already waiting for approval",
  confidential_external: "Confidential → external",
  confidential_internal: "Confidential needs approval",
  internal_external: "Internal → external needs approval",
  approval_required_by_policy: "Policy: approve every send",
  approved_by_human: "Approved by a human",
  send_permitted: "Send permitted",
};
