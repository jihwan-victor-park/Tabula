"""Overnight pipeline — orchestrates the full coordination cycle with Hermes AI + Solana verification."""

from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from openai import OpenAI
from dotenv import load_dotenv

import config
from models.store_profile import StoreProfile
from models.demand_signal import DemandSignal, AnonymizedSignal, AggregatedTrend
from models.recommendation import StoreRecommendationBundle
from agents.personal_agent import PersonalAgent
from agents.coordinator_agent import CoordinatorAgent
from coordination.anonymizer import Anonymizer
from coordination.hex_analytics import HexAnalytics
from coordination.solana_verifier import SolanaVerifier
from utils.logger import Logger
from utils.chat_logger import ChatLogger
from utils.chat_simulation import ChatSimulation


@dataclass
class PipelineResults:
    cycle_id: str = ""
    scenario: str = ""
    generated_at: str = ""
    market_trends: list[AggregatedTrend] = field(default_factory=list)
    store_results: dict[str, StoreRecommendationBundle] = field(default_factory=dict)
    verification: dict | None = None
    ecosystem_health: dict | None = None

    def to_dict(self) -> dict:
        d = {
            "cycle_id": self.cycle_id,
            "scenario": self.scenario,
            "generated_at": self.generated_at,
            "market_trends": [t.to_dict() for t in sorted(self.market_trends, key=lambda t: t.strength, reverse=True)],
            "store_results": [
                self.store_results[k].to_dict()
                for k in sorted(self.store_results.keys())
            ],
        }
        if self.verification:
            d["verification"] = self.verification
        if self.ecosystem_health:
            d["ecosystem_health"] = self.ecosystem_health
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


class OvernightPipeline:
    def __init__(self, scenario: str = "default", verbose: bool = False, chat_mode: bool = False):
        load_dotenv()

        # Hermes API (OpenAI-compatible)
        api_key = os.getenv("NOUS_API_KEY")
        if not api_key:
            raise RuntimeError("NOUS_API_KEY not found. Set it in .env file.")

        self.scenario = scenario
        self.verbose = verbose
        self.chat_mode = chat_mode

        # OpenAI-compatible client pointing to Nous Research
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://inference-api.nousresearch.com/v1",
        )

        self.stores = config.build_store_profiles()
        self.anonymizer = Anonymizer(noise_sigma=config.NOISE_SIGMA)
        self.chat = ChatLogger() if verbose else None
        self.chat_sim = ChatSimulation() if chat_mode else None

        # Solana verifier
        solana_key = os.getenv("SOLANA_PRIVATE_KEY")
        solana_rpc = os.getenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")
        self.verifier = SolanaVerifier(rpc_url=solana_rpc, private_key=solana_key)

        self.coordinator = CoordinatorAgent(self.client, self.chat)
        self.hex = HexAnalytics()

        now = datetime.now(timezone.utc)
        self.generated_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.cycle_id = f"cycle_{now.strftime('%Y%m%d_%H%M%S')}"

    def run(self) -> PipelineResults:
        """Execute the full overnight cycle and return structured results."""
        scenario_desc = config.SCENARIO_DESCRIPTIONS.get(self.scenario, "Unknown scenario.")

        Logger.header(f"Overnight Coordination Cycle: {self.cycle_id}")
        Logger.info(f"Scenario: {self.scenario} — {scenario_desc}")
        Logger.info(f"Processing {len(self.stores)} stores")
        Logger.info(f"AI Model: {config.MODEL_NAME} (Nous Research Hermes)")

        if self.chat_sim:
            self.chat_sim.show_header()
            self.chat_sim.message("start", "coordinator",
                "hey everyone, nightly sync time\nsend me your market reads and i'll crunch the numbers")

        # ── Phase 1: Generate demand signals ──────────────────────────────
        Logger.step("Phase 1: Generating demand signals")
        all_signals: list[DemandSignal] = []

        for store in self.stores:
            Logger.info(f"  {store.store_name}...")
            agent = PersonalAgent(store, self.client, self.chat)
            signals = agent.generate_signals(self.scenario)
            all_signals.extend(signals)

            # Solana: commit each store's signals on-chain
            signal_dicts = [s.to_dict() for s in signals]
            self.verifier.commit_signals(signal_dicts, store.store_id)
            Logger.success(f"  {store.store_name}: {len(signals)} signals (hash committed)")

        if self.chat_sim:
            self.chat_sim.system("after_signals", "stores are checking their inventory")

        # ── Phase 2: Anonymize ────────────────────────────────────────────
        Logger.step("Phase 2: Anonymizing signals")
        anon_signals = self.anonymizer.anonymize_batch(all_signals)
        Logger.success(f"Anonymized {len(anon_signals)} signals (stripped IDs, added noise, shuffled)")

        if self.chat_sim:
            self.chat_sim.message("after_anonymization", "privacy_shield",
                f"running all {len(anon_signals)} signals through the privacy layer\n"
                "stripping store IDs... adding noise... shuffling order...\n"
                "done. coordinator can't tell who sent what now")

        # ── Phase 3: Aggregate trends ─────────────────────────────────────
        Logger.step("Phase 3: Coordinator aggregating trends via Hermes")
        trends = self.coordinator.aggregate_trends(anon_signals)
        Logger.success(f"Identified {len(trends)} market trends")

        if self.chat_sim:
            self.chat_sim.system("after_trends", "coordinator finished analysis")
            rising = [t for t in trends if t.direction == "rising"]
            if rising:
                names = ", ".join(t.category.replace("_", " ") for t in sorted(rising, key=lambda t: t.strength, reverse=True))
                self.chat_sim.message("after_trends", "coordinator",
                    f"Just ran the numbers. Rising categories: {names}.")

        # ── Phase 3.5: Multi-agent debate ─────────────────────────────────
        Logger.step("Phase 3.5: Agent-to-agent debate on market trends")
        debate_log = self._run_debate(trends)

        if self.chat_sim:
            self.chat_sim.system("after_debate", "agents finished debating market trends")
            for entry in debate_log[-3:]:
                self.chat_sim.message("debate", entry["store_id"],
                    entry["argument"][:120])

        # ── Phase 3.75: Hex-powered ecosystem health analytics ─────────────
        Logger.step("Phase 3.75: Hex ecosystem health analysis")
        self._ecosystem_health = self.hex.analyze(
            raw_signals=all_signals,
            anon_signals=anon_signals,
            trends=trends,
            store_count=len(self.stores),
        )

        if self.chat_sim:
            h = self._ecosystem_health
            self.chat_sim.system("hex_analytics",
                f"Hex ecosystem health: {h.overall_health:.0f}/100 | "
                f"anomalies: {h.anomaly_count} | "
                f"collaboration value: +{h.collaboration_value:.0f}%")

        # ── Phase 4: Generate per-store recommendations ───────────────────
        Logger.step("Phase 4: Generating personalized recommendations via Hermes")
        store_results: dict[str, StoreRecommendationBundle] = {}

        for store in self.stores:
            Logger.info(f"  {store.store_name}...")
            agent = PersonalAgent(store, self.client, self.chat)
            recs = agent.generate_recommendations(trends, self.scenario)
            bundle = StoreRecommendationBundle(
                store_id=store.store_id,
                store_name=store.store_name,
                generated_at=self.generated_at,
                recommendations=recs,
            )
            store_results[store.store_id] = bundle
            Logger.success(f"  {store.store_name}: {len(recs)} recommendations")

        if self.chat_sim:
            self.chat_sim.system("after_recommendations", "everyone got their personalized recommendations")
            self.chat_sim.message("end", "coordinator",
                "alright that's a wrap\nrecommendations are in your output files\nsame time tomorrow night?")
            self.chat_sim.system("end", "Overnight cycle complete")

        # ── Phase 5: Build results and commit summary on-chain ────────────
        results = PipelineResults(
            cycle_id=self.cycle_id,
            scenario=self.scenario,
            generated_at=self.generated_at,
            market_trends=trends,
            store_results=store_results,
        )

        # Solana: commit the full results hash on-chain
        summary_for_chain = {
            "cycle_id": self.cycle_id,
            "generated_at": self.generated_at,
            "trend_count": len(trends),
            "store_count": len(store_results),
            "market_trends": [t.to_dict() for t in trends],
        }
        self.verifier.commit_summary(summary_for_chain)
        results.verification = self.verifier.get_report().to_dict()

        Logger.success(f"Verification: {results.verification['signal_count']} signal hashes + summary committed")

        # Attach ecosystem health from Hex analytics
        if hasattr(self, '_ecosystem_health') and self._ecosystem_health:
            results.ecosystem_health = self._ecosystem_health.to_dict()

        # ── Write outputs ─────────────────────────────────────────────────
        self._write_outputs(results)

        return results

    def _run_debate(self, trends: list[AggregatedTrend]) -> list[dict]:
        """Run a multi-round agent-to-agent debate about the aggregated trends."""
        debate_history: list[dict] = []
        agents = {
            store.store_id: PersonalAgent(store, self.client, self.chat)
            for store in self.stores
        }

        for round_num in range(config.DEBATE_ROUNDS):
            Logger.info(f"  Debate round {round_num + 1}/{config.DEBATE_ROUNDS}")

            for store in self.stores:
                agent = agents[store.store_id]
                argument = agent.debate(trends, debate_history, round_num)

                entry = {
                    "round": round_num,
                    "store_id": store.store_id,
                    "store_name": store.store_name,
                    "argument": argument,
                    "timestamp": self.generated_at,
                }
                debate_history.append(entry)
                Logger.info(f"    {store.store_name}: {argument[:80]}...")

                if self.chat:
                    self.chat.store_to_claude(store.store_id, "debate", f"Round {round_num + 1}: {argument}")

        self._debate_log = debate_history
        Logger.success(f"Debate complete: {len(debate_history)} messages across {config.DEBATE_ROUNDS} rounds")
        return debate_history

    def _write_outputs(self, results: PipelineResults) -> None:
        """Write all JSON output files to output/ directory."""
        output_dir = os.path.join(os.path.dirname(__file__), "..", "output")
        os.makedirs(output_dir, exist_ok=True)

        # Main results
        with open(os.path.join(output_dir, "results.json"), "w") as f:
            f.write(results.to_json())
        Logger.success("Wrote output/results.json")

        # Market trends only
        with open(os.path.join(output_dir, "market_trends.json"), "w") as f:
            json.dump({
                "generated_at": results.generated_at,
                "scenario": results.scenario,
                "market_trends": [t.to_dict() for t in results.market_trends],
            }, f, indent=2)

        # Per-store recommendations
        for store_id, bundle in results.store_results.items():
            fname = f"store_{store_id}_recommendations.json"
            with open(os.path.join(output_dir, fname), "w") as f:
                json.dump(bundle.to_dict(), f, indent=2)

        # Verification report
        if results.verification:
            with open(os.path.join(output_dir, "verification.json"), "w") as f:
                json.dump(results.verification, f, indent=2)
            Logger.success("Wrote output/verification.json")

        # Debate log
        if hasattr(self, '_debate_log') and self._debate_log:
            with open(os.path.join(output_dir, "debate_log.json"), "w") as f:
                json.dump({
                    "cycle_id": results.cycle_id,
                    "generated_at": results.generated_at,
                    "rounds": config.DEBATE_ROUNDS,
                    "participants": [s.store_name for s in self.stores],
                    "messages": self._debate_log,
                }, f, indent=2)
            Logger.success("Wrote output/debate_log.json")

        # Ecosystem health (Hex analytics)
        if results.ecosystem_health:
            with open(os.path.join(output_dir, "ecosystem_health.json"), "w") as f:
                json.dump({
                    "cycle_id": results.cycle_id,
                    "generated_at": results.generated_at,
                    "hex_enabled": self.hex.hex_enabled,
                    **results.ecosystem_health,
                }, f, indent=2)
            Logger.success("Wrote output/ecosystem_health.json")

        # Chat logs
        if self.chat:
            with open(os.path.join(output_dir, "conversation_log.json"), "w") as f:
                f.write(self.chat.to_json())

        if self.chat_sim:
            with open(os.path.join(output_dir, "group_chat.json"), "w") as f:
                f.write(self.chat_sim.to_json())
