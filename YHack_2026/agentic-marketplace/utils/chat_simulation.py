"""Group-chat simulation between store agents — casual banter messages."""

from __future__ import annotations
import json
from datetime import datetime, timezone, timedelta


class ChatSimulation:
    def __init__(self) -> None:
        self.entries: list[dict] = []
        self._base_time = datetime.now(timezone.utc)
        self._offset = 0

    def _ts(self) -> str:
        t = self._base_time + timedelta(seconds=self._offset)
        self._offset += 1
        return t.strftime("%Y-%m-%dT%H:%M:%SZ")

    def show_header(self) -> None:
        self.entries.append({"phase": "start", "kind": "system", "text": "Overnight cycle started", "timestamp": self._ts()})

    def system(self, phase: str, text: str) -> None:
        self.entries.append({"phase": phase, "kind": "system", "text": text, "timestamp": self._ts()})

    def message(self, phase: str, sender: str, text: str) -> None:
        self.entries.append({"phase": phase, "kind": "message", "sender": sender, "text": text, "timestamp": self._ts()})

    def to_dict(self) -> dict:
        return {
            "generated_at": self._base_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "entry_count": len(self.entries),
            "entries": self.entries,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)
