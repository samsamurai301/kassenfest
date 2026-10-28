from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from kassenfest.api.routes import Current, router
from kassenfest.config import LlmMode, get_settings

app = FastAPI(title="Kassenfest API", version="0.1.0")
app.include_router(router)


class Health(BaseModel):
    status: str
    llm_mode: LlmMode
    api_key_configured: bool
    data_source: Literal["fixtures", "pipeline"]
    month: str


@app.get("/api/health")
def health(world: Current) -> Health:
    settings = get_settings()
    return Health(
        status="ok",
        llm_mode=settings.llm_mode,
        api_key_configured=settings.model_api_key is not None,
        data_source=world.source,
        month=world.month,
    )
