import json

import pytest
from fastapi.testclient import TestClient

from app import main, sessions


@pytest.fixture
def client():
    main.store = sessions.SessionStore()
    return TestClient(main.app)


def start(client):
    r = client.post("/api/sessions")
    assert r.status_code == 200
    sid = r.json()["session_id"]
    return {"X-Session-Id": sid}, r.json()["state"]


def reset(client, headers, **body):
    run_id = client.get("/api/state", headers=headers).json()["run_id"]
    return client.post("/api/reset", headers=headers, json={"expected_run_id": run_id, **body})


def test_requests_without_a_valid_session_are_rejected(client):
    assert client.get("/api/state").status_code == 401
    assert client.get("/api/state", headers={"X-Session-Id": "guess"}).status_code == 401
    assert client.post("/api/step", json={"expected_run_id": 1}).status_code == 401


def test_other_hosts_are_rejected(client):
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400


def test_full_replay_flow_over_http(client):
    h, state = start(client)
    state = reset(client, h, scenario_id="normal").json()
    for _ in range(3):
        state = client.post("/api/step", headers=h, json={"expected_run_id": state["run_id"]}).json()
    assert state["status"] == "awaiting_approval" and len(state["pending"]) == 1
    pending = state["pending"][0]
    assert pending["recipient"] == "coordinator@umbc-club.test" and pending["body"]
    url = f"/api/actions/{pending['action_id']}/approval"
    for _ in range(2):   # double click
        state = client.post(url, headers=h, json={"approve": True, "expected_run_id": state["run_id"]}).json()
    assert len(state["outbox"]) == 1 and state["status"] == "finished"
    assert state["counts"] == {"proposed": 3, "denied": 0, "awaiting": 0, "executed": 3}


def test_stale_tab_gets_a_conflict(client):
    h, state = start(client)
    old = state["run_id"]
    reset(client, h, scenario_id="restricted")
    r = client.post("/api/step", headers=h, json={"expected_run_id": old})
    assert r.status_code == 409


def test_step_after_finish_is_a_conflict(client):
    h, _ = start(client)
    state = reset(client, h, scenario_id="sensitive", variant_id="public").json()
    for _ in range(3):
        state = client.post("/api/step", headers=h, json={"expected_run_id": state["run_id"]}).json()
    assert state["status"] == "finished"
    assert client.post("/api/step", headers=h, json={"expected_run_id": state["run_id"]}).status_code == 409


def test_policy_validation(client):
    h, state = start(client)
    bad = {"expected_run_id": state["run_id"], "allowed_documents": ["passwords"],
           "allowed_recipients": [], "always_require_approval": False}
    assert client.patch("/api/policy", headers=h, json=bad).status_code == 422
    good = {**bad, "allowed_documents": ["club-notes", "member-roster"]}
    state = client.patch("/api/policy", headers=h, json=good).json()
    assert state["policy"]["version"] == 2
    assert state["timeline"][-1]["kind"] == "policy_change"


def test_unknown_scenario_is_404(client):
    h, _ = start(client)
    assert reset(client, h, scenario_id="nope").status_code == 404


def test_responses_leak_no_denied_content_or_secrets(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-secret-value")
    h, _ = start(client)
    state = reset(client, h, scenario_id="restricted").json()
    for _ in range(2):
        state = client.post("/api/step", headers=h, json={"expected_run_id": state["run_id"]}).json()
    text = json.dumps(state)
    assert "Alex Rivera" not in text                    # the denied roster body
    assert "sk-test-secret-value" not in text
    assert "conversation" not in state
    assert h["X-Session-Id"] not in text


def test_live_mode_requires_configuration(client, monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "AGENTGATE_LIVE", "OPENROUTER_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    h, _ = start(client)
    r = reset(client, h, scenario_id="normal", mode="live")
    assert r.status_code == 400 and "not configured" in r.json()["detail"]


def test_attack_text_is_bounded(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    h, _ = start(client)
    r = reset(client, h, scenario_id="normal", mode="live", attack_text="a" * 1001)
    assert r.status_code == 422


def test_session_capacity_is_explicit(client, monkeypatch):
    monkeypatch.setattr(sessions, "MAX_SESSIONS", 1)
    start(client)
    assert client.post("/api/sessions").status_code == 503


def test_reset_rejects_a_stale_run(client):
    headers, state = start(client)
    reset(client, headers, scenario_id="restricted")
    response = client.post("/api/reset", headers=headers,
                           json={"scenario_id": "normal", "expected_run_id": state["run_id"]})
    assert response.status_code == 409
    assert client.get("/api/state", headers=headers).json()["scenario_id"] == "restricted"


def test_mutations_check_run_under_lock(client, monkeypatch):
    original = main.check_run
    checked = []

    def check_locked(session, run_id):
        assert session.lock._is_owned()
        checked.append(run_id)
        original(session, run_id)

    monkeypatch.setattr(main, "check_run", check_locked)
    headers, _ = start(client)
    state = reset(client, headers, scenario_id="normal").json()
    client.patch("/api/policy", headers=headers,
                 json={"expected_run_id": state["run_id"], **state["policy"]})
    for _ in range(3):
        state = client.post("/api/step", headers=headers,
                            json={"expected_run_id": state["run_id"]}).json()
    response = client.post(f"/api/actions/{state['pending'][0]['action_id']}/approval", headers=headers,
                           json={"expected_run_id": state["run_id"], "approve": True})
    assert response.status_code == 200
    assert len(checked) == 3


def test_snapshot_does_not_share_mutable_state(client):
    headers, _ = start(client)
    session = main.store.get(headers["X-Session-Id"])
    saved = main.snapshot(session)
    session.timeline[0]["task"] = "changed"
    session.label_history[0]["label"] = "confidential"
    session.outbox.append({"receipt_id": "later"})
    assert saved["timeline"][0]["task"] != "changed"
    assert saved["label_history"][0]["label"] == "public"
    assert saved["outbox"] == []


def test_full_timeline_does_not_apply_policy(client, monkeypatch):
    headers, state = start(client)
    monkeypatch.setattr(sessions, "MAX_TIMELINE", 1)
    response = client.patch("/api/policy", headers=headers,
                            json={"expected_run_id": state["run_id"],
                                  "allowed_documents": [], "allowed_recipients": [],
                                  "always_require_approval": False})
    assert response.status_code == 409
    assert client.get("/api/state", headers=headers).json()["policy"] == state["policy"]
