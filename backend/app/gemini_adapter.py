"""Gemini proposes calls; the runner still sends them through the gate."""

import json
import os
from urllib.parse import quote
from uuid import uuid4

import httpx

from .model_adapter import MODEL, TIMEOUT_SECONDS, TOOLS, ModelError, ModelTurn, ToolCall


class GeminiAdapter:
    def __init__(self):
        self._client = httpx.Client(timeout=TIMEOUT_SECONDS)
        self.last_usage: dict = {}

    @staticmethod
    def to_contents(messages: list) -> list:
        contents, calls = [], {}
        for message in messages:
            content = message["content"]
            if isinstance(content, str):
                contents.append({"role": "user", "parts": [{"text": content}]})
                continue
            if message["role"] == "assistant":
                stored = content[0]
                parts = stored["parts"]
                functions = [p["functionCall"] for p in parts if "functionCall" in p]
                calls.update(zip(stored["call_ids"], functions))
                # Keep signatures attached to their original parts, including text parts.
                contents.append({"role": "model", "parts": parts})
                continue
            parts = []
            for block in content:
                if block["type"] == "text":
                    parts.append({"text": block["text"]})
                elif block["type"] == "tool_result":
                    call = calls[block["tool_use_id"]]
                    result = {"name": call["name"], "response": json.loads(block["content"])}
                    if call.get("id"):
                        result["id"] = call["id"]
                    parts.append({"functionResponse": result})
            contents.append({"role": "user", "parts": parts})
        return contents

    def next_turn(self, system: str, messages: list) -> ModelTurn:
        key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise ModelError("Set GOOGLE_API_KEY or GEMINI_API_KEY before using Gemini Live mode.")
        declarations = [{"name": t["name"], "description": t["description"],
                         "parametersJsonSchema": t["input_schema"]} for t in TOOLS]
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": self.to_contents(messages),
                "tools": [{"functionDeclarations": declarations}],
                "generationConfig": {"maxOutputTokens": 8192}}
        model = quote(MODEL.removeprefix("models/"), safe="")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            response = self._client.post(url, json=body, headers={"x-goog-api-key": key})
        except httpx.TimeoutException:
            raise ModelError(f"Gemini did not answer within {TIMEOUT_SECONDS:.0f} seconds.") from None
        except httpx.HTTPError:
            raise ModelError("Could not reach Gemini. Check the network or use Replay.") from None
        if response.status_code in (401, 403):
            raise ModelError("Gemini rejected access. Check your Google API key and project permissions.")
        if response.status_code == 429:
            raise ModelError("Gemini quota or rate limit reached. Wait or use Replay.")
        if response.status_code in (400, 404):
            raise ModelError("Gemini rejected the request. Check your API key and AGENTGATE_MODEL access.")
        if response.status_code >= 400:
            raise ModelError(f"Gemini error {response.status_code}. Try again or use Replay.")
        try:
            return self._parse_response(response.json())
        except (KeyError, IndexError, TypeError, AttributeError, ValueError):
            raise ModelError("Gemini returned an unreadable response. Try again or use Replay.") from None

    def _parse_response(self, data: dict) -> ModelTurn:
        self.last_usage = data.get("usageMetadata") or {}
        if data.get("promptFeedback", {}).get("blockReason"):
            raise ModelError("Gemini blocked this prompt. Try another prompt or use Replay.")
        candidate = data["candidates"][0]
        finish = candidate.get("finishReason")
        if finish == "MAX_TOKENS":
            return ModelTurn(text="Gemini reached its output limit; no proposed tools were run.",
                             stop_reason="max_tokens")
        if finish != "STOP":
            raise ModelError("Gemini stopped without a complete answer. No tools were run; try Replay.")
        parts = candidate["content"]["parts"]
        if not isinstance(parts, list) or not parts:
            raise ValueError("Missing parts")
        texts, calls, provider_ids = [], [], set()
        for part in parts:
            if not isinstance(part, dict):
                raise ValueError("Invalid part")
            if "text" in part:
                if not isinstance(part["text"], str):
                    raise ValueError("Invalid text")
                if not part.get("thought"):
                    texts.append(part["text"])
            if "functionCall" in part:
                call = part["functionCall"]
                name, args = call["name"], call.get("args", {})
                if not isinstance(name, str) or not name or not isinstance(args, dict):
                    raise ValueError("Invalid function call")
                if "id" in call:
                    call_id = call["id"]
                    if not isinstance(call_id, str) or not call_id or call_id in provider_ids:
                        raise ValueError("Invalid call ID")
                    provider_ids.add(call_id)
                calls.append(ToolCall(uuid4().hex, name, args))
        text = " ".join(texts).strip()
        if not text and not calls:
            raise ValueError("Empty answer")
        stored = [{"type": "gemini_content", "parts": parts, "call_ids": [c.id for c in calls]}]
        return ModelTurn(text=text, tool_calls=calls, assistant_content=stored,
                         stop_reason="tool_use" if calls else "end_turn")
