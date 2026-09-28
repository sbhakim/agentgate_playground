import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "./api";
import type { Catalog, Mode, Policy, State } from "./types";
import { ActionTimeline } from "./components/ActionTimeline";
import { ApprovalDialog } from "./components/ApprovalDialog";
import { PolicyPanel } from "./components/PolicyPanel";
import { ScenarioCards, ScenarioPanel } from "./components/ScenarioPanel";
import { ComparePanel, SessionLabelPanel, WorkspacePanel } from "./components/WorkspacePanel";
import { Icon } from "./components/ui";

export default function App() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [state, setState] = useState<State | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [attackText, setAttackText] = useState("");
  const [dismissed, setDismissed] = useState<string | null>(null);
  const requestInFlight = useRef(false);

  useEffect(() => {
    Promise.all([api.catalog(), api.start()])
      .then(([c, s]) => { setCatalog(c); setState(s); })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  // Catch a second click before React has time to disable the buttons.
  const run = useCallback(async (call: () => Promise<State>, selectLatest = false) => {
    if (requestInFlight.current) return;
    requestInFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const next = await call();
      setState(next);
      if (selectLatest) {
        const actions = next.timeline.filter((e) => e.kind === "action");
        setSelected(actions.length ? actions[actions.length - 1].seq : null);
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError(e.message);
        setState(await api.state().catch(() => state!));
      } else if (e instanceof ApiError && e.status === 401) {
        setError("The server restarted, so the demo state was cleared. Starting a fresh session.");
        try {
          setState(await api.start());
        } catch (recoveryError) {
          setError(recoveryError instanceof Error ? recoveryError.message : String(recoveryError));
        }
      } else {
        setError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      requestInFlight.current = false;
      setBusy(false);
    }
  }, [state]);

  const reset = useCallback((scenarioId: string, variantId: string, mode: Mode, attack?: string) => {
    if (!state) return;
    setSelected(null);
    setDismissed(null);
    return run(() => api.reset(state.run_id, scenarioId, variantId, mode, attack));
  }, [run, state]);

  const next = useCallback(() => {
    if (state) run(() => api.step(state.run_id), true);
  }, [run, state]);

  const pending = state?.pending[0] ?? null;
  const dialogOpen = !!pending && dismissed !== pending.action_id;

  // Keyboard shortcut for presenting: N = next action, R = reset.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement;
      if (dialogOpen || e.metaKey || e.ctrlKey || e.altKey || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName)) return;
      if (!state || busy) return;
      if (e.key === "n" || e.key === "N") next();
      if (e.key === "r" || e.key === "R") reset(state.scenario_id, state.variant_id, state.mode);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dialogOpen, state, busy, next, reset]);

  if (!catalog || !state) {
    return (
      <div className="app">
        <div className={error ? "error-bar" : "banner"}>{error ?? "Loading AgentGate Playground…"}</div>
      </div>
    );
  }

  const inProgress = state.status === "running" || state.status === "awaiting_approval";
  const selectScenario = (scenarioId: string, variantId: string) => {
    if (scenarioId === state.scenario_id && variantId === state.variant_id) return;
    if (inProgress && !window.confirm("Switching scenarios resets the current run. Continue?")) return;
    reset(scenarioId, variantId, state.mode);
  };

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <span className="brand-mark"><Icon name="shield" size={22} /></span>
          <div>
            <h1>AgentGate Playground</h1>
            <p>The model proposes. The policy decides.</p>
          </div>
        </div>
        <div className="header-controls">
          <span className="safety-pill" title="Documents are synthetic fixtures, drafts live in memory, and the outbox is a list.">
            <Icon name="shield" size={14} /><strong>Simulated workspace</strong>
          </span>
          <div className="segmented" role="group" aria-label="Mode">
            <button aria-pressed={state.mode === "replay"} disabled={busy}
              onClick={() => state.mode !== "replay" && reset(state.scenario_id, state.variant_id, "replay")}>
              <Icon name="play" size={13} />Replay</button>
            <button aria-pressed={state.mode === "live"} disabled={busy || !state.live.configured}
              title={state.live.configured ? `Live model: ${state.live.model}` : "Configure provider credentials on the server to enable"}
              onClick={() => state.mode !== "live" && reset(state.scenario_id, state.variant_id, "live")}>
              <Icon name="bot" size={13} />Live model</button>
          </div>
        </div>
      </header>

      {error && (
        <div className="error-bar" role="alert">
          <span><Icon name="alert" size={14} /> {error}</span>
          <button className="btn btn-danger" onClick={() => setError(null)}>Dismiss</button>
        </div>
      )}

      {pending && !dialogOpen && (
        <div className="banner" style={{ borderLeftColor: "var(--wait)" }}>
          <span><Icon name="pause" size={14} /> A send to <strong>{pending.recipient}</strong> is waiting for your decision.</span>
          <button className="btn" onClick={() => setDismissed(null)}>Review send</button>
        </div>
      )}

      <ScenarioCards catalog={catalog} state={state} disabled={busy} onSelect={selectScenario} />

      <main className="grid">
        <div className="col">
          <ScenarioPanel catalog={catalog} state={state} disabled={busy} attackText={attackText}
            onAttackText={setAttackText}
            onSelectVariant={(v) => selectScenario(state.scenario_id, v)}
            onRunAttack={() => reset(state.scenario_id, state.variant_id, "live", attackText)} />
          <PolicyPanel catalog={catalog} policy={state.policy} runId={state.run_id} disabled={busy}
            hasPending={state.pending.length > 0}
            onApply={(p: Omit<Policy, "version">) => run(() => api.updatePolicy(state.run_id, p))} />
        </div>
        <div className="col">
          <ActionTimeline state={state} busy={busy} selected={selected} onSelect={setSelected} onNext={next}
            onReset={() => reset(state.scenario_id, state.variant_id, state.mode)} />
        </div>
        <div className="col col-right">
          <SessionLabelPanel state={state} />
          <WorkspacePanel state={state} />
          <ComparePanel state={state} />
        </div>
      </main>

      <footer className="counters" aria-label="Run counters">
        <div className="counters-inner">
          <div className="counter"><b>{state.counts.proposed}</b><span>proposed</span></div>
          <div className="counter allow"><b>{state.counts.executed}</b><span>executed</span></div>
          <div className="counter deny"><b>{state.counts.denied}</b><span>denied</span></div>
          <div className="counter wait"><b>{state.counts.awaiting}</b><span>awaiting approval</span></div>
          <div className="counter"><b>{state.outbox.length}</b><span>in mock outbox</span></div>
          <span className="tagline" title="Executed counts allowed reads and drafts too, not only sends.">
            Keys: <span className="mono">N</span> next · <span className="mono">R</span> reset
          </span>
        </div>
      </footer>

      {dialogOpen && pending && (
        <ApprovalDialog pending={pending} busy={busy}
          onClose={() => setDismissed(pending.action_id)}
          onDecide={(approve) => run(() => api.approve(state.run_id, pending.action_id, approve), true)} />
      )}
    </div>
  );
}
