import { useState } from "react";
import type { Label, RunSummary, State } from "../types";
import { Icon, LabelChip, RULE_TITLES } from "./ui";

const LABELS: Label[] = ["public", "internal", "confidential"];

export function SessionLabelPanel({ state }: { state: State }) {
  const current = state.label_history[state.label_history.length - 1];
  return (
    <section className="panel" aria-labelledby="label-h">
      <div className="panel-head"><h2 id="label-h"><Icon name="lock" size={14} />Session data label</h2></div>
      <div className="panel-body">
        <div className="label-meter" role="img" aria-label={`Session label is ${state.session_label}`}>
          {LABELS.map((l) => (
            <div key={l} className={`${l} ${LABELS.indexOf(l) <= LABELS.indexOf(state.session_label) ? "on" : ""}`}>{l}</div>
          ))}
        </div>
        <p className="label-explain">
          {current && current.because !== "start"
            ? <>Raised by reading <span className="mono">{current.because}</span>. It never goes down during a run.</>
            : "Nothing sensitive has been read yet. Reading a document raises this to that document's label."}
        </p>
      </div>
    </section>
  );
}

export function WorkspacePanel({ state }: { state: State }) {
  const [tab, setTab] = useState<"drafts" | "outbox">("drafts");
  return (
    <section className="panel" aria-labelledby="ws-h">
      <div className="panel-head">
        <h2 id="ws-h"><span className="step-num">4</span>Workspace</h2>
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={tab === "drafts"} onClick={() => setTab("drafts")}>
            Drafts<span className="count">{state.drafts.length}</span></button>
          <button role="tab" aria-selected={tab === "outbox"} onClick={() => setTab("outbox")}>
            Outbox<span className="count">{state.outbox.length}</span></button>
        </div>
      </div>
      <div className="panel-body" role="tabpanel">
        {tab === "drafts" && (state.drafts.length === 0
          ? <div className="empty">No drafts. Creating a draft never sends it.</div>
          : state.drafts.map((d) => (
            <article className="mail" key={d.id}>
              <div className="mail-top">
                <span className="mono small">{d.id}</span>
                <span style={{ display: "flex", gap: 6 }}>
                  <LabelChip label={d.label} />
                  {d.sent ? <span className="badge badge-allow">Sent (mock)</span> : <span className="class-chip">not sent</span>}
                </span>
              </div>
              <div className="mail-subject">{d.subject}</div>
              <div className="mail-to">To {d.recipient} {d.recipient_class && <span className="class-chip">{d.recipient_class}</span>}</div>
              <div className="mail-body">{d.body}</div>
            </article>
          )))}
        {tab === "outbox" && (state.outbox.length === 0
          ? <div className="empty">Outbox empty. Nothing has been sent, even in simulation.</div>
          : state.outbox.map((r) => (
            <article className="mail sent" key={r.receipt_id}>
              <div className="mail-top"><span className="mono small">{r.receipt_id}</span><LabelChip label={r.label} /></div>
              <div className="mail-subject">{r.subject}</div>
              <div className="mail-to">To {r.recipient}</div>
            </article>
          )))}
        <Prevented state={state} />
        <p className="small muted" style={{ margin: "10px 0 0" }}>
          <Icon name="info" size={12} /> The outbox is a local list. No real email is sent.
        </p>
      </div>
    </section>
  );
}

function Prevented({ state }: { state: State }) {
  const stopped = state.timeline.filter((e) => e.kind === "action" && e.status === "denied" && e.without_gate);
  if (!stopped.length) return null;
  return (
    <div className="prevented">
      <div className="eyebrow">Stopped by the gate ({stopped.length})</div>
      <ul>{stopped.map((e) => e.kind === "action" && <li key={e.seq}>{e.without_gate}</li>)}</ul>
      <div className="small muted">Described, not performed: none of this ran.</div>
    </div>
  );
}

function summaryText(s: RunSummary): string {
  if (!s.send_status) return "No send attempted";
  if (s.send_status === "executed") return `Send allowed · ${s.outbox} in outbox`;
  if (s.send_status === "denied") return `Send denied (${RULE_TITLES[s.send_rule ?? ""] ?? s.send_rule})`;
  if (s.send_status === "awaiting_approval") return "Send waiting for approval";
  return `Send ${s.send_status}`;
}

export function ComparePanel({ state }: { state: State }) {
  const prev = state.last_summary;
  const actions = state.timeline.filter((e) => e.kind === "action");
  const sends = actions.filter((e) => e.kind === "action" && e.tool === "send_draft");
  const lastSend = sends[sends.length - 1];
  const current: RunSummary | null = actions.length ? {
    scenario: "", variant: "", mode: state.mode, session_label: state.session_label,
    send_status: lastSend && lastSend.kind === "action" ? lastSend.status : null,
    send_rule: lastSend && lastSend.kind === "action" ? lastSend.rule_id : null,
    outbox: state.outbox.length, denied: state.counts.denied,
  } : null;
  if (!prev) return null;
  return (
    <section className="panel" aria-labelledby="cmp-h">
      <div className="panel-head"><h2 id="cmp-h"><Icon name="sliders" size={14} />Previous run vs this run</h2></div>
      <div className="panel-body">
        <div className="compare">
          <div>
            <div className="ttl">Previous ({prev.mode}) · {prev.scenario}{prev.variant !== "Default" && ` · ${prev.variant}`}</div>
            <LabelChip label={prev.session_label} />
            <div style={{ marginTop: 6 }}>{summaryText(prev)}</div>
          </div>
          <div>
            <div className="ttl">This run</div>
            {current ? <><LabelChip label={current.session_label} /><div style={{ marginTop: 6 }}>{summaryText(current)}</div></>
              : <div className="muted">Not started</div>}
          </div>
        </div>
      </div>
    </section>
  );
}
