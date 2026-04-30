import { motion } from "framer-motion";
import type { CSSProperties } from "react";
import type { DemoPhase } from "../types";

const PHASES: { id: DemoPhase; label: string }[] = [
  { id: "idle", label: "Idle" },
  { id: "signals", label: "1 Signals" },
  { id: "encrypt", label: "2 Encrypt" },
  { id: "communicate", label: "3 Exchange" },
  { id: "aggregate", label: "4 Aggregate" },
  { id: "recommend", label: "5 Feedback" },
  { id: "complete", label: "Done" },
];

type Props = {
  phase: DemoPhase;
  onRun: () => void;
  onReset: () => void;
  onNext: () => void;
  onRefreshData: () => void;
  loadingApi: boolean;
  apiError: string | null;
};

export function PhaseHud({ phase, onRun, onReset, onNext, onRefreshData, loadingApi, apiError }: Props) {
  const idx = PHASES.findIndex((p) => p.id === phase);

  return (
    <header
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        zIndex: 15,
        padding: "14px 24px 12px",
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
        background: "linear-gradient(180deg, rgba(245,224,207,0.98) 0%, rgba(245,224,207,0.85) 70%, transparent 100%)",
        borderBottom: "1px solid rgba(232,212,198,0.5)",
      }}
    >
      <div>
        <div
          style={{
            fontSize: 12,
            fontWeight: 700,
            letterSpacing: "0.16em",
            textTransform: "uppercase",
            color: "#1B3A4B",
          }}
        >
          Pebble · Agentic Marketplace
        </div>
        <div style={{ fontSize: 10, color: "#9AAFBC", marginTop: 3, fontFamily: '"JetBrains Mono", monospace' }}>
          Privacy-preserving multi-agent intelligence · Pebble's view
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        {PHASES.map((p, i) => {
          const active = i === idx;
          const done = i < idx;
          return (
            <div key={p.id} style={{ display: "flex", alignItems: "center", gap: 5 }}>
              {i > 0 && (
                <div style={{ width: 12, height: 1, background: done ? "rgba(27,58,75,0.25)" : "rgba(27,58,75,0.08)" }} />
              )}
              <motion.div
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: active ? "#E8654A" : done ? "#1B3A4B" : "rgba(27,58,75,0.12)",
                  boxShadow: active ? "0 0 10px rgba(232,101,74,0.4)" : "none",
                }}
                animate={{ scale: active ? [1, 1.4, 1] : 1 }}
                transition={{ duration: 1.4, repeat: active ? Infinity : 0 }}
              />
              <span
                style={{
                  fontSize: 9.5,
                  fontFamily: '"JetBrains Mono", monospace',
                  color: active ? "#E8654A" : done ? "#1B3A4B" : "#9AAFBC",
                  fontWeight: active ? 600 : 400,
                }}
              >
                {p.label}
              </span>
            </div>
          );
        })}
      </div>

      <div style={{ display: "flex", gap: 6 }}>
        <button type="button" onClick={onRun} disabled={phase !== "idle" && phase !== "complete"} style={btn(phase === "idle" || phase === "complete")}>
          ▶ Run
        </button>
        <button type="button" onClick={onNext} style={btn(true)}>
          Step →
        </button>
        <button type="button" onClick={onReset} style={btn(true)}>
          Reset
        </button>
        <button type="button" onClick={onRefreshData} disabled={loadingApi} style={btn(!loadingApi)}>
          {loadingApi ? "…" : "Sync"}
        </button>
      </div>

      {apiError && (
        <div style={{ width: "100%", fontSize: 9.5, fontFamily: '"JetBrains Mono", monospace', color: "#9AAFBC" }}>
          api: using bundled sample ({apiError})
        </div>
      )}
    </header>
  );
}

function btn(enabled: boolean): CSSProperties {
  return {
    border: `1px solid ${enabled ? "#E8D4C6" : "rgba(27,58,75,0.06)"}`,
    background: enabled ? "#FFFFFF" : "rgba(253,245,239,0.5)",
    color: enabled ? "#1B3A4B" : "#9AAFBC",
    padding: "6px 12px",
    borderRadius: 6,
    fontSize: 11,
    fontFamily: '"JetBrains Mono", monospace',
    fontWeight: 600,
    letterSpacing: "0.03em",
    cursor: enabled ? "pointer" : "default",
    boxShadow: enabled ? "0 1px 3px rgba(0,0,0,0.06)" : "none",
  };
}
