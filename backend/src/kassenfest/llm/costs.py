"""Model prices and the per-call log (docs/04-RESEARCH-NOTES.md §2, re-check before quoting)."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# USD per 1M tokens: (input, cached input, output). Reasoning tokens bill as output.
CHAT_PRICES: dict[str, tuple[float, float, float]] = {
    "muse-spark-1.3": (1.25, 0.15, 4.25),
}
SAM_PRICE_PER_IMAGE: dict[str, float] = {
    "sam-3.1": 2.50 / 1000,
}


def chat_cost(model: str, usage: dict[str, Any] | None) -> float:
    if not usage or model not in CHAT_PRICES:
        return 0.0
    price_in, price_cached, price_out = CHAT_PRICES[model]
    prompt = usage.get("prompt_tokens") or 0
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    output = usage.get("completion_tokens") or 0
    return ((prompt - cached) * price_in + cached * price_cached + output * price_out) / 1e6


def sam_cost(model: str, images: int = 1) -> float:
    return SAM_PRICE_PER_IMAGE.get(model, 0.0) * images


@dataclass
class CallRecord:
    ts: str
    model: str
    prompt_id: str
    key: str
    cache_hit: bool
    latency_ms: int
    cost_usd: float
    input_tokens: int = 0
    output_tokens: int = 0


class CallLog:
    """Append-only JSONL; a cache hit is logged with the original cost but spends nothing."""

    def __init__(self, path: Path):
        self.path = path

    def append(self, record: CallRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record)) + "\n")
