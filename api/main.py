"""FastAPI app — exposes the Trend Analyst Agent as a REST endpoint."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

from clawbot.agents.trend_agent import run_trend_agent
from clawbot.agents.recommendation_memory import get_all, record_outcome
from clawbot.schemas.trend import TrendReport, TrendRequest


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set. Copy .env.example → .env and fill it in.")
    yield


app = FastAPI(
    title="Trend Analyst Agent API",
    description=(
        "Claude-powered agent that analyzes product category trends for small businesses. "
        "Cross-references Google Trends, Reddit signals, local events, and the owner's "
        "sales history to produce inventory recommendations."
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


@app.post("/analyze", response_model=TrendReport, summary="Run a full trend analysis")
def analyze(request: TrendRequest) -> TrendReport:
    try:
        return run_trend_agent(request)
    except KeyError as exc:
        raise HTTPException(status_code=500, detail=f"Missing configuration: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/categories/labels")
def get_labels() -> dict[str, list[str]]:
    return {"statuses": ["trending", "stable", "fading"]}


class FeedbackRequest(BaseModel):
    recommendation_id: str
    outcome: str


@app.post("/feedback")
def feedback(req: FeedbackRequest) -> dict[str, str]:
    try:
        found = record_outcome(req.recommendation_id, req.outcome)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not found:
        raise HTTPException(status_code=404, detail=f"Recommendation {req.recommendation_id!r} not found")
    return {"status": "recorded", "recommendation_id": req.recommendation_id, "outcome": req.outcome}


@app.get("/memory")
def memory() -> dict:
    return get_all()
