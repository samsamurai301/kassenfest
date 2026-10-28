"""The inbox: uploads are stored at once, read in the background, followed over SSE."""

import asyncio
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from kassenfest.api import inbox as inbox_mod
from kassenfest.api.app import app
from kassenfest.api.inbox import Deps, Inbox, Run, run_deps, unpack
from kassenfest.db import Batch, Document, create_db, session_scope
from kassenfest.llm.client import MetaModelClient
from kassenfest.storage import BlobStore
from tests.conftest import FakeTransport


def png(color: str = "white") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (200, 280), color).save(buf, format="PNG")
    return buf.getvalue()


def zipped(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def api(make_settings, tmp_path, monkeypatch):
    """The app with a fake model that calls every page 'other', on an empty database."""
    classification = {
        "pages": [{"page": 0, "doc_type": "other", "confidence": 0.9, "starts_new_document": True}],
        "synthetic_watermark": True,
    }
    client = MetaModelClient(make_settings(), transport=FakeTransport(chat_content=classification))
    deps = Deps(client, create_db(tmp_path / "k.db"), BlobStore(tmp_path / "blobs"), None)
    monkeypatch.setattr(inbox_mod, "inbox", Inbox())  # no runs left over from other tests
    app.dependency_overrides[run_deps] = lambda: deps
    with TestClient(app) as c:  # keeps one event loop, so background reads finish
        yield c, deps
    del app.dependency_overrides[run_deps]


def events(client: TestClient, batch_id: str) -> list[dict]:
    with client.stream("GET", f"/api/batches/{batch_id}/events") as res:
        assert res.headers["content-type"].startswith("text/event-stream")
        return [json.loads(line[6:]) for line in res.iter_lines() if line.startswith("data: ")]


def test_an_upload_is_stored_at_once_read_in_the_background_and_streamed(api):
    client, _ = api
    files = [
        ("files", ("a.png", png(), "image/png")),
        ("files", ("broken.png", b"not an image", "image/png")),
        ("files", ("notes.txt", b"skip me", "text/plain")),
    ]
    res = client.post("/api/batches", files=files, data={"label": "Oktober"})

    assert res.status_code == 202, res.text
    batch = res.json()
    assert batch["label"] == "Oktober"
    assert [d["filename"] for d in batch["documents"]] == ["a.png", "broken.png"]
    assert batch["documents"][1]["status"] == "error"

    stream = events(client, batch["id"])  # finished by now: replayed in full, then closed
    assert [e["seq"] for e in stream] == list(range(1, len(stream) + 1))
    steps = [(e["document"]["filename"], e["document"]["step"]) for e in stream if e["document"]]
    assert steps == [
        ("a.png", "stored"),
        ("broken.png", "error"),
        ("a.png", "classified"),
        ("a.png", "done"),
    ]
    assert [(e["kind"], e["phase"]) for e in stream if e["kind"] == "phase"] == [
        ("phase", "evidence"),
        ("phase", "done"),
    ]
    done = client.get(f"/api/batches/{batch['id']}").json()
    assert (done["phase"], done["files"], done["done"], done["failed"]) == ("done", 2, 1, 1)
    assert done["documents"][0]["detail"] == "not a billing document"
    assert client.get("/api/batches").json()["batches"][0]["id"] == batch["id"]


def test_files_come_out_of_zips_and_junk_is_skipped(api):
    archive = zipped(
        {
            "Oktober/syn-1.png": png(),
            "Oktober/scan.PDF": b"%PDF-",
            "__MACOSX/Oktober/._syn-1.png": b"resource fork",
            "Oktober/.DS_Store": b"",
            "Oktober/readme.txt": b"hello",
        }
    )
    files = unpack([("Oktober.zip", archive), ("x.heic", b"h"), (".hidden.png", b"")])
    assert [name for name, _ in files] == ["scan.PDF", "syn-1.png", "x.heic"]

    client, _ = api
    nothing = client.post("/api/batches", files=[("files", ("a.txt", b"x", "text/plain"))])
    assert nothing.status_code == 422
    bad_zip = client.post("/api/batches", files=[("files", ("a.zip", b"x", "application/zip"))])
    assert bad_zip.status_code == 422


def test_a_batch_left_unfinished_by_a_restart_says_so(api):
    client, deps = api
    with session_scope(deps.engine) as s:
        s.add(Batch(id="bat-old", label="before the restart"))
        s.add(
            Document(
                batch_id="bat-old",
                filename="a.png",
                source_sha256="x",
                source_key="k",
                status="processing",
            )
        )
    batch = client.get("/api/batches/bat-old").json()
    assert batch["phase"] == "interrupted"
    assert batch["documents"][0]["step"] == "stored"
    assert events(client, "bat-old") == []  # not read by this process: nothing to follow
    assert client.get("/api/batches/bat-nope").status_code == 404


async def test_a_late_listener_gets_what_it_missed_then_live_events_until_done():
    box = Inbox()
    box.runs["b"] = Run()
    box._phase("b", "reading", "first")
    got = []

    async def listen():
        async for event in box.follow("b"):
            got.append(event)

    task = asyncio.create_task(listen())
    await asyncio.sleep(0)  # listening now
    box._phase("b", "evidence", "second")
    box._phase("b", "done", "third")
    await asyncio.wait_for(task, 1)

    assert [(e.seq, e.detail) for e in got] == [(1, "first"), (2, "second"), (3, "third")]
    assert not box.runs["b"].listeners
