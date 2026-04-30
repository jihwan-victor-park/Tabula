"""Privacy layer — strips store identity, adds noise, shuffles signals."""

from __future__ import annotations
import hashlib
import os
import random

from models.demand_signal import DemandSignal, AnonymizedSignal


class Anonymizer:
    def __init__(self, noise_sigma: float = 0.05):
        self.noise_sigma = noise_sigma

    def anonymize(self, signal: DemandSignal) -> AnonymizedSignal:
        signal_id = hashlib.sha256(os.urandom(16)).hexdigest()[:8]
        return AnonymizedSignal(
            signal_id=signal_id,
            category=signal.category,
            direction=signal.direction,
            intensity=self._add_noise(signal.intensity),
            confidence=self._add_noise(signal.confidence),
        )

    def anonymize_batch(self, signals: list[DemandSignal]) -> list[AnonymizedSignal]:
        anon = [self.anonymize(s) for s in signals]
        random.shuffle(anon)
        return anon

    def _add_noise(self, val: float) -> float:
        noised = val + random.gauss(0, self.noise_sigma)
        return round(max(0.0, min(1.0, noised)), 3)
