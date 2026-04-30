"""Universal Agent — schemas."""
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


class UserMessage(BaseModel):
    """A message from the business owner, arriving from any channel."""
    message: str
    business_name: str
    location: str
    recipient: str = Field(description="iMessage phone number or Apple ID to reply to")
    # Agent URLs — all default to localhost
    trend_url: str = "http://localhost:8001"
    procurement_url: str = "http://localhost:8003"
    inventory_url: str = "http://localhost:8004"
    price_scout_url: str = "http://localhost:8000"


class UniversalResult(BaseModel):
    """Full result from one universal agent run."""
    message_received: str
    agents_called: list[str] = Field(default_factory=list)
    response_text: str = ""
    confirmation_sent: bool = False
    recipient: str = ""
    error: str | None = None
