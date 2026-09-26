"""Advance replay or live proposals through the same dispatcher."""

import json
from copy import deepcopy
from typing import Optional

from . import model_adapter
from .dispatcher import dispatch_action
from .scenarios import get_variant, load_catalog, preset_policy, resolve_aliases
from .sessions import Session, add_event

MAX_TOOL_PROPOSALS = 8   # per live run; a demo limit, not a tuned value
MAX_MODEL_CALLS = 6      # bounds text-only turns too

_adapter = None


class RunConflict(Exception):
    """The request does not fit the run's current state (HTTP 409)."""


def get_adapter():
    global _adapter
    if _adapter is None:
        _adapter = model_adapter.make_adapter()
    return _adapter


def summarize(session: Session) -> Optional[dict]:
    actions = [e for e in session.timeline if e["kind"] == "action"]
    if not actions:
        return None
    scenario, variant = get_variant(session.scenario_id, session.variant_id)
    sends = [e for e in actions if e["tool"] == "send_draft"]
    last_send = sends[-1] if sends else None
    return {
        "scenario": scenario["title"], "variant": variant["label"], "mode": session.mode,
        "session_label": session.session_label,
        "send_status": last_send["status"] if last_send else None,
        "send_rule": last_send["rule_id"] if last_send else None,
        "outbox": len(session.outbox), "denied": sum(e["status"] == "denied" for e in actions),
    }


def reset_run(session: Session, scenario_id: str, variant_id: str, mode: str,
              attack_text: Optional[str] = None) -> None:
    scenario, variant = get_variant(scenario_id, variant_id)   # KeyError/StopIteration if unknown
    with session.lock:
        # Keep a one-line summary of the previous run for side-by-side comparison.
        session.last_summary = summarize(session) or session.last_summary
        session.run_id += 1   # any in-flight model reply for the old run is now discarded
        session.scenario_id, session.variant_id, session.mode = scenario_id, variant_id, mode
        session.policy = preset_policy(scenario["preset"])
        session.session_label = "public"
        session.label_history = [{"label": "public", "because": "start", "seq": 0}]
        session.drafts, session.outbox, session.pending = {}, [], {}
        session.timeline, session.seq = [], 0
        session.replay_index, session.replay_total = 0, len(variant["replay"])
        session.aliases, session.notes_for_model = {}, []
        session.model_calls, session.proposals = 0, 0
        session.status, session.error, session.step_in_flight = "ready", None, False

        session.custom_attack = None
        if mode == "live" and attack_text and attack_text.strip():
            session.custom_attack = attack_text.strip()
            session.injection = "\n\n" + session.custom_attack
        elif variant["inject"]:
            session.injection = load_catalog().documents["club-notes"]["injection"]
        else:
            session.injection = None
        session.conversation = [{"role": "user", "content": variant["task"]}] if mode == "live" else []
        add_event(session, "run_start", scenario=scenario["title"], variant=variant["label"],
                  mode=mode, task=variant["task"], custom_attack=bool(mode == "live" and attack_text))


def step(session: Session, adapter=None, *, expected_run_id: Optional[int] = None) -> None:
    with session.lock:
        if expected_run_id is not None and expected_run_id != session.run_id:
            raise RunConflict("This run was reset. Refresh before trying again.")
        if session.step_in_flight:
            raise RunConflict("A step is already running.")
        if session.status == "awaiting_approval":
            raise RunConflict("Approve or reject the pending send first.")
        if session.status in ("finished", "error"):
            raise RunConflict("This run is over. Reset to start again.")
        session.step_in_flight = True
        run_id = session.run_id
        mode = session.mode
    try:
        if mode == "replay":
            _replay_step(session, run_id)
        else:
            _live_step(session, run_id, adapter or get_adapter())
    finally:
        with session.lock:
            if session.run_id == run_id:
                session.step_in_flight = False


def _replay_step(session: Session, run_id: int) -> None:
    with session.lock:
        if session.run_id != run_id:
            return
        _, variant = get_variant(session.scenario_id, session.variant_id)
        proposal = variant["replay"][session.replay_index]
        args = resolve_aliases(proposal["args"], session.aliases)
        entry, result = dispatch_action(session, proposal["tool"], args, "replay")
        session.replay_index += 1
        if session.replay_index == session.replay_total and not session.pending:
            session.status = "finished"
        # Fixture authors mark the proposals that follow the hidden instruction.
        entry["from_injection"] = bool(proposal.get("from_injection"))
        if proposal.get("save_as") and result.get("draft_id"):
            session.aliases[proposal["save_as"]] = result["draft_id"]


def _live_step(session: Session, run_id: int, adapter) -> None:
    with session.lock:
        if session.run_id != run_id:
            return
        if session.model_calls >= MAX_MODEL_CALLS:
            add_event(session, "note", text=f"Stopped: reached the limit of {MAX_MODEL_CALLS} model turns.")
            session.status = "finished"
            return
        if session.notes_for_model:
            _append_to_last_user_message(session, "[AgentGate] " + " ".join(session.notes_for_model))
            session.notes_for_model = []
        messages = deepcopy(session.conversation)
        catalog = load_catalog()
        system = model_adapter.build_system_prompt(catalog.documents, catalog.contacts)

    try:
        turn = adapter.next_turn(system, messages)     # no lock held here
        error = None
    except model_adapter.ModelError as exc:
        turn, error = None, str(exc)

    with session.lock:
        if session.run_id != run_id:
            return   # a late reply must not enter a newly reset run
        if error:
            session.status, session.error = "error", error
            add_event(session, "note", text=f"Model error: {error} Switch to Replay to continue the demo.")
            return
        session.model_calls += 1
        session.conversation.append({"role": "assistant", "content": turn.assistant_content})
        if turn.text:
            add_event(session, "model_message", text=turn.text[:2000])

        if turn.stop_reason == "refusal":
            add_event(session, "note", text="The model declined to continue this task.")
            session.status = "finished"
            return
        if turn.stop_reason == "max_tokens" or not turn.tool_calls:
            session.status = "finished"
            return

        tool_results, hit_limit = [], False
        for call in turn.tool_calls:   # sequential, each re-evaluated by the gate
            if session.proposals >= MAX_TOOL_PROPOSALS:
                hit_limit = True
                result = {"status": "not_executed", "reason": "The demo's tool-call limit was reached."}
            else:
                _, result = dispatch_action(session, call.name, call.input, "live")
            tool_results.append({"type": "tool_result", "tool_use_id": call.id,
                                 "content": json.dumps(result),
                                 "is_error": result["status"] in ("denied", "failed", "not_executed")})
        # Every tool_use gets its result in a single user message.
        session.conversation.append({"role": "user", "content": tool_results})
        if hit_limit:
            add_event(session, "note", text=f"Stopped: reached the limit of {MAX_TOOL_PROPOSALS} tool proposals.")
            session.status = "awaiting_approval" if session.pending else "finished"


def _append_to_last_user_message(session: Session, text: str) -> None:
    last = session.conversation[-1]
    if isinstance(last["content"], str):
        last["content"] = [{"type": "text", "text": last["content"]}]
    last["content"] = list(last["content"]) + [{"type": "text", "text": text}]
