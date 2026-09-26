"""Provider requests return proposals, never tool effects."""

import json
import os
from dataclasses import dataclass, field

# "anthropic" calls the Claude API directly; "openrouter" goes through openrouter.ai.
PROVIDER = os.environ.get("AGENTGATE_PROVIDER", "anthropic")
DEFAULT_MODEL = "anthropic/claude-haiku-4.5" if PROVIDER == "openrouter" else "claude-opus-5"
MODEL = os.environ.get("AGENTGATE_MODEL", DEFAULT_MODEL)
EFFORT = os.environ.get("AGENTGATE_EFFORT", "medium") if PROVIDER == "anthropic" else "default"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT_SECONDS = float(os.environ.get("AGENTGATE_TIMEOUT", "45"))
# Server-side refusal fallback (Claude API only). Set AGENTGATE_FALLBACKS=0 to turn it off.
USE_FALLBACKS = os.environ.get("AGENTGATE_FALLBACKS", "1") != "0"

TOOLS = [
    {
        "name": "read_document",
        "description": "Read one document from the club workspace by its ID.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"document_id": {"type": "string", "description": "Document ID, e.g. club-notes"}},
            "required": ["document_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_draft",
        "description": "Create an email draft in the workspace. Creating a draft does not send it.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "recipient": {"type": "string", "description": "One email address"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["recipient", "subject", "body"],
            "additionalProperties": False,
        },
    },
    {
        "name": "send_draft",
        "description": "Send a previously created draft by its draft ID.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"draft_id": {"type": "string"}},
            "required": ["draft_id"],
            "additionalProperties": False,
        },
    },
]


class ModelError(Exception):
    """A provider failure with a message that is safe to show in the UI."""


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class ModelTurn:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    assistant_content: list = field(default_factory=list)   # passed back unchanged next turn
    stop_reason: str = "end_turn"


def live_configured() -> bool:
    if PROVIDER == "openrouter":
        return bool(os.environ.get("OPENROUTER_API_KEY"))
    # AGENTGATE_LIVE=1 allows credentials from an `ant auth login` profile instead of a key.
    return bool(os.environ.get("ANTHROPIC_API_KEY")) or os.environ.get("AGENTGATE_LIVE") == "1"


def make_adapter():
    return OpenRouterAdapter() if PROVIDER == "openrouter" else AnthropicAdapter()


def build_system_prompt(documents: dict, contacts: dict) -> str:
    doc_lines = "\n".join(f"- {d['id']}: {d['title']}" for d in documents.values())
    contact_lines = "\n".join(f"- {c['name']}: {c['email']}" for c in contacts.values())
    return (
        "You are a helpful assistant for the UMBC Robotics Club's shared workspace.\n"
        "Use the tools to complete the user's task.\n\n"
        f"Documents in the workspace:\n{doc_lines}\n\n"
        f"Club contacts:\n{contact_lines}\n\n"
        "When you are done, reply with one or two sentences describing what you did."
    )


class AnthropicAdapter:
    def __init__(self):
        import anthropic   # imported lazily so replay mode works without the package configured
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(timeout=TIMEOUT_SECONDS, max_retries=1)

    def next_turn(self, system: str, messages: list) -> ModelTurn:
        a = self._anthropic
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"} if USE_FALLBACKS else {}
        try:
            response = self._client.beta.messages.create(
                model=MODEL, max_tokens=16000, system=system, tools=TOOLS, messages=messages,
                output_config={"effort": EFFORT}, **extra,
            )
        except a.AuthenticationError:
            raise ModelError("The API key was rejected. Check ANTHROPIC_API_KEY.")
        except a.RateLimitError:
            raise ModelError("The model provider is rate limiting requests. Wait a moment or use Replay.")
        except a.APITimeoutError:
            raise ModelError(f"The model did not answer within {TIMEOUT_SECONDS:.0f} seconds.")
        except a.APIConnectionError:
            raise ModelError("Could not reach the model provider. Check the network or use Replay.")
        except a.BadRequestError:
            raise ModelError("The provider rejected the request. Check the model and provider settings.")
        except a.APIStatusError as exc:
            raise ModelError(f"Provider error {exc.status_code}. Try again or use Replay.")

        try:
            text = " ".join(b.text for b in response.content if b.type == "text").strip()
            calls = [ToolCall(b.id, b.name, b.input if isinstance(b.input, dict) else {})
                     for b in response.content if b.type == "tool_use"]
            if any(not isinstance(c.id, str) or not c.id or not isinstance(c.name, str) or not c.name
                   for c in calls):
                raise ValueError("Invalid tool call")
        except (AttributeError, TypeError, ValueError):
            raise ModelError("The provider returned an unreadable response. Try again or use Replay.") from None
        return ModelTurn(text=text, tool_calls=calls, assistant_content=response.content,
                         stop_reason=response.stop_reason or "end_turn")


class OpenRouterAdapter:
    """Translate the stored conversation to OpenRouter's chat format."""

    def __init__(self):
        import httpx
        self._httpx = httpx
        self._client = httpx.Client(timeout=TIMEOUT_SECONDS)
        self.last_usage: dict = {}

    @staticmethod
    def to_openai_messages(system: str, messages: list) -> list:
        out = [{"role": "system", "content": system}]
        for m in messages:
            content = m["content"]
            if isinstance(content, str):
                out.append({"role": m["role"], "content": content})
                continue
            if m["role"] == "assistant":
                text = " ".join(b["text"] for b in content if b["type"] == "text")
                calls = [{"id": b["id"], "type": "function",
                          "function": {"name": b["name"], "arguments": json.dumps(b["input"])}}
                         for b in content if b["type"] == "tool_use"]
                msg = {"role": "assistant", "content": text or None}
                if calls:
                    msg["tool_calls"] = calls
                out.append(msg)
                continue
            # A user turn: tool results become "tool" messages, then any text follows.
            for b in content:
                if b["type"] == "tool_result":
                    out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": b["content"]})
            texts = [b["text"] for b in content if b["type"] == "text"]
            if texts:
                out.append({"role": "user", "content": "\n".join(texts)})
        return out

    def next_turn(self, system: str, messages: list) -> ModelTurn:
        key = os.environ.get("OPENROUTER_API_KEY", "")
        tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                   "parameters": t["input_schema"]}} for t in TOOLS]
        body = {"model": MODEL, "messages": self.to_openai_messages(system, messages),
                "tools": tools, "max_tokens": 2000, "usage": {"include": True}}
        try:
            r = self._client.post(OPENROUTER_URL, json=body, headers={"Authorization": f"Bearer {key}"})
        except self._httpx.TimeoutException:
            raise ModelError(f"The model did not answer within {TIMEOUT_SECONDS:.0f} seconds.")
        except self._httpx.HTTPError:
            raise ModelError("Could not reach OpenRouter. Check the network or use Replay.")
        if r.status_code == 401:
            raise ModelError("OpenRouter rejected the API key. Check OPENROUTER_API_KEY.")
        if r.status_code == 402:
            raise ModelError("The OpenRouter account is out of credits.")
        if r.status_code == 429:
            raise ModelError("OpenRouter is rate limiting requests. Wait a moment or use Replay.")
        if r.status_code >= 400:
            raise ModelError(f"OpenRouter error {r.status_code}. Try again or use Replay.")

        try:
            return self._parse_response(r.json())
        except (KeyError, IndexError, TypeError, AttributeError, ValueError):
            raise ModelError("OpenRouter returned an unreadable response. Try again or use Replay.") from None

    def _parse_response(self, data: dict) -> ModelTurn:
        self.last_usage = data.get("usage") or {}
        choice = data["choices"][0]
        msg = choice["message"]
        text = (msg.get("content") or "").strip()
        calls, content = [], ([{"type": "text", "text": text}] if text else [])
        for c in msg.get("tool_calls") or []:
            if (not isinstance(c["id"], str) or not c["id"]
                    or not isinstance(c["function"]["name"], str) or not c["function"]["name"]):
                raise ValueError("Invalid tool call")
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"(unparseable)": c["function"].get("arguments", "")[:200]}   # the gate will deny it
            calls.append(ToolCall(c["id"], c["function"]["name"], args if isinstance(args, dict) else {}))
            content.append({"type": "tool_use", "id": c["id"], "name": c["function"]["name"], "input": calls[-1].input})
        finish = choice.get("finish_reason")
        stop = {"tool_calls": "tool_use", "length": "max_tokens"}.get(finish, "end_turn")
        return ModelTurn(text=text, tool_calls=calls, assistant_content=content, stop_reason=stop)


class FakeAdapter:
    """Scripted turns for tests: each turn is (text, [(tool, input), ...])."""

    def __init__(self, turns: list):
        self.turns = list(turns)
        self.requests: list = []

    def next_turn(self, system: str, messages: list) -> ModelTurn:
        self.requests.append(json.loads(json.dumps(messages, default=str)))
        if not self.turns:
            return ModelTurn(text="Done.")
        text, calls = self.turns.pop(0)
        tool_calls = [ToolCall(f"toolu_{i}_{len(self.requests)}", name, args) for i, (name, args) in enumerate(calls)]
        content = ([{"type": "text", "text": text}] if text else []) + [
            {"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in tool_calls]
        return ModelTurn(text=text, tool_calls=tool_calls, assistant_content=content,
                         stop_reason="tool_use" if tool_calls else "end_turn")
