"""OpenRouter adapter tests with a fake HTTP transport: no network, no cost."""

import json

import httpx
import pytest

from app import runner
from app.model_adapter import ModelError, OpenRouterAdapter
from app.sessions import Session


def adapter_with(handler):
    a = OpenRouterAdapter()
    a._client = httpx.Client(transport=httpx.MockTransport(handler))
    return a


def reply(tool_calls=None, content=None, finish="tool_calls"):
    return {"choices": [{"message": {"content": content, "tool_calls": tool_calls}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0001}}


def test_translates_conversation_to_openai_format():
    conversation = [
        {"role": "user", "content": "Summarize the notes."},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "c1", "name": "read_document",
                                           "input": {"document_id": "club-notes"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": '{"status": "ok"}'},
                                     {"type": "text", "text": "[AgentGate] note"}]},
    ]
    out = OpenRouterAdapter.to_openai_messages("SYS", conversation)
    assert [m["role"] for m in out] == ["system", "user", "assistant", "tool", "user"]
    assert out[2]["tool_calls"][0]["function"] == {"name": "read_document", "arguments": '{"document_id": "club-notes"}'}
    assert out[3] == {"role": "tool", "tool_call_id": "c1", "content": '{"status": "ok"}'}


def test_parses_tool_calls_and_sends_tools():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=reply([{"id": "c9", "type": "function", "function": {
            "name": "create_draft", "arguments": '{"recipient": "a@b.test", "subject": "s", "body": "b"}'}}]))

    turn = adapter_with(handler).next_turn("SYS", [{"role": "user", "content": "hi"}])
    assert [t["function"]["name"] for t in seen["body"]["tools"]] == ["read_document", "create_draft", "send_draft"]
    assert turn.stop_reason == "tool_use"
    assert turn.tool_calls[0].name == "create_draft" and turn.tool_calls[0].input["recipient"] == "a@b.test"


def test_bad_json_arguments_reach_the_gate_as_invalid():
    def handler(request):
        return httpx.Response(200, json=reply([{"id": "c1", "type": "function",
                                                 "function": {"name": "read_document", "arguments": "{not json"}}]))
    s = Session(id="t")
    runner.reset_run(s, "normal", "default", "live")
    runner.step(s, adapter_with(handler))
    action = [e for e in s.timeline if e["kind"] == "action"][0]
    assert (action["status"], action["rule_id"]) == ("denied", "invalid_arguments")


@pytest.mark.parametrize("status,words", [(401, "API key"), (402, "credits"), (429, "rate limiting"), (500, "error 500")])
def test_http_errors_become_readable_messages(status, words):
    with pytest.raises(ModelError, match=words):
        adapter_with(lambda r: httpx.Response(status)).next_turn("SYS", [{"role": "user", "content": "hi"}])


def test_text_only_reply_ends_the_turn():
    turn = adapter_with(lambda r: httpx.Response(200, json=reply(None, "Done.", "stop"))).next_turn("S", [])
    assert (turn.text, turn.tool_calls, turn.stop_reason) == ("Done.", [], "end_turn")


@pytest.mark.parametrize("payload", [
    {}, {"choices": []}, {"choices": None}, {"choices": [{"message": None}]},
    reply(content=[{"text": "unexpected format"}]),
    reply(tool_calls=[{"id": "call", "function": {"name": ["read_document"]}}]),
    reply(tool_calls=[{"function": {"name": "read_document", "arguments": "{}"}}]),
])
def test_malformed_response_stops_without_executing(payload):
    session = Session(id="test")
    runner.reset_run(session, "normal", "default", "live")
    adapter = adapter_with(lambda request: httpx.Response(200, json=payload))
    runner.step(session, adapter)
    assert session.status == "error"
    assert "unreadable response" in session.error
    assert not session.drafts and not session.outbox


def test_non_json_response_becomes_a_model_error():
    adapter = adapter_with(lambda request: httpx.Response(200, text="not json"))
    with pytest.raises(ModelError, match="unreadable response"):
        adapter.next_turn("system", [])


def test_truncated_tool_response_is_not_executed():
    payload = reply(tool_calls=[{"id": "c1", "function": {
        "name": "read_document", "arguments": '{"document_id":"club-notes"}'}}], finish="length")
    session = Session(id="test")
    runner.reset_run(session, "normal", "default", "live")
    runner.step(session, adapter_with(lambda request: httpx.Response(200, json=payload)))
    assert session.proposals == 0
    assert session.status == "finished"
