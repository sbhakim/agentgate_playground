import { useEffect } from "react";
import type { ActionEntry, State, TimelineEntry } from "../types";
import { Icon, LabelChip, RULE_TITLES, StatusBadge, describeAction, effectText, toolIcon } from "./ui";

interface Props {
  state: State;
  busy: boolean;
  selected: number | null;
  onSelect: (seq: number | null) => void;
  onNext: () => void;
  onReset: () => void;
}

const NEXT_PHRASE: Record<string, string> = {
  read_document: "read a document",
  create_draft: "write an email draft",
  send_draft: "send a draft",
};

function statusLine(state: State): { text: string; icon: string } {
  if (state.step_in_flight) return { text: "Waiting for the model's next proposal…", icon: "clock" };
  switch (state.status) {
    case "ready": return { text: "Ready. Press Next action to let the assistant propose its first step.", icon: "play" };
    case "running":
      return state.mode === "replay"
        ? { text: `Next, the assistant will try to ${NEXT_PHRASE[state.replay.next_tool ?? ""] ?? "continue"}.`, icon: "play" }
        : { text: "Next: ask the model for its next turn.", icon: "bot" };
    case "awaiting_approval": return { text: "Paused: a send needs a human decision.", icon: "pause" };
    case "finished": return { text: "Run complete. Reset, or pick another scenario.", icon: "check" };
    case "error": return { text: state.error ?? "The run stopped with an error.", icon: "alert" };
  }
}

export function ActionTimeline({ state, busy, selected, onSelect, onNext, onReset }: Props) {
  const line = statusLine(state);
  const canStep = !busy && !state.step_in_flight && (state.status === "ready" || state.status === "running");
  const progress = state.mode === "replay" && state.replay.total ? (state.replay.index / state.replay.total) * 100 : 0;
  const actions = state.timeline.filter((e): e is ActionEntry => e.kind === "action");
  const latest = actions[actions.length - 1];
  let actionNo = 0;

  // Keep the newest proposal on screen as the timeline grows.
  useEffect(() => {
    if (latest) document.getElementById(`act-${latest.seq}`)?.scrollIntoView({ block: "nearest" });
  }, [latest?.seq, latest?.status]);

  return (
    <section className="panel" aria-labelledby="timeline-h">
      <div className="panel-head">
        <h2 id="timeline-h"><span className="step-num">3</span>Action timeline</h2>
        <span className="small muted">
          {state.mode === "replay" ? "Replay: predefined proposals, real policy checks" : `Live: ${state.live.model}`}
        </span>
      </div>

      <div className="run-control">
        <button className="btn btn-primary btn-lg next" onClick={onNext} disabled={!canStep}>
          <Icon name={state.step_in_flight ? "clock" : "play"} size={18} />
          {busy || state.step_in_flight ? "Working…" : "Next action"}
        </button>
        <button className="btn" onClick={onReset} disabled={busy}><Icon name="reset" size={14} />Reset</button>
        <div className="run-meta" aria-live="polite">
          <div className="status-line"><Icon name={line.icon} size={16} />{line.text}</div>
          {state.mode === "replay" ? (
            <div className="progress" aria-label={`Step ${state.replay.index} of ${state.replay.total}`}>
              <div style={{ width: `${progress}%` }} />
            </div>
          ) : (
            <div className="small muted">Model turns {state.live.calls}/{state.live.max_calls} · tool proposals capped at {state.live.max_proposals}</div>
          )}
        </div>
      </div>

      {latest ? <Verdict entry={latest} /> : (
        <div className="flow-legend" aria-hidden="true">
          Every step goes <b>Document</b> → <b>Proposal</b> → <b>Policy decision</b> → <b>Simulated effect</b>
        </div>
      )}

      <ol className="timeline">
        {state.timeline.map((e: TimelineEntry) => {
          if (e.kind === "action") {
            actionNo += 1;
            return (
              <li key={e.seq} id={`act-${e.seq}`}>
                <ActionCard entry={e} n={actionNo} open={selected === e.seq}
                  onToggle={() => onSelect(selected === e.seq ? null : e.seq)} />
                {selected === e.seq && <Inspector entry={e} />}
              </li>
            );
          }
          return <li key={e.seq}><Note entry={e} /></li>;
        })}
        {actions.length === 0 && (
          <li className="empty">No proposals yet. Each action the assistant requests will appear here with the rule that decided it.</li>
        )}
      </ol>
    </section>
  );
}

function ActionCard({ entry, n, open, onToggle }: { entry: ActionEntry; n: number; open: boolean; onToggle: () => void }) {
  const why = entry.status === "stale" ? entry.stale_reason : entry.approval ? entry.approval.reasons[0] : entry.reasons[0];
  return (
    <button className={`t-card s-${entry.status}`} aria-expanded={open} onClick={onToggle}>
      <span className="t-num">{n}</span>
      <span className="t-main">
        <span className="t-title"><Icon name={toolIcon(entry.tool)} size={15} />{describeAction(entry)}
          {entry.source === "live" && <span className="class-chip">model</span>}
          {entry.from_injection && <span className="inject-chip"><Icon name="alert" size={11} />follows the hidden text</span>}</span>
        <span className="t-why" style={{ display: "block" }}>{why}</span>
        <span className="t-rule">rule: {entry.approval ? entry.approval.rule_id : entry.rule_id}</span>
        {entry.status === "denied" && entry.without_gate && (
          <span className="without-gate"><b>Without the gate:</b> {entry.without_gate}</span>
        )}
      </span>
      <StatusBadge entry={entry} />
    </button>
  );
}

function Verdict({ entry }: { entry: ActionEntry }) {
  const rule = entry.approval ? entry.approval.rule_id : entry.rule_id;
  return (
    <div className={`verdict v-${entry.status}`} aria-live="polite">
      <StatusBadge entry={entry} />
      <span className="verdict-text"><strong>{describeAction(entry)}</strong>
        <span> · {RULE_TITLES[rule] ?? rule}</span></span>
    </div>
  );
}

function Inspector({ entry }: { entry: ActionEntry }) {
  const labelChanged = entry.label_after && entry.label_after !== entry.label_before;
  return (
    <div className="inspector">
      <div className="chain">
        <div className="chain-step">
          <div className="eyebrow">1 · Source</div>
          <div className="value">{entry.source === "live" ? "Model tool call" : "Scripted fixture"}</div>
          <div className="small muted" style={{ marginTop: 4 }}>session label <LabelChip label={entry.label_before} /></div>
        </div>
        <div className="chain-step">
          <div className="eyebrow">2 · Proposal</div>
          <div className="value mono">{entry.tool}</div>
        </div>
        <div className="chain-step">
          <div className="eyebrow">3 · Policy decision</div>
          <div className="value"><strong>{RULE_TITLES[entry.rule_id] ?? entry.rule_id}</strong></div>
          <div className="small muted">policy v{entry.policy_version}</div>
        </div>
        <div className="chain-step">
          <div className="eyebrow">4 · Effect</div>
          <div className="value">{effectText(entry)}</div>
        </div>
      </div>
      {labelChanged && (
        <p className="small" style={{ margin: "10px 0 0" }}>
          Session label raised: <LabelChip label={entry.label_before} /> → <LabelChip label={entry.label_after!} />.
          Drafts created from now on (and unsent ones) carry this label.
        </p>
      )}
      <ul className="reasons">
        {entry.reasons.map((r) => <li key={r}>{r}</li>)}
        {entry.approval && entry.approval.rule_id !== entry.rule_id && <li>After approval: {entry.approval.reasons[0]}</li>}
      </ul>
      <div className="args" aria-label="Proposed arguments (truncated for display)">{JSON.stringify(entry.args, null, 2)}</div>
    </div>
  );
}

function Note({ entry }: { entry: Exclude<TimelineEntry, ActionEntry> }) {
  if (entry.kind === "run_start") {
    return (
      <div className="t-note">
        <Icon name="info" size={15} />
        <span>Run started: <strong>{entry.scenario}</strong>{entry.variant !== "Default" && ` · ${entry.variant}`} in {entry.mode} mode
          {entry.custom_attack && " with visitor-written text"}.</span>
      </div>
    );
  }
  if (entry.kind === "policy_change") {
    return (
      <div className="t-note policy">
        <Icon name="sliders" size={15} />
        <span><strong>Trusted policy change (v{entry.version}):</strong> {entry.summary?.join("; ")}. Pending approvals were cancelled.</span>
      </div>
    );
  }
  if (entry.kind === "model_message") {
    return (
      <div className="t-note model">
        <Icon name="bot" size={15} />
        <span><strong>Model says:</strong> {entry.text}</span>
      </div>
    );
  }
  return <div className="t-note"><Icon name="alert" size={15} /><span>{entry.text}</span></div>;
}
