"""What running the pipeline needs, as a FastAPI dependency so tests can swap in a fake model."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine

from kassenfest.api.live import db_engine
from kassenfest.config import get_settings
from kassenfest.llm.client import MetaModelClient
from kassenfest.schemas.records import MasterData
from kassenfest.storage import BlobStore


@dataclass
class Deps:
    """The model client, the database, the page images and the records."""

    client: MetaModelClient
    engine: Engine
    blobs: BlobStore
    records: MasterData | None


@lru_cache(maxsize=1)
def _client() -> MetaModelClient:
    return MetaModelClient(get_settings())  # one client: one concurrency limit for all runs


@lru_cache(maxsize=2)
def _records(path: Path, mtime_ns: int) -> MasterData:
    return MasterData.model_validate_json(path.read_text())


def run_deps() -> Deps:
    settings = get_settings()
    path = settings.records_path
    records = _records(path, path.stat().st_mtime_ns) if path.exists() else None
    return Deps(_client(), db_engine(settings.db_path), BlobStore(settings.blob_dir), records)


RunDeps = Annotated[Deps, Depends(run_deps)]
