"""Data models for demand signals, anonymized signals, and aggregated trends."""

from __future__ import annotations
from dataclasses import dataclass, field
import json


@dataclass
class DemandSignal:
    store_id: str
    category: str
    direction: str          # "rising" | "stable" | "falling"
    intensity: float        # 0.0 - 1.0
    confidence: float       # 0.0 - 1.0
    reasoning: str = ""

    def to_dict(self) -> dict:
        return {
            "store_id": self.store_id,
            "category": self.category,
            "direction": self.direction,
            "intensity": round(self.intensity, 3),
            "confidence": round(self.confidence, 3),
            "reasoning": self.reasoning,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class AnonymizedSignal:
    signal_id: str
    category: str
    direction: str
    intensity: float
    confidence: float

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id,
            "category": self.category,
            "direction": self.direction,
            "intensity": round(self.intensity, 3),
            "confidence": round(self.confidence, 3),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class AggregatedTrend:
    category: str
    direction: str
    strength: float
    signal_count: int
    consensus: str          # "strong" | "moderate" | "mixed"

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "direction": self.direction,
            "strength": round(self.strength, 3),
            "signal_count": self.signal_count,
            "consensus": self.consensus,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())
