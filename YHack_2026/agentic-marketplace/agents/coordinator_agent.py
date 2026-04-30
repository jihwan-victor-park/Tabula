"""Coordinator agent — aggregates anonymized signals into market-level trends via Hermes API."""

from __future__ import annotations
import json
import time
from collections import defaultdict
from openai import OpenAI

import config
from models.demand_signal import AnonymizedSignal, AggregatedTrend
from utils.logger import Logger
from utils.chat_logger import ChatLogger


class CoordinatorAgent:
    def __init__(self, client: OpenAI, chat: ChatLogger | None = None):
        self.client = client
        self.chat = chat

    def aggregate_trends(self, signals: list[AnonymizedSignal]) -> list[AggregatedTrend]:
        """Send anonymized signals to Hermes and get back market-level trends."""
        signals_json = json.dumps([s.to_dict() for s in signals])

        system_prompt = (
            "You are a market coordination agent for a neighborhood of toy stores.\n"
            "You receive anonymized demand signals from multiple stores. You do NOT know which store sent which signal. "
            "You cannot and should not try to identify individual stores.\n\n"
            "Your job is to synthesize these signals into market-level trends per product category.\n\n"
            "You MUST respond with ONLY valid JSON — no markdown, no explanation, no code fences.\n"
            "Return a JSON array of trend objects, one per product category.\n"
            "Each object must have exactly these fields:\n"
            '  "category": string,\n'
            '  "direction": "rising" | "stable" | "falling",\n'
            '  "strength": float 0.0-1.0,\n'
            '  "signal_count": integer,\n'
            '  "consensus": "strong" | "moderate" | "mixed"\n'
        )

        user_prompt = (
            f"I have received {len(signals)} anonymized demand signals from toy stores in the neighborhood:\n\n"
            f"{signals_json}\n\n"
            "Synthesize these into market-level trends. Identify consensus direction per category, "
            "flag any conflicting signals, and assign confidence. Respond with ONLY the JSON array."
        )

        if self.chat:
            self.chat.coordinator_to_claude("aggregate_trends", system_prompt + "\n\n" + user_prompt)

        response = self._call_hermes(system_prompt, user_prompt)
        trends = self._parse_trends(response, signals)

        if self.chat:
            self.chat.claude_to_coordinator("aggregate_trends", self._summarize_trends(trends))

        return trends

    def _call_hermes(self, system_prompt: str, user_prompt: str) -> str:
        """Make a Hermes API call with one retry on rate limit."""
        for attempt in range(config.MAX_RETRIES + 1):
            try:
                response = self.client.chat.completions.create(
                    model=config.MODEL_NAME,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=config.COORDINATOR_TEMPERATURE,
                    max_tokens=2048,
                )
                return response.choices[0].message.content
            except Exception as e:
                if "rate" in str(e).lower() and attempt < config.MAX_RETRIES:
                    Logger.warning("Coordinator rate limited, retrying in 5s...")
                    time.sleep(5)
                else:
                    Logger.error(f"Coordinator API error: {e}")
                    return "[]"

    def _parse_trends(self, raw: str, signals: list[AnonymizedSignal]) -> list[AggregatedTrend]:
        """Parse Hermes JSON response into AggregatedTrend objects."""
        try:
            data = json.loads(self._clean_json(raw))
            trends = []
            for item in data:
                trends.append(AggregatedTrend(
                    category=item.get("category", ""),
                    direction=item.get("direction", "stable"),
                    strength=self._clamp(float(item.get("strength", 0.5))),
                    signal_count=int(item.get("signal_count", 0)),
                    consensus=item.get("consensus", "mixed"),
                ))
            return trends
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            Logger.error(f"Failed to parse coordinator response: {e}")
            return self._fallback_trends(signals)

    def _fallback_trends(self, signals: list[AnonymizedSignal]) -> list[AggregatedTrend]:
        """Compute simple statistical fallback if Hermes response is unparseable."""
        by_cat: dict[str, list[AnonymizedSignal]] = defaultdict(list)
        for s in signals:
            by_cat[s.category].append(s)

        trends = []
        for cat, sigs in by_cat.items():
            avg_intensity = sum(s.intensity for s in sigs) / len(sigs)
            directions = [s.direction for s in sigs]
            direction = max(set(directions), key=directions.count)
            unique_dirs = len(set(directions))
            consensus = "strong" if unique_dirs == 1 else ("moderate" if unique_dirs == 2 else "mixed")
            trends.append(AggregatedTrend(
                category=cat,
                direction=direction,
                strength=round(avg_intensity, 3),
                signal_count=len(sigs),
                consensus=consensus,
            ))
        return trends

    @staticmethod
    def _clean_json(raw: str) -> str:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw[raw.index("\n") + 1:]
        if raw.endswith("```"):
            raw = raw[: raw.rindex("```")]
        return raw.strip()

    @staticmethod
    def _clamp(val: float) -> float:
        return max(0.0, min(1.0, val))

    def _summarize_trends(self, trends: list[AggregatedTrend]) -> str:
        rising = sorted([t for t in trends if t.direction == "rising"], key=lambda t: t.strength, reverse=True)
        parts = [f"Identified {len(trends)} category trends."]
        if rising:
            parts.append("Rising: " + ", ".join(f"{t.category}({t.strength:.2f},{t.consensus})" for t in rising))
        return " ".join(parts)
