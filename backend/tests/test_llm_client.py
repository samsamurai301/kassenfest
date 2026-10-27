import pytest
from meta_sam_parser._mask_codec import _encode_raster
from pydantic import BaseModel

from kassenfest.llm import CacheMiss, MetaModelClient
from tests.conftest import FakeTransport


class Card(BaseModel):
    kvnr: str | None
    signed: bool


CARD = {"kvnr": "A123456780", "signed": True}


async def _extract(client: MetaModelClient, page):
    return await client.chat_json(
        prompt_id="test.v1", schema=Card, system="sys", user_text="extract", images=[page]
    )


async def test_record_mode_calls_once_then_serves_from_cache(make_settings, page):
    transport = FakeTransport(chat_content=CARD)
    client = MetaModelClient(make_settings(llm_mode="record"), transport=transport)

    first = await _extract(client, page)
    second = await _extract(client, page)

    assert first.parsed == Card(**CARD) == second.parsed
    assert len(transport.calls) == 1
    assert not first.meta.cache_hit and first.meta.cost_usd > 0
    assert second.meta.cache_hit and second.meta.cost_usd == 0
    log_lines = client.settings.llm_call_log.read_text().splitlines()
    assert len(log_lines) == 2


async def test_request_carries_schema_effort_and_image(make_settings, page):
    transport = FakeTransport(chat_content=CARD)
    client = MetaModelClient(make_settings(), transport=transport)
    await _extract(client, page)

    _, request = transport.calls[0]
    assert request["model"] == "muse-spark-1.3"
    assert request["response_format"]["json_schema"]["name"] == "Card"
    assert request["reasoning_effort"] == "medium"
    image_part = request["messages"][1]["content"][1]
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")


async def test_replay_serves_recordings_without_an_api_key(make_settings, page):
    recorder = MetaModelClient(make_settings(llm_mode="record"), transport=FakeTransport(CARD))
    await _extract(recorder, page)

    # No transport and no key: any attempt to reach the API would raise RuntimeError.
    replayer = MetaModelClient(make_settings(llm_mode="replay"))
    result = await _extract(replayer, page)
    assert result.parsed.kvnr == "A123456780"
    assert result.meta.cache_hit


async def test_replay_miss_raises_without_calling_the_api(make_settings, page):
    transport = FakeTransport(chat_content=CARD)
    client = MetaModelClient(make_settings(llm_mode="replay"), transport=transport)
    with pytest.raises(CacheMiss):
        await _extract(client, page)
    assert transport.calls == []


async def test_live_mode_always_calls(make_settings, page):
    transport = FakeTransport(chat_content=CARD)
    client = MetaModelClient(make_settings(llm_mode="live"), transport=transport)
    await _extract(client, page)
    await _extract(client, page)
    assert len(transport.calls) == 2


async def test_cache_file_stores_image_hash_not_image_bytes(make_settings, page):
    client = MetaModelClient(make_settings(), transport=FakeTransport(CARD))
    await _extract(client, page)
    (cached,) = client.settings.llm_cache_dir.rglob("*.json")
    text = cached.read_text()
    assert f"sha256:{page.sha256}" in text
    assert "base64," not in text


def test_contributor_models_are_refused(make_settings):
    with pytest.raises(ValueError, match="contributor"):
        MetaModelClient(make_settings(muse_model="muse-spark-1.3-contributor"))


async def test_missing_key_is_a_clear_error_in_record_mode(make_settings, page):
    client = MetaModelClient(make_settings(llm_mode="record"))
    with pytest.raises(RuntimeError, match="MODEL_API_KEY"):
        await _extract(client, page)


def _sam_record(object_id: int, box: tuple[int, int, int, int], size=(200, 100), c=0.9) -> str:
    x1, y1, x2, y2 = box  # inclusive corners, as the API sends them
    mw, mh = x2 - x1 + 1, y2 - y1 + 1
    payload = _encode_raster([1] * (mw * mh), mw, mh)
    return (
        f"{object_id}<|box;x1={x1};y1={y1};x2={x2};y2={y2};w={size[0]};h={size[1]};c={c}|>"
        f"<|mask;x=0;y=0;c={c};data={mh},{mw},{payload}|>"
    )


async def test_segment_concept_parses_boxes_masks_and_confidence(make_settings, page):
    text = "<0f>" + _sam_record(0, (10, 20, 49, 59)) + "," + _sam_record(1, (100, 5, 139, 34))
    transport = FakeTransport(sam_text=text)
    client = MetaModelClient(make_settings(), transport=transport)

    result = await client.segment(page, concept="signature")

    _, request = transport.calls[0]
    assert request["model"] == "sam-3.1"
    assert request["metadata"] == {"include_confidence": "true"}
    assert request["input"][0]["content"][0] == {"type": "input_text", "text": "signature"}
    assert [s.box for s in result.segments] == [(10, 20, 50, 60), (100, 5, 140, 35)]
    assert result.segments[0].confidence == pytest.approx(0.9)
    mask = result.segments[0].mask_array()
    assert mask is not None and mask.shape == (40, 40) and mask.all()


async def test_segment_empty_output_means_no_match(make_settings, page):
    client = MetaModelClient(make_settings(), transport=FakeTransport(sam_text=""))
    result = await client.segment(page, concept="stamp")
    assert result.segments == []


async def test_segment_box_prompt_uses_object_prompt_grammar(make_settings, page):
    transport = FakeTransport(sam_text="")
    client = MetaModelClient(make_settings(), transport=transport)
    await client.segment(page, boxes=[(10.4, 20, 50, 60)])
    text = transport.calls[0][1]["input"][0]["content"][0]["text"]
    assert text.startswith("<0f>1<|box;") and "w=200" in text and "h=100" in text


async def test_segment_needs_exactly_one_prompt_kind(make_settings, page):
    client = MetaModelClient(make_settings(), transport=FakeTransport())
    with pytest.raises(ValueError):
        await client.segment(page)
    with pytest.raises(ValueError):
        await client.segment(page, concept="stamp", boxes=[(0, 0, 10, 10)])
