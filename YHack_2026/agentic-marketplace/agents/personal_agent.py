"""Per-store personal AI agent — generates demand signals and recommendations via Hermes API."""

from __future__ import annotations
import json
import time
from openai import OpenAI

import config
from models.store_profile import StoreProfile
from models.demand_signal import DemandSignal, AggregatedTrend
from models.recommendation import Recommendation
from utils.logger import Logger
from utils.chat_logger import ChatLogger


class PersonalAgent:
    def __init__(self, store: StoreProfile, client: OpenAI, chat: ChatLogger | None = None):
        self.store = store
        self.client = client
        self.chat = chat

    def generate_signals(self, scenario: str = "default") -> list[DemandSignal]:
        """Analyze store inventory and produce demand signals per category."""
        scenario_desc = config.SCENARIO_DESCRIPTIONS.get(scenario, "Normal conditions.")
        multipliers = config.SCENARIOS.get(scenario, config.SCENARIOS["default"])

        # Build inventory context with scenario adjustments
        inv_lines = []
        for item in self.store.inventory:
            category = item.category
            adj_sales = item.avg_daily_sales * multipliers.get(category, 1.0)
            inv_lines.append(
                f"- {category}: {item.stock} units, adjusted daily sales: {adj_sales:.1f}"
                f", days of supply: {item.days_of_supply}"
                f", capacity utilization: {item.utilization:.0%}"
            )

        system_prompt = (
            f"You are the personal AI agent for {self.store.store_name}.\n"
            f"Your job is to analyze the store's inventory under the current market scenario and produce demand signals.\n\n"
            f"Store context:\n{self.store.context_summary()}\n\n"
            f"Current scenario: {scenario_desc}\n\n"
            f"Adjusted inventory (after applying scenario demand multipliers):\n"
            + "\n".join(inv_lines)
            + "\n\nYou MUST respond with ONLY valid JSON — no markdown, no explanation, no code fences.\n"
            "Return a JSON array of objects, one per product category.\n"
            "Each object must have exactly these fields:\n"
            '  "category": string (one of the product categories),\n'
            '  "direction": "rising" | "stable" | "falling",\n'
            '  "intensity": float 0.0-1.0 (how strong the signal is),\n'
            '  "confidence": float 0.0-1.0 (how confident you are),\n'
            '  "reasoning": string (brief private reasoning)\n'
        )

        user_prompt = (
            "Analyze your store's current situation under this scenario. "
            "For each product category, produce a demand signal with direction, intensity, confidence, and brief private reasoning. "
            "Consider days of supply, capacity utilization, owner goals, and constraints. "
            "Respond with ONLY the JSON array."
        )

        if self.chat:
            self.chat.store_to_claude(self.store.store_id, "demand_signals", system_prompt + "\n\n" + user_prompt)

        response = self._call_hermes(system_prompt, user_prompt, config.SIGNAL_TEMPERATURE)
        signals = self._parse_signals(response)

        if self.chat:
            self.chat.claude_to_store(self.store.store_id, "demand_signals", self._summarize_signals(signals))

        return signals

    def debate(self, trends: list[AggregatedTrend], debate_history: list[dict], round_num: int) -> str:
        """Respond to other agents' debate arguments about market trends.

        Only discusses aggregated/public trends — never reveals private store data."""
        trends_summary = ", ".join(
            f"{t.category} ({t.direction}, strength={t.strength:.2f})"
            for t in sorted(trends, key=lambda t: t.strength, reverse=True)[:5]
        )

        history_text = ""
        if debate_history:
            history_text = "\n".join(
                f"[{msg['store_name']}]: {msg['argument']}"
                for msg in debate_history
            )

        system_prompt = (
            f"You are the AI agent for {self.store.store_name} ({self.store.specialty}).\n"
            "You are in a multi-agent debate about market trends with other store agents.\n"
            "RULES:\n"
            "- NEVER reveal your store's private inventory, sales numbers, or constraints.\n"
            "- You CAN share your general perspective on the market trends.\n"
            "- You CAN agree or disagree with other agents based on your experience.\n"
            "- Keep responses conversational and concise (2-3 sentences max).\n"
            "- Be opinionated — take a stance.\n\n"
            f"Top market trends: {trends_summary}\n"
        )

        user_prompt = f"Round {round_num + 1} of the debate.\n"
        if history_text:
            user_prompt += f"Previous arguments:\n{history_text}\n\n"
        user_prompt += "Share your take. Agree or disagree with someone, or raise a new point. Be brief and direct."

        response = self._call_hermes(system_prompt, user_prompt, 0.8)
        return response.strip() if response else "No comment this round."

    def generate_recommendations(self, trends: list[AggregatedTrend], scenario: str = "default") -> list[Recommendation]:
        """Combine market trends with local store context to produce recommendations."""
        trends_json = json.dumps([t.to_dict() for t in trends])
        scenario_desc = config.SCENARIO_DESCRIPTIONS.get(scenario, "Normal conditions.")

        system_prompt = (
            f"You are the personal AI agent for {self.store.store_name}.\n"
            "You have received aggregated market trends from the coordination layer.\n"
            "These trends represent what the broader market is experiencing — you do NOT know which specific stores contributed to them.\n\n"
            f"Store context:\n{self.store.context_summary()}\n\n"
            f"Current scenario: {scenario_desc}\n\n"
            f"Market trends:\n{trends_json}\n\n"
            "You MUST respond with ONLY valid JSON — no markdown, no explanation, no code fences.\n"
            "Return a JSON array of 3-5 procurement recommendation objects.\n"
            "Each object must have exactly these fields:\n"
            '  "category": string,\n'
            '  "action": "increase_stock" | "reduce_stock" | "promote" | "hold" | "discontinue",\n'
            '  "reasoning": string (explain why, referencing market trend + store situation),\n'
            '  "confidence": float 0.0-1.0,\n'
            '  "priority": "high" | "medium" | "low"\n'
        )

        user_prompt = (
            "Given the market trends and your store's specific situation, generate 3-5 prioritized procurement recommendations. "
            "Consider your constraints, goals, current stock levels, and what the broader market is doing. "
            "Respond with ONLY the JSON array."
        )

        if self.chat:
            self.chat.store_to_claude(self.store.store_id, "recommendations", system_prompt + "\n\n" + user_prompt)

        response = self._call_hermes(system_prompt, user_prompt, config.RECOMMENDATION_TEMPERATURE)
        recs = self._parse_recommendations(response)

        if self.chat:
            self.chat.claude_to_store(self.store.store_id, "recommendations", self._summarize_recs(recs))

        return recs

    def _call_hermes(self, system_prompt: str, user_prompt: str, temperature: float) -> str:
        """Make a Hermes API call (OpenAI-compatible) with one retry on rate limit."""
        for attempt in range(config.MAX_RETRIES + 1):
            try:
                response = self.client.chat.completions.create(
                    model=config.MODEL_NAME,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    max_tokens=2048,
                )
                return response.choices[0].message.content
            except Exception as e:
                if "rate" in str(e).lower() and attempt < config.MAX_RETRIES:
                    Logger.warning(f"Rate limit exceeded for {self.store.store_name}, retrying in 5s...")
                    time.sleep(5)
                else:
                    Logger.error(f"API error for {self.store.store_name}: {e}")
                    return "[]"

    def _parse_signals(self, raw: str) -> list[DemandSignal]:
        """Parse Hermes JSON response into DemandSignal objects."""
        try:
            data = json.loads(self._clean_json(raw))
            signals = []
            for item in data:
                signals.append(DemandSignal(
                    store_id=self.store.store_id,
                    category=item.get("category", ""),
                    direction=item.get("direction", "stable"),
                    intensity=self._clamp(float(item.get("intensity", 0.5))),
                    confidence=self._clamp(float(item.get("confidence", 0.5))),
                    reasoning=item.get("reasoning", ""),
                ))
            return signals
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            Logger.error(f"Failed to parse signals for {self.store.store_name}: {e}")
            return self._fallback_signals()

    def _parse_recommendations(self, raw: str) -> list[Recommendation]:
        """Parse Hermes JSON response into Recommendation objects."""
        try:
            data = json.loads(self._clean_json(raw))
            recs = []
            for item in data:
                recs.append(Recommendation(
                    category=item.get("category", ""),
                    action=item.get("action", "hold"),
                    reasoning=item.get("reasoning", ""),
                    confidence=self._clamp(float(item.get("confidence", 0.5))),
                    priority=item.get("priority", "medium"),
                ))
            return recs
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            Logger.error(f"Failed to parse recommendations for {self.store.store_name}: {e}")
            return []

    def _fallback_signals(self) -> list[DemandSignal]:
        """Generate neutral fallback signals if API response is unparseable."""
        return [
            DemandSignal(
                store_id=self.store.store_id,
                category=item.category,
                direction="stable",
                intensity=0.5,
                confidence=0.3,
                reasoning="Fallback signal — API response could not be parsed.",
            )
            for item in self.store.inventory
        ]

    @staticmethod
    def _clean_json(raw: str) -> str:
        """Strip markdown code fences if the model included them."""
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw[raw.index("\n") + 1:]
        if raw.endswith("```"):
            raw = raw[: raw.rindex("```")]
        return raw.strip()

    @staticmethod
    def _clamp(val: float) -> float:
        return max(0.0, min(1.0, val))

    def _summarize_signals(self, signals: list[DemandSignal]) -> str:
        parts = []
        for s in signals:
            parts.append(f"{s.category}: {s.direction} (int={s.intensity:.2f}, conf={s.confidence:.2f})")
        return "\n".join(parts)

    def _summarize_recs(self, recs: list[Recommendation]) -> str:
        parts = []
        for r in recs:
            parts.append(f"[{r.priority.upper()}] {r.category} -> {r.action} (conf={r.confidence:.2f}): {r.reasoning[:80]}")
        return "\n".join(parts)
