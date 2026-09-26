"""No real API requests: exercise Gemini through a fake HTTP transport."""

import json

import httpx
import pytest

from app import model_adapter, runner
from app.dispatcher import resolve_approval
from app.gemini_adapter import GeminiAdapter
from app.model_adapter import ModelError
from app.sessions import Session


@pytest.fixture(autouse=True)
def fake_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.fixture
def adapter():
    instance = GeminiAdapter()
    instance._client.close()
    yield instance
    instance._client.close()


def respond(adapter, payload, status=200):
    adapter._client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(status, json=payload)))


def reply(parts, finish="STOP"):
    return {"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": finish}],
            "usageMetadata": {"totalTokenCount": 12}}


def call(name="read_document", args=None, **extra):
    return {"functionCall": {"name": name, "args": args if args is not None else
                             {"document_id": "club-notes"}, **extra}}


def test_request_and_signed_history_round_trip(adapter):
    parts = [{"text": "private reasoning", "thought": True, "thoughtSignature": "sig-text"},
             {**call(id="provider-1"), "thoughtSignature": "sig-call"}, call()]
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        assert request.headers["x-goog-api-key"] == "test-google-key"
        assert not request.url.query
        assert request.url.host == "generativelanguage.googleapis.com"
        return httpx.Response(200, json=reply(parts if len(requests) == 1 else [{"text": "Done."}]))

    adapter._client = httpx.Client(transport=httpx.MockTransport(handler))
    messages = [{"role": "user", "content": "Read the notes"}]
    turn = adapter.next_turn("SYS", messages)
    assert turn.text == "" and len(turn.tool_calls) == 2
    assert turn.tool_calls[0].id != turn.tool_calls[1].id
    assert turn.stop_reason == "tool_use"
    tools = requests[0]["tools"][0]["functionDeclarations"]
    assert [t["name"] for t in tools] == ["read_document", "create_draft", "send_draft"]
    assert tools[0]["parametersJsonSchema"]["additionalProperties"] is False
    messages += [{"role": "assistant", "content": turn.assistant_content},
                 {"role": "user", "content": [
                     {"type": "tool_result", "tool_use_id": c.id, "content": '{"status":"denied"}'}
                     for c in turn.tool_calls] + [{"type": "text", "text": "Approval was denied."}]}]
    final = adapter.next_turn("SYS", messages)
    assert final.text == "Done." and final.stop_reason == "end_turn"
    contents = requests[1]["contents"]
    assert contents[1] == {"role": "model", "parts": parts}
    results = contents[2]["parts"]
    assert results[0]["functionResponse"] == {
        "name": "read_document", "id": "provider-1", "response": {"status": "denied"}}
    assert "id" not in results[1]["functionResponse"]
    assert results[2] == {"text": "Approval was denied."}
    assert adapter.last_usage == {"totalTokenCount": 12}


@pytest.mark.parametrize("payload", [
    {}, {"candidates": []}, {"candidates": None}, reply([]), reply([None]),
    reply([{"text": 3}]), reply([{"thought": True, "text": "hidden"}]),
    reply([call(args=[])]), reply([call(name=[]) ]), reply([call(id="")]),
    reply([call(id="same"), call(id="same")]), reply([{"functionCall": None}]),
])
def test_malformed_response_stops_without_tools(adapter, payload):
    respond(adapter, payload)
    session = Session(id="gemini-test")
    runner.reset_run(session, "normal", "default", "live")
    runner.step(session, adapter)
    assert session.status == "error"
    assert "unreadable response" in session.error
    assert session.proposals == 0 and not session.drafts and not session.outbox


@pytest.mark.parametrize("finish", ["SAFETY", "RECITATION", "MALFORMED_FUNCTION_CALL", "OTHER", None])
def test_incomplete_response_never_executes_calls(adapter, finish):
    respond(adapter, reply([call()], finish))
    with pytest.raises(ModelError, match="No tools were run"):
        adapter.next_turn("SYS", [])


def test_output_limit_never_executes_calls(adapter):
    respond(adapter, reply([call()], "MAX_TOKENS"))
    session = Session(id="gemini-test")
    runner.reset_run(session, "normal", "default", "live")
    runner.step(session, adapter)
    assert session.status == "finished" and session.proposals == 0


def test_blocked_prompt(adapter):
    respond(adapter, {"promptFeedback": {"blockReason": "SAFETY"}})
    with pytest.raises(ModelError, match="blocked this prompt"):
        adapter.next_turn("SYS", [])


@pytest.mark.parametrize("status,words", [(400, "rejected the request"), (401, "rejected access"),
    (403, "rejected access"), (404, "AGENTGATE_MODEL"), (429, "quota"), (500, "error 500")])
def test_http_errors_do_not_echo_provider_details(adapter, status, words):
    respond(adapter, {"error": "test-google-key"}, status)
    with pytest.raises(ModelError, match=words) as error:
        adapter.next_turn("SYS", [])
    assert "test-google-key" not in str(error.value)


@pytest.mark.parametrize("exception,words", [(httpx.ReadTimeout, "did not answer"),
                                           (httpx.ConnectError, "Could not reach")])
def test_network_errors(adapter, exception, words):
    def handler(request):
        raise exception("secret provider details", request=request)
    adapter._client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ModelError, match=words):
        adapter.next_turn("SYS", [])


def test_non_json_response(adapter):
    adapter._client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text="not json")))
    with pytest.raises(ModelError, match="unreadable response"):
        adapter.next_turn("SYS", [])


def test_gemini_key_alias_and_missing_key(adapter, monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY")
    monkeypatch.setenv("GEMINI_API_KEY", "alias-key")
    def handler(request):
        assert request.headers["x-goog-api-key"] == "alias-key"
        return httpx.Response(200, json=reply([{"text": "Done."}]))
    adapter._client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter.next_turn("SYS", [])
    monkeypatch.delenv("GEMINI_API_KEY")
    with pytest.raises(ModelError, match="Set GOOGLE_API_KEY"):
        adapter.next_turn("SYS", [])


def test_provider_selection(monkeypatch):
    monkeypatch.setattr(model_adapter, "PROVIDER", "gemini")
    assert model_adapter.live_configured()
    adapter = model_adapter.make_adapter()
    assert isinstance(adapter, GeminiAdapter)
    adapter._client.close()
    monkeypatch.delenv("GOOGLE_API_KEY")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-use")
    monkeypatch.setenv("AGENTGATE_LIVE", "1")
    assert not model_adapter.live_configured()
    monkeypatch.setattr(model_adapter, "PROVIDER", "typo")
    assert not model_adapter.live_configured()
    with pytest.raises(ModelError, match="Unknown AGENTGATE_PROVIDER"):
        model_adapter.make_adapter()


@pytest.mark.parametrize("name,args,status", [
    ("read_document", {"document_id": "club-notes"}, "executed"),
    ("read_document", {"document_id": "not-a-document"}, "denied"),
    ("read_document", {"unexpected": "argument"}, "denied"),
    ("run_shell", {"command": "anything"}, "denied"),
    ("create_draft", {"recipient": "outsider@outside.test", "subject": "Hi", "body": "Hello"}, "denied"),
])
def test_proposals_still_pass_through_the_gate(adapter, name, args, status):
    respond(adapter, reply([call(name, args)]))
    session = Session(id="gemini-test")
    runner.reset_run(session, "normal", "default", "live")
    runner.step(session, adapter)
    actions = [e for e in session.timeline if e["kind"] == "action"]
    assert actions[0]["status"] == status
    assert not session.outbox


def test_full_run_waits_for_human_approval(adapter):
    session = Session(id="gemini-test")
    runner.reset_run(session, "normal", "default", "live")
    requests = []

    def handler(request):
        contents = json.loads(request.content)["contents"]
        requests.append(contents)
        if len(requests) == 1:
            parts = [call()]
        elif len(requests) == 2:
            assert contents[-1]["parts"][0]["functionResponse"]["name"] == "read_document"
            parts = [call("create_draft", {"recipient": "coordinator@umbc-club.test",
                                          "subject": "Notes", "body": "Meeting summary."})]
        elif len(requests) == 3:
            parts = [call("send_draft", {"draft_id": next(iter(session.drafts))})]
        else:
            assert contents[-1]["parts"][-1]["text"].startswith("[AgentGate]")
            parts = [{"text": "The approved draft was sent."}]
        return httpx.Response(200, json=reply(parts))

    adapter._client = httpx.Client(transport=httpx.MockTransport(handler))
    for _ in range(3):
        runner.step(session, adapter)
    assert session.status == "awaiting_approval" and not session.outbox
    resolve_approval(session, next(iter(session.pending)), True)
    runner.step(session, adapter)
    assert session.status == "finished" and len(session.outbox) == 1
