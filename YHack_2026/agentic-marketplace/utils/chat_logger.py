"""Records API request/response transcripts for --verbose mode."""

from __future__ import annotations
import json


class ChatLogger:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def store_to_claude(self, store_id: str, label: str, prompt: str) -> None:
        self.entries.append({
            "direction": "store_to_api",
            "store_id": store_id,
            "label": label,
            "content": prompt,
        })

    def claude_to_store(self, store_id: str, label: str, response: str) -> None:
        self.entries.append({
            "direction": "api_to_store",
            "store_id": store_id,
            "label": label,
            "content": response,
        })

    def coordinator_to_claude(self, label: str, prompt: str) -> None:
        self.entries.append({
            "direction": "coordinator_to_api",
            "label": label,
            "content": prompt,
        })

    def claude_to_coordinator(self, label: str, response: str) -> None:
        self.entries.append({
            "direction": "api_to_coordinator",
            "label": label,
            "content": response,
        })

    def to_json(self) -> str:
        return json.dumps(self.entries, indent=2)
