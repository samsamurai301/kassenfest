from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]

LlmMode = Literal["live", "record", "replay"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=(),
    )

    model_api_key: SecretStr | None = None
    model_base_url: str = "https://api.meta.ai/v1"
    muse_model: str = "muse-spark-1.3"
    sam_model: str = "sam-3.1"

    # live: always call the API and overwrite the cache
    # record: serve from cache, call the API on a miss and store the result
    # replay: cache only; a miss is an error (demo and judges' runs)
    llm_mode: LlmMode = "record"
    llm_cache_dir: Path = REPO_ROOT / "var" / "llm-cache"
    llm_call_log: Path = REPO_ROOT / "var" / "llm-calls.jsonl"
    llm_max_concurrency: int = 8
    llm_timeout_s: float = 180.0
    llm_max_retries: int = 4

    db_path: Path = REPO_ROOT / "var" / "kassenfest.db"
    blob_dir: Path = REPO_ROOT / "var" / "blobs"

    # The Pflegedienst's own records; synthetic ones until a billing system is wired in.
    records_path: Path = REPO_ROOT / "data" / "synthetic" / "demo" / "master_data.json"
    # auto: the pipeline's results once it has processed a document, else the fixtures
    api_source: Literal["auto", "fixtures", "pipeline"] = "auto"


@lru_cache
def get_settings() -> Settings:
    return Settings()
