import base64
import hashlib

from kassenfest.llm.cache import CacheEntry, ResponseCache, cache_key, normalize_request
from kassenfest.llm.costs import chat_cost


def _data_url(data: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(data).decode()


def test_normalize_replaces_inline_images_with_their_hash():
    request = {"content": [{"image_url": {"url": _data_url(b"page-bytes")}}, "plain text"]}
    normalized = normalize_request(request)
    assert normalized["content"][0]["image_url"]["url"] == (
        "sha256:" + hashlib.sha256(b"page-bytes").hexdigest()
    )
    assert normalized["content"][1] == "plain text"


def test_key_ignores_dict_order_but_not_image_content():
    a = {"model": "m", "image": _data_url(b"one"), "effort": "low"}
    b = {"effort": "low", "image": _data_url(b"one"), "model": "m"}
    c = {"model": "m", "image": _data_url(b"two"), "effort": "low"}
    assert cache_key(a) == cache_key(b)
    assert cache_key(a) != cache_key(c)


def test_cache_roundtrip(tmp_path):
    cache = ResponseCache(tmp_path)
    entry = CacheEntry("ab" * 32, "m", "p.v1", {"x": 1}, {"y": "ä"}, 0.01, 120, "2026-10-27")
    assert cache.get(entry.key) is None
    cache.put(entry)
    assert cache.get(entry.key) == entry
    assert not list(tmp_path.rglob("*.tmp"))


def test_chat_cost_bills_cached_input_at_the_cached_rate():
    usage = {
        "prompt_tokens": 1_000_000,
        "prompt_tokens_details": {"cached_tokens": 400_000},
        "completion_tokens": 100_000,
    }
    assert (
        chat_cost("muse-spark-1.3", usage)
        == (600_000 * 1.25 + 400_000 * 0.15 + 100_000 * 4.25) / 1e6
    )
    assert chat_cost("unknown-model", usage) == 0.0
