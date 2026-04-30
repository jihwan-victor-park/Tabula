from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from clawbot.config.settings import AppPaths, get_paths
from clawbot.tools.json_store import load_json, save_json, utc_now


JsonDict = dict[str, Any]


@dataclass
class SessionMemory:
    paths: AppPaths | None = None

    def __post_init__(self) -> None:
        if self.paths is None:
            self.paths = get_paths()

    def load(self) -> JsonDict:
        assert self.paths is not None
        return load_json(
            self.paths.session_memory_path,
            {"version": 1, "updatedAt": None, "recentNotes": []},
        )

    def append_note(self, note: str, kind: str = "operator") -> JsonDict:
        payload = self.load()
        payload["recentNotes"].append(
            {"kind": kind, "note": note, "createdAt": utc_now()}
        )
        payload["recentNotes"] = payload["recentNotes"][-25:]
        payload["updatedAt"] = utc_now()
        assert self.paths is not None
        save_json(self.paths.session_memory_path, payload)
        return payload
