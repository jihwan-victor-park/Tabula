import { useCallback, useEffect, useRef, useState } from "react";
import type { DemoPhase, PipelineResults } from "../types";
import { SAMPLE_RESULTS } from "../data/sampleResults";

const PHASE_ORDER: DemoPhase[] = [
  "idle",
  "signals",
  "encrypt",
  "communicate",
  "aggregate",
  "recommend",
  "complete",
];

const AUTO_MS: Record<DemoPhase, number> = {
  idle: 0,
  signals: 4000,
  encrypt: 5000,
  communicate: 12000,
  aggregate: 4500,
  recommend: 4500,
  complete: 0,
};

export function useDemoController() {
  const [phase, setPhase] = useState<DemoPhase>("idle");
  const [results, setResults] = useState<PipelineResults>(SAMPLE_RESULTS);
  const [loadingApi, setLoadingApi] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  const clearTimer = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };

  const nextPhase = useCallback(() => {
    const i = PHASE_ORDER.indexOf(phase);
    if (i >= 0 && i < PHASE_ORDER.length - 1) setPhase(PHASE_ORDER[i + 1]!);
  }, [phase]);

  const reset = useCallback(() => {
    clearTimer();
    setPhase("idle");
  }, []);

  const run = useCallback(() => {
    clearTimer();
    setPhase("signals");
  }, []);

  const fetchLiveResults = useCallback(async () => {
    setLoadingApi(true);
    setApiError(null);
    try {
      const res = await fetch("/api/results");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const trends = data.market_trends || data.trends;
      if (trends?.length) {
        setResults({
          cycle_id: data.cycle_id,
          scenario: data.scenario,
          generated_at: data.generated_at,
          market_trends: trends,
        });
      } else {
        throw new Error(data.hint || "empty");
      }
    } catch (e) {
      setApiError(e instanceof Error ? e.message : "unavailable");
      setResults(SAMPLE_RESULTS);
    } finally {
      setLoadingApi(false);
    }
  }, []);

  useEffect(() => {
    void fetchLiveResults();
  }, [fetchLiveResults]);

  useEffect(() => {
    clearTimer();
    const ms = AUTO_MS[phase];
    if (!ms) return;
    timer.current = window.setTimeout(nextPhase, ms);
    return clearTimer;
  }, [phase, nextPhase]);

  return { phase, results, loadingApi, apiError, nextPhase, reset, run, fetchLiveResults };
}
