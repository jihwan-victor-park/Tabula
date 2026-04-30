"""
Reads results.json from the agentic debate pipeline and produces
a compact debate_summary.json for the finalized AI to consume.
"""

import json
from collections import Counter
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"
RESULTS_PATH = OUTPUT_DIR / "results.json"
SUMMARY_PATH = OUTPUT_DIR / "debate_summary.json"


def generate_summary() -> dict:
    with open(RESULTS_PATH) as f:
        results = json.load(f)

    trends = results["market_trends"]
    stores = results.get("store_results", [])

    # --- categorise trends by direction ---
    rising = sorted(
        [t for t in trends if t["direction"] == "rising"],
        key=lambda t: t["strength"],
        reverse=True,
    )
    falling = sorted(
        [t for t in trends if t["direction"] == "falling"],
        key=lambda t: t["strength"],
        reverse=True,
    )
    stable = [t for t in trends if t["direction"] == "stable"]

    # --- aggregate recommendations across all stores ---
    all_recs = []
    for store in stores:
        for rec in store.get("recommendations", []):
            all_recs.append(rec)

    # find the most common (action, category) pairs weighted by confidence
    action_scores: dict[tuple[str, str], float] = {}
    for rec in all_recs:
        key = (rec["action"], rec["category"])
        action_scores[key] = action_scores.get(key, 0) + rec["confidence"]

    top_actions = sorted(action_scores.items(), key=lambda x: x[1], reverse=True)

    key_recommendations = [
        {
            "action": action,
            "category": category,
            "confidence": round(score / sum(1 for r in all_recs if r["action"] == action and r["category"] == category), 2),
            "store_count": sum(1 for r in all_recs if r["action"] == action and r["category"] == category),
        }
        for (action, category), score in top_actions[:8]
    ]

    # --- build natural-language summary ---
    rising_names = [t["category"].replace("_", " ") for t in rising]
    falling_names = [t["category"].replace("_", " ") for t in falling]

    parts = []
    parts.append(
        f"Multi-agent debate across {len(stores)} stores analysed {len(trends)} product categories."
    )
    if rising_names:
        parts.append(f"Rising categories: {', '.join(rising_names)}.")
    if falling_names:
        parts.append(f"Declining categories: {', '.join(falling_names)}.")
    if stable:
        parts.append(f"{len(stable)} categories remain stable.")

    avg_confidence = round(
        sum(r["confidence"] for r in all_recs) / len(all_recs), 2
    ) if all_recs else 0

    # --- include verification data if present ---
    verification = results.get("verification")
    verification_summary = None
    if verification:
        verification_summary = {
            "chain": verification.get("chain", "solana"),
            "network": verification.get("network", "devnet"),
            "signals_on_chain": verification.get("signals_on_chain", False),
            "signal_count": verification.get("signal_count", 0),
            "summary_on_chain": verification.get("summary_on_chain", False),
            "all_verified": verification.get("all_verified", False),
        }

    summary = {
        "source": "market_debate",
        "generated_at": results.get("generated_at"),
        "cycle_id": results.get("cycle_id"),
        "ai_model": "hermes-4-70b",
        "ai_provider": "nous_research",
        "summary": " ".join(parts),
        "store_count": len(stores),
        "category_count": len(trends),
        "top_rising": [
            {"category": t["category"], "strength": t["strength"], "consensus": t["consensus"]}
            for t in rising
        ],
        "top_falling": [
            {"category": t["category"], "strength": t["strength"], "consensus": t["consensus"]}
            for t in falling
        ],
        "average_confidence": avg_confidence,
        "key_recommendations": key_recommendations,
        "verification": verification_summary,
    }

    with open(SUMMARY_PATH, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"Wrote debate summary to {SUMMARY_PATH}")
    return summary


if __name__ == "__main__":
    s = generate_summary()
    print(json.dumps(s, indent=2))
