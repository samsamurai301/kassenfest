"""Meta Model API client: Muse Spark JSON-schema chat and SAM 3.1, behind the record/replay cache.

The API is OpenAI-compatible, so this wraps the `openai` SDK with a custom base URL.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from openai import AsyncOpenAI
from pydantic import BaseModel

from kassenfest.config import Settings, get_settings
from kassenfest.llm.cache import CacheEntry, CacheMiss, ResponseCache, cache_key, normalize_request
from kassenfest.llm.costs import CallLog, CallRecord, chat_cost, sam_cost
from kassenfest.vision.geometry import Box
from kassenfest.vision.image import PageImage
from kassenfest.vision.sam import Segment, box_prompt, parse_sam_output

ReasoningEffort = Literal["minimal", "low", "medium", "high", "xhigh", "max"]


@dataclass
class CallMeta:
    key: str
    cache_hit: bool
    cost_usd: float  # spent by this call: 0 on a cache hit
    latency_ms: int


@dataclass
class ChatResult[T: BaseModel]:
    parsed: T
    raw_content: str
    meta: CallMeta


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str
    """JSON, as the model wrote it: may not parse."""


@dataclass
class ToolTurn:
    content: str
    calls: list[ToolCall]
    meta: CallMeta

    def message(self) -> dict[str, Any]:
        """The assistant message to send back on the next turn."""
        out: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.calls:
            out["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": c.arguments},
                }
                for c in self.calls
            ]
        return out


@dataclass
class SegmentResult:
    segments: list[Segment]
    raw_output: str
    meta: CallMeta


def responses_output_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    return "".join(
        part.get("text", "")
        for item in response.get("output") or []
        if item.get("type") == "message"
        for part in item.get("content") or []
        if part.get("type") == "output_text"
    )


class MetaModelClient:
    def __init__(self, settings: Settings | None = None, *, transport: Any | None = None):
        self.settings = settings or get_settings()
        for model in (self.settings.muse_model, self.settings.sam_model):
            # Contributor variants may train on inputs (docs/03 Q10).
            if model.endswith("-contributor"):
                raise ValueError(f"refusing contributor model {model!r}")
        self._transport = transport
        self._cache = ResponseCache(self.settings.llm_cache_dir)
        self._log = CallLog(self.settings.llm_call_log)
        self._sem = asyncio.Semaphore(self.settings.llm_max_concurrency)

    @property
    def transport(self) -> AsyncOpenAI:
        # Created lazily so replay mode works without an API key.
        if self._transport is None:
            if self.settings.model_api_key is None:
                raise RuntimeError("MODEL_API_KEY is not set: add it to .env or use replay mode")
            self._transport = AsyncOpenAI(
                api_key=self.settings.model_api_key.get_secret_value(),
                base_url=self.settings.model_base_url,
                timeout=self.settings.llm_timeout_s,
                max_retries=self.settings.llm_max_retries,
            )
        return self._transport

    async def chat_json[T: BaseModel](
        self,
        *,
        prompt_id: str,
        schema: type[T],
        system: str,
        user_text: str,
        images: Sequence[PageImage] = (),
        reasoning_effort: ReasoningEffort = "medium",
    ) -> ChatResult[T]:
        content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
        content += [{"type": "image_url", "image_url": {"url": img.data_url()}} for img in images]
        model = self.settings.muse_model
        request = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
            },
            "reasoning_effort": reasoning_effort,
        }
        response, meta = await self._call(
            prompt_id,
            request,
            lambda: self.transport.chat.completions.create(**request),
            lambda r: chat_cost(model, r.get("usage")),
        )
        raw = response["choices"][0]["message"]["content"]
        return ChatResult(parsed=schema.model_validate_json(raw), raw_content=raw, meta=meta)

    async def chat_tools(
        self,
        *,
        prompt_id: str,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        reasoning_effort: ReasoningEffort = "medium",
    ) -> ToolTurn:
        """One turn of a tool loop: the model's next message, with any tool calls in it.

        `tool_choice` only takes "auto" on this API, so the caller decides what to do when
        the model answers in prose instead."""
        model = self.settings.muse_model
        request = {
            "model": model,
            "messages": list(messages),
            "tools": list(tools),
            "tool_choice": "auto",
            "reasoning_effort": reasoning_effort,
        }
        response, meta = await self._call(
            prompt_id,
            request,
            lambda: self.transport.chat.completions.create(**request),
            lambda r: chat_cost(model, r.get("usage")),
        )
        message = response["choices"][0]["message"]
        calls = [
            ToolCall(c["id"], c["function"]["name"], c["function"].get("arguments") or "{}")
            for c in message.get("tool_calls") or []
        ]
        return ToolTurn(message.get("content") or "", calls, meta)

    async def segment(
        self,
        image: PageImage,
        *,
        concept: str | None = None,
        boxes: Sequence[Box] = (),
        prompt_id: str = "sam",
    ) -> SegmentResult:
        """One concept noun phrase, or 1–16 pixel boxes to refine. Never both."""
        if (concept is None) == (not boxes):
            raise ValueError("pass exactly one of concept or boxes")
        text = concept if concept is not None else box_prompt(image.width, image.height, boxes)
        model = self.settings.sam_model
        request = {
            "model": model,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": text},
                        {"type": "input_image", "image_url": image.data_url()},
                    ],
                }
            ],
            "metadata": {"include_confidence": "true"},
        }
        response, meta = await self._call(
            prompt_id,
            request,
            lambda: self.transport.responses.create(**request),
            lambda _: sam_cost(model),
        )
        raw = responses_output_text(response)
        return SegmentResult(segments=parse_sam_output(raw), raw_output=raw, meta=meta)

    async def _call(
        self,
        prompt_id: str,
        request: dict[str, Any],
        invoke: Callable[[], Awaitable[Any]],
        cost_of: Callable[[dict[str, Any]], float],
    ) -> tuple[dict[str, Any], CallMeta]:
        key = cache_key(request)
        mode = self.settings.llm_mode
        now = datetime.now(UTC).isoformat(timespec="seconds")

        if mode != "live" and (entry := self._cache.get(key)) is not None:
            if self.settings.llm_replay_pace > 0:
                async with self._sem:  # paced like the live call, concurrency limit included
                    await asyncio.sleep(entry.latency_ms / 1000 * self.settings.llm_replay_pace)
            self._log.append(CallRecord(now, entry.model, prompt_id, key, True, 0, entry.cost_usd))
            return entry.response, CallMeta(key, cache_hit=True, cost_usd=0.0, latency_ms=0)
        if mode == "replay":
            raise CacheMiss(f"{prompt_id}: no recorded response for {key[:12]} (LLM_MODE=replay)")

        async with self._sem:
            started = time.perf_counter()
            raw = await invoke()
            latency_ms = round((time.perf_counter() - started) * 1000)

        response = raw.model_dump(mode="json")
        cost = cost_of(response)
        self._cache.put(
            CacheEntry(
                key=key,
                model=request["model"],
                prompt_id=prompt_id,
                request=normalize_request(request),
                response=response,
                cost_usd=cost,
                latency_ms=latency_ms,
                created_at=now,
            )
        )
        usage = response.get("usage") or {}
        self._log.append(
            CallRecord(
                now,
                request["model"],
                prompt_id,
                key,
                False,
                latency_ms,
                cost,
                input_tokens=usage.get("prompt_tokens") or usage.get("input_tokens") or 0,
                output_tokens=usage.get("completion_tokens") or usage.get("output_tokens") or 0,
            )
        )
        return response, CallMeta(key, cache_hit=False, cost_usd=cost, latency_ms=latency_ms)
