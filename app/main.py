from __future__ import annotations

import json
import logging
import mimetypes
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db
from .config import (
    APP_VERSION,
    MAX_INPUT_CHARS,
    MIN_INPUT_CHARS,
    STATIC_DIR,
    has_credentials,
)
from .examples import EXAMPLES
from .llm import get_provider
from .models import ChallengeMessage
from .service import InputError, stream_analysis, stream_challenge, validate_input

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("atlas")

# Windows 的 MIME 注册表有时会把 .js 识别成 text/plain，导致 ES Module 加载失败。
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    provider = get_provider()
    log.info(
        "Argument Atlas %s | provider=%s mode=%s model=%s",
        APP_VERSION,
        provider.name,
        provider.mode,
        provider.model,
    )
    yield


app = FastAPI(
    title="Argument Atlas · 论点地图",
    description="把一段文字拆成一张可以追问的论证地图。",
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class AnalyzeRequest(BaseModel):
    text: str = ""


class ChallengeRequest(BaseModel):
    analysis_id: str
    node_id: str
    message: str = ""
    history: list[ChallengeMessage] = Field(default_factory=list)


def _ndjson(events: AsyncIterator[dict]) -> StreamingResponse:
    async def generate():
        async for event in events:
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health():
    provider = get_provider()
    return {
        "ok": True,
        "version": APP_VERSION,
        "provider": provider.name,
        "mode": provider.mode,
        "model": provider.model,
        "live_ready": has_credentials(),
        "limits": {"min_chars": MIN_INPUT_CHARS, "max_chars": MAX_INPUT_CHARS},
    }


@app.get("/api/examples")
async def examples():
    return {"examples": EXAMPLES}


@app.get("/api/analyses")
async def analyses():
    return {"items": db.list_analyses()}


@app.get("/api/analyses/{analysis_id}")
async def analysis_detail(analysis_id: str):
    record = db.get_analysis(analysis_id)
    if record is None:
        raise HTTPException(status_code=404, detail="找不到这次拆解。")
    return record


@app.delete("/api/analyses/{analysis_id}")
async def remove_analysis(analysis_id: str):
    if not db.delete_analysis(analysis_id):
        raise HTTPException(status_code=404, detail="找不到这次拆解。")
    return {"ok": True}


@app.post("/api/analyze")
async def analyze(request: AnalyzeRequest):
    try:
        text = validate_input(request.text)
    except InputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _ndjson(stream_analysis(text))


@app.post("/api/challenge")
async def challenge(request: ChallengeRequest):
    record = db.get_analysis(request.analysis_id)
    if record is None:
        raise HTTPException(status_code=404, detail="找不到这次拆解，请重新分析。")
    nodes = record["analysis"].get("nodes", [])
    if request.node_id != "thesis" and not any(
        node.get("id") == request.node_id for node in nodes
    ):
        raise HTTPException(status_code=404, detail="找不到这个节点。")
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="先写下一个问题吧。")

    history = [message.model_dump() for message in request.history]
    return _ndjson(
        stream_challenge(request.analysis_id, request.node_id, history, request.message)
    )
