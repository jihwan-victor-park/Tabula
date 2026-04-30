"""
Recommendation memory — tracks what was recommended vs what the owner acted on.

Learns preferences silently over time. No configuration required from the owner.
Each recommendation is stored with an outcome: pending → acted | ignored.
After 7 days with no feedback, pending recommendations are auto-aged to ignored.

Preference scores per category drive how Claude prioritises its next analysis.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

_MEMORY_PATH = Path(__file__).parent.parent.parent / ".openclaw" / "trend-agent" / "recommendation_memory.json"
_IGNORE_AFTER_DAYS = 7
_MIN_INTERACTIONS = 3  # need at least this many before influencing Claude


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _load() -> dict[str, Any]:
    if not _MEMORY_PATH.exists():
        return {"version": 1, "recommendations": [], "preferences": {}}
    with _MEMORY_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict[str, Any]) -> None:
    _MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _MEMORY_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def _make_id(category: str, product_name: str, date: str) -> str:
    raw = f"{category}:{product_name}:{date}"
    return "rec-" + hashlib.sha1(raw.encode()).hexdigest()[:12]


def _recompute_preferences(recommendations: list[dict[str, Any]]) -> dict[str, Any]:
    """Recompute per-category preference scores from all non-pending recommendations."""
    counts: dict[str, dict[str, int]] = {}
    for rec in recommendations:
        if rec["outcome"] == "pending":
            continue
        cat = rec["category"]
        if cat not in counts:
            counts[cat] = {"acted": 0, "ignored": 0}
        counts[cat][rec["outcome"]] += 1

    prefs = {}
    for cat, c in counts.items():
        total = c["acted"] + c["ignored"]
        prefs[cat] = {
            "acted": c["acted"],
            "ignored": c["ignored"],
            "total": total,
            "score": round(c["acted"] / total, 2) if total > 0 else 0.5,
            "reliable": total >= _MIN_INTERACTIONS,
        }
    return prefs


def _age_pending(recommendations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Auto-mark old pending recommendations as ignored."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=_IGNORE_AFTER_DAYS)
    for rec in recommendations:
        if rec["outcome"] != "pending":
            continue
        made_at = datetime.fromisoformat(rec["made_at"].replace("Z", "+00:00"))
        if made_at < cutoff:
            rec["outcome"] = "ignored"
            rec["outcome_recorded_at"] = _utc_now()
            rec["auto_aged"] = True
    return recommendations


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def record_recommendations(
    category: str,
    recommendations: list[dict[str, Any]],
    analysis_date: str,
) -> list[str]:
    """
    Persist a batch of recommendations for a category as pending.

    Args:
        category: Product category name.
        recommendations: List of dicts with at least 'product_name' and 'action'.
        analysis_date: ISO date string (YYYY-MM-DD).

    Returns:
        List of recommendation IDs assigned to each item.
    """
    data = _load()
    data["recommendations"] = _age_pending(data["recommendations"])

    ids = []
    for rec in recommendations:
        rec_id = _make_id(category, rec["product_name"], analysis_date)
        ids.append(rec_id)

        # Don't duplicate — if same rec was made today, skip
        if any(r["id"] == rec_id for r in data["recommendations"]):
            continue

        data["recommendations"].append({
            "id": rec_id,
            "made_at": _utc_now(),
            "analysis_date": analysis_date,
            "category": category,
            "product_name": rec["product_name"],
            "action": rec["action"],
            "outcome": "pending",
            "outcome_recorded_at": None,
            "auto_aged": False,
        })

    # Keep last 200 recommendations
    data["recommendations"] = data["recommendations"][-200:]
    data["preferences"] = _recompute_preferences(data["recommendations"])
    _save(data)
    return ids


def record_outcome(recommendation_id: str, outcome: str) -> bool:
    """
    Record the owner's response to a recommendation.

    Args:
        recommendation_id: ID returned by record_recommendations.
        outcome: 'acted' or 'ignored'.

    Returns:
        True if found and updated, False if not found.
    """
    if outcome not in ("acted", "ignored"):
        raise ValueError("outcome must be 'acted' or 'ignored'")

    data = _load()
    for rec in data["recommendations"]:
        if rec["id"] == recommendation_id:
            rec["outcome"] = outcome
            rec["outcome_recorded_at"] = _utc_now()
            rec["auto_aged"] = False
            data["preferences"] = _recompute_preferences(data["recommendations"])
            _save(data)
            return True
    return False


def get_preference_context() -> str:
    """
    Return a plain-English summary of the owner's preferences for injection
    into Claude's system prompt. Returns empty string if insufficient data.
    """
    data = _load()
    data["recommendations"] = _age_pending(data["recommendations"])
    data["preferences"] = _recompute_preferences(data["recommendations"])
    _save(data)

    prefs = data["preferences"]
    if not prefs:
        return ""

    reliable = {cat: p for cat, p in prefs.items() if p["reliable"]}
    if not reliable:
        return ""

    lines = []
    high = [(c, p) for c, p in reliable.items() if p["score"] >= 0.7]
    low  = [(c, p) for c, p in reliable.items() if p["score"] <= 0.3]

    if high:
        cats = ", ".join(f"{c} ({int(p['score']*100)}% acted on)" for c, p in sorted(high, key=lambda x: -x[1]["score"]))
        lines.append(f"Owner consistently acts on: {cats}. Prioritise depth and specificity here.")

    if low:
        cats = ", ".join(f"{c} ({int(p['score']*100)}% acted on)" for c, p in sorted(low, key=lambda x: x[1]["score"]))
        lines.append(f"Owner rarely acts on: {cats}. Keep these brief or omit if signals are weak.")

    return "\n".join(lines)


def get_all() -> dict[str, Any]:
    """Return the full memory store (for API inspection)."""
    data = _load()
    data["recommendations"] = _age_pending(data["recommendations"])
    data["preferences"] = _recompute_preferences(data["recommendations"])
    _save(data)
    return data
