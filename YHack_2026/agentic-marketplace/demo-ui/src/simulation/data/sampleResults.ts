import type { PipelineResults } from "../types";

export const SAMPLE_RESULTS: PipelineResults = {
  cycle_id: "demo_cycle",
  scenario: "holiday_rush",
  generated_at: "2026-03-28T12:00:00Z",
  market_trends: [
    { category: "lego_sets", direction: "rising", strength: 0.82, signal_count: 5, consensus: "strong" },
    { category: "video_games", direction: "rising", strength: 0.78, signal_count: 5, consensus: "moderate" },
    { category: "action_figures", direction: "rising", strength: 0.71, signal_count: 5, consensus: "moderate" },
    { category: "board_games", direction: "rising", strength: 0.65, signal_count: 5, consensus: "moderate" },
    { category: "craft_kits", direction: "rising", strength: 0.58, signal_count: 5, consensus: "mixed" },
    { category: "educational_toys", direction: "rising", strength: 0.55, signal_count: 5, consensus: "mixed" },
    { category: "puzzles", direction: "stable", strength: 0.52, signal_count: 5, consensus: "mixed" },
    { category: "books_comics", direction: "stable", strength: 0.50, signal_count: 5, consensus: "strong" },
    { category: "dolls", direction: "stable", strength: 0.48, signal_count: 4, consensus: "mixed" },
    { category: "outdoor_toys", direction: "falling", strength: 0.44, signal_count: 5, consensus: "moderate" },
  ],
};
