from fastapi import FastAPI
from pydantic import BaseModel

from kassenfest.config import LlmMode, get_settings

app = FastAPI(title="Kassenfest API", version="0.1.0")


class Health(BaseModel):
    status: str
    llm_mode: LlmMode
    api_key_configured: bool


@app.get("/api/health")
def health() -> Health:
    settings = get_settings()
    return Health(
        status="ok",
        llm_mode=settings.llm_mode,
        api_key_configured=settings.model_api_key is not None,
    )
