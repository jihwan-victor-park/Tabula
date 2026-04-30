"""Hex API integration — triggers analytics notebooks and computes ecosystem health metrics."""

from __future__ import annotations
import json
import os
import time
import math
from collections import defaultdict
from dataclasses import dataclass, field

import requests

from models.demand_signal import DemandSignal, AnonymizedSignal, AggregatedTrend
from utils.logger import Logger


@dataclass
class EcosystemHealth:
    """Metrics computed by Hex analytics for the ecosystem."""
    overall_health: float = 0.0          # 0-100 score
    consensus_strength: float = 0.0      # avg consensus across categories
    signal_diversity: float = 0.0        # how diverse are store signals (good = high)
    anomaly_count: int = 0               # signals flagged as outliers
    anomalous_signals: list[dict] = field(default_factory=list)
    collaboration_value: float = 0.0     # % improvement from sharing vs solo
    category_alignment: dict = field(default_factory=dict)  # per-category agreement
    participation_rate: float = 0.0      # % of stores actively contributing
    hex_run_id: str | None = None
    hex_run_url: str | None = None

    def to_dict(self) -> dict:
        return {
            "overall_health": round(self.overall_health, 1),
            "consensus_strength": round(self.consensus_strength, 2),
            "signal_diversity": round(self.signal_diversity, 2),
            "anomaly_count": self.anomaly_count,
            "anomalous_signals": self.anomalous_signals,
            "collaboration_value": round(self.collaboration_value, 1),
            "category_alignment": {
                k: round(v, 2) for k, v in self.category_alignment.items()
            },
            "participation_rate": round(self.participation_rate, 1),
            "hex_run_id": self.hex_run_id,
            "hex_run_url": self.hex_run_url,
        }


class HexAnalytics:
    """Computes ecosystem health metrics and optionally syncs with Hex API."""

    def __init__(self):
        self.hex_token = os.getenv("HEX_API_TOKEN")
        self.hex_project_id = os.getenv("HEX_PROJECT_ID")
        self.hex_base_url = os.getenv("HEX_BASE_URL", "https://app.hex.tech/api/v1")

    @property
    def hex_enabled(self) -> bool:
        return bool(self.hex_token and self.hex_project_id)

    def analyze(
        self,
        raw_signals: list[DemandSignal],
        anon_signals: list[AnonymizedSignal],
        trends: list[AggregatedTrend],
        store_count: int,
    ) -> EcosystemHealth:
        """Run full ecosystem health analysis. Triggers Hex if configured."""
        Logger.step("Hex Analytics: Computing ecosystem health metrics")

        health = EcosystemHealth()

        # 1. Consensus strength — average across all categories
        if trends:
            consensus_map = {"strong": 1.0, "moderate": 0.6, "mixed": 0.3}
            health.consensus_strength = sum(
                consensus_map.get(t.consensus, 0.3) for t in trends
            ) / len(trends)

        # 2. Signal diversity — std dev of intensities (higher = more diverse perspectives)
        if anon_signals:
            by_cat: dict[str, list[float]] = defaultdict(list)
            for s in anon_signals:
                by_cat[s.category].append(s.intensity)

            diversities = []
            for cat, intensities in by_cat.items():
                if len(intensities) > 1:
                    mean = sum(intensities) / len(intensities)
                    variance = sum((x - mean) ** 2 for x in intensities) / len(intensities)
                    diversities.append(math.sqrt(variance))
            health.signal_diversity = sum(diversities) / len(diversities) if diversities else 0

        # 3. Anomaly detection — flag signals that deviate >2σ from category mean
        anomalies = self._detect_anomalies(anon_signals)
        health.anomaly_count = len(anomalies)
        health.anomalous_signals = anomalies

        # 4. Collaboration value — compare individual variance to collective trend strength
        if raw_signals and trends:
            health.collaboration_value = self._compute_collaboration_value(raw_signals, trends)

        # 5. Category alignment — per-category agreement score
        health.category_alignment = self._compute_alignment(anon_signals)

        # 6. Participation rate
        unique_stores = len(set(s.store_id for s in raw_signals))
        health.participation_rate = (unique_stores / store_count * 100) if store_count else 0

        # 7. Overall health score (weighted composite)
        health.overall_health = self._compute_overall(health)

        # 8. Trigger Hex notebook if configured
        if self.hex_enabled:
            hex_result = self._trigger_hex_run(raw_signals, anon_signals, trends, health)
            health.hex_run_id = hex_result.get("run_id")
            health.hex_run_url = hex_result.get("run_url")

        Logger.success(f"Ecosystem health: {health.overall_health:.0f}/100 "
                       f"(consensus={health.consensus_strength:.0%}, "
                       f"anomalies={health.anomaly_count}, "
                       f"collaboration_value=+{health.collaboration_value:.0f}%)")

        return health

    def _detect_anomalies(self, signals: list[AnonymizedSignal]) -> list[dict]:
        """Flag signals where intensity deviates >2σ from category mean."""
        by_cat: dict[str, list[AnonymizedSignal]] = defaultdict(list)
        for s in signals:
            by_cat[s.category].append(s)

        anomalies = []
        for cat, sigs in by_cat.items():
            intensities = [s.intensity for s in sigs]
            if len(intensities) < 3:
                continue
            mean = sum(intensities) / len(intensities)
            std = math.sqrt(sum((x - mean) ** 2 for x in intensities) / len(intensities))
            if std == 0:
                continue

            for s in sigs:
                z_score = abs(s.intensity - mean) / std
                if z_score > 2.0:
                    anomalies.append({
                        "signal_id": s.signal_id,
                        "category": cat,
                        "intensity": s.intensity,
                        "z_score": round(z_score, 2),
                        "category_mean": round(mean, 3),
                        "category_std": round(std, 3),
                        "flag": "outlier",
                    })
        return anomalies

    def _compute_collaboration_value(
        self, raw_signals: list[DemandSignal], trends: list[AggregatedTrend]
    ) -> float:
        """Estimate % improvement from collective vs individual analysis.

        Compares individual signal variance to aggregated trend confidence.
        Higher trend strength relative to individual noise = more collaboration value.
        """
        by_cat: dict[str, list[float]] = defaultdict(list)
        for s in raw_signals:
            by_cat[s.category].append(s.intensity)

        individual_uncertainty = []
        for cat, intensities in by_cat.items():
            if len(intensities) > 1:
                mean = sum(intensities) / len(intensities)
                variance = sum((x - mean) ** 2 for x in intensities) / len(intensities)
                individual_uncertainty.append(math.sqrt(variance))

        avg_individual_uncertainty = (
            sum(individual_uncertainty) / len(individual_uncertainty)
            if individual_uncertainty else 0.5
        )

        avg_trend_strength = (
            sum(t.strength for t in trends) / len(trends) if trends else 0.5
        )

        # Collaboration value: how much the aggregation reduces uncertainty
        if avg_individual_uncertainty > 0:
            reduction = (avg_individual_uncertainty - (1 - avg_trend_strength)) / avg_individual_uncertainty
            return max(0, min(100, reduction * 100))
        return 0

    def _compute_alignment(self, signals: list[AnonymizedSignal]) -> dict[str, float]:
        """Per-category agreement score (0-1). 1 = all signals agree on direction."""
        by_cat: dict[str, list[str]] = defaultdict(list)
        for s in signals:
            by_cat[s.category].append(s.direction)

        alignment = {}
        for cat, directions in by_cat.items():
            if not directions:
                continue
            most_common = max(set(directions), key=directions.count)
            alignment[cat] = directions.count(most_common) / len(directions)
        return alignment

    def _compute_overall(self, health: EcosystemHealth) -> float:
        """Weighted composite health score 0-100."""
        score = 0.0
        score += health.consensus_strength * 30       # 30% weight on consensus
        score += health.participation_rate * 0.2       # 20% weight on participation
        score += health.collaboration_value * 0.3      # 30% weight on collab value
        score += (1 - min(health.anomaly_count / 5, 1)) * 20  # 20% penalty for anomalies
        return max(0, min(100, score))

    def _trigger_hex_run(
        self,
        raw_signals: list[DemandSignal],
        anon_signals: list[AnonymizedSignal],
        trends: list[AggregatedTrend],
        health: EcosystemHealth,
    ) -> dict:
        """Trigger a Hex project run via the API with ecosystem data as input."""
        Logger.info("Hex: Triggering analytics notebook run...")

        input_params = {
            "signal_count": str(len(anon_signals)),
            "store_count": str(len(set(s.store_id for s in raw_signals))),
            "trend_data": json.dumps([t.to_dict() for t in trends]),
            "anonymized_signals": json.dumps([s.to_dict() for s in anon_signals]),
            "health_metrics": json.dumps(health.to_dict()),
        }

        try:
            response = requests.post(
                f"{self.hex_base_url}/projects/{self.hex_project_id}/runs",
                json={
                    "inputParams": input_params,
                    "updatePublishedResults": True,
                },
                headers={"Authorization": f"Bearer {self.hex_token}"},
                timeout=30,
            )

            if response.ok:
                data = response.json()
                run_id = data.get("runId", "")
                run_url = data.get("runUrl", "")
                Logger.success(f"Hex run triggered: {run_id}")

                # Poll for completion (max 60s)
                status = self._poll_hex_run(run_id, timeout=60)
                Logger.info(f"Hex run status: {status}")

                return {"run_id": run_id, "run_url": run_url, "status": status}
            else:
                Logger.warning(f"Hex API returned {response.status_code}: {response.text[:200]}")
                return {"error": f"HTTP {response.status_code}"}

        except Exception as e:
            Logger.warning(f"Hex API call failed (non-blocking): {e}")
            return {"error": str(e)}

    def _poll_hex_run(self, run_id: str, timeout: int = 60) -> str:
        """Poll Hex run status until complete or timeout."""
        start = time.time()
        while time.time() - start < timeout:
            try:
                resp = requests.get(
                    f"{self.hex_base_url}/projects/{self.hex_project_id}/runs/{run_id}",
                    headers={"Authorization": f"Bearer {self.hex_token}"},
                    timeout=10,
                )
                if resp.ok:
                    status = resp.json().get("status", "UNKNOWN")
                    if status in ("COMPLETED", "ERRORED", "KILLED"):
                        return status
            except Exception:
                pass
            time.sleep(3)
        return "TIMEOUT"
