import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from kassenfest.config import Settings
from kassenfest.vision.image import PageImage


class FakeResponse:
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        return self.payload


class FakeTransport:
    """Mimics the parts of AsyncOpenAI the client uses and records every call.

    `chat_content` and `sam_text` may be callables taking the request kwargs, to
    answer differently per schema or prompt.
    """

    def __init__(
        self,
        chat_content: dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        sam_text: str | Callable[[dict[str, Any]], str] = "",
    ):
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.chat_content = chat_content or {}
        self.sam_text = sam_text

        async def chat_create(**kwargs: Any) -> FakeResponse:
            self.calls.append(("chat", kwargs))
            content = (
                self.chat_content(kwargs) if callable(self.chat_content) else self.chat_content
            )
            return FakeResponse(
                {
                    "choices": [{"message": {"content": json.dumps(content)}}],
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 200},
                }
            )

        async def responses_create(**kwargs: Any) -> FakeResponse:
            self.calls.append(("responses", kwargs))
            text = self.sam_text(kwargs) if callable(self.sam_text) else self.sam_text
            return FakeResponse(
                {
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": text}],
                        }
                    ]
                }
            )

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=chat_create))
        self.responses = SimpleNamespace(create=responses_create)


@pytest.fixture
def make_settings(tmp_path):
    def _make(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "_env_file": None,
            "model_api_key": None,
            "llm_cache_dir": tmp_path / "cache",
            "llm_call_log": tmp_path / "calls.jsonl",
            "llm_mode": "record",
        }
        values.update(overrides)
        return Settings(**values)

    return _make


@pytest.fixture
def page() -> PageImage:
    return PageImage.from_pil(Image.new("RGB", (200, 100), "white"))
