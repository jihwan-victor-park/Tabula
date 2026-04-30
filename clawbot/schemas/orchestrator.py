"""
Orchestrator Agent — schemas for inbound natural language messages and results.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class InboundMessage(BaseModel):
    """
    A natural language message from the business owner, e.g. from iMessage.
    The orchestrator interprets intent and chains trend + procurement agents.
    """

    message: str = Field(description="Raw text from the business owner")
    business_name: str
    location: str
    recipient: str = Field(description="iMessage phone number or Apple ID to reply to")
    # Agent API URLs — defaults assume all agents run locally
    trend_url: str = "http://localhost:8001"
    procurement_url: str = "http://localhost:8003"
    inventory_url: str | None = None


class ExtractedIntent(BaseModel):
    """Structured intent extracted from a natural language owner message."""

    product_name: str
    category: str
    quantity_estimate: int = Field(20, description="Estimated units to order")
    confidence: float = Field(description="0.0 – 1.0 confidence in the extraction")
    reasoning: str


class OrchestratorResult(BaseModel):
    """Full output from one orchestrator run."""

    message_received: str
    extracted_intent: ExtractedIntent | None = None
    trend_summary: str | None = None
    trend_direction: str | None = None
    trend_confidence: float | None = None
    order: dict[str, Any] | None = None
    confirmation_sent: bool = False
    confirmation_recipient: str | None = None
    imsg_text: str | None = None
    error: str | None = None
