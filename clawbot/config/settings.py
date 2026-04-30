from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class AppPaths:
    root: Path = REPO_ROOT
    state_dir: Path = REPO_ROOT / ".openclaw" / "price-scout"
    prompts_dir: Path = REPO_ROOT / "prompts"
    settings_path: Path = state_dir / "settings.json"
    watchlist_path: Path = state_dir / "watchlist.json"
    findings_path: Path = state_dir / "findings.json"
    alerts_path: Path = state_dir / "alerts.json"
    session_memory_path: Path = state_dir / "session-memory.json"


def get_paths() -> AppPaths:
    return AppPaths()
