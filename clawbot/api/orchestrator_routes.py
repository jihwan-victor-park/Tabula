"""FastAPI app — Orchestrator Agent at port 8005."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from clawbot.agents.orchestrator_agent import run_orchestrator
from clawbot.schemas.orchestrator import InboundMessage, OrchestratorResult


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example → .env and fill it in."
        )
    yield


app = FastAPI(
    title="Orchestrator Agent API",
    description=(
        "Accepts a natural language message from a business owner and chains the "
        "Trend Analyst → Procurement Agent pipeline, then sends an iMessage "
        "confirmation with trend context, supplier quotes, and margin analysis."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/ask",
    response_model=OrchestratorResult,
    summary="Send a natural language message and trigger the full agent pipeline",
)
def post_ask(body: InboundMessage) -> OrchestratorResult:
    """
    The full inference pipeline:

    1. Claude extracts the product and intent from the owner's message.
    2. The Trend Agent checks demand signals for that product category.
    3. The Procurement Agent sources wholesale suppliers and builds an order form.
    4. Claude composes a rich plain-text iMessage with trend insight, order details,
       and margin analysis.
    5. The message is sent via iMessage asking the owner YES/NO to confirm the order.
    """
    try:
        return run_orchestrator(body)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
