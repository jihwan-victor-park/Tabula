"""Universal Agent API — reactive (/ask) and proactive (/digest) on port 8006."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from clawbot.agents.universal_agent import run_universal_agent, send_digest
from clawbot.auth.auth0 import verify_token
from clawbot.schemas.imsg import DigestRequest, DigestResult
from clawbot.schemas.universal import UniversalResult, UserMessage


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")
    from clawbot.tools.mongodb import get_client
    try:
        get_client().admin.command("ping")
    except Exception as exc:
        raise RuntimeError(f"MongoDB is not reachable: {exc}")
    yield


app = FastAPI(
    title="Universal Agent",
    description=(
        "Single iMessage agent: responds to owner messages (/ask) "
        "and pushes proactive digests (/digest)."
    ),
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ask", response_model=UniversalResult)
def post_ask(body: UserMessage, claims: dict = Depends(verify_token)) -> UniversalResult:
    """Reactive: handle a natural language message from the business owner."""
    try:
        return run_universal_agent(body)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/ask/internal", response_model=UniversalResult)
def post_ask_internal(body: UserMessage) -> UniversalResult:
    """Internal: same as /ask but no auth — only callable from localhost."""
    try:
        return run_universal_agent(body)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/digest", response_model=DigestResult)
def post_digest(body: DigestRequest) -> DigestResult:
    """Proactive: build and send an unprompted business briefing via iMessage."""
    try:
        return send_digest(body)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
