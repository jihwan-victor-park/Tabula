import { motion, AnimatePresence } from "framer-motion";
import { useEffect, useState } from "react";
import type { DemoPhase } from "../types";
import type { Point } from "../hooks/useLayout";

type Props = { center: Point; phase: DemoPhase };

const PROC_LABELS = [
  "Aggregating encrypted submissions from all agents…",
  "Stripping identity metadata from payloads…",
  "Applying differential privacy constraints…",
  "Synthesizing generalized market signals…",
  "Preparing anonymous guidance for distribution…",
];

export function AggregationCore({ center, phase }: Props) {
  const visible = phase !== "idle" && phase !== "signals";
  const receiving = phase === "communicate";
  const processing = phase === "aggregate";
  const done = phase === "recommend" || phase === "complete";

  const [labelIdx, setLabelIdx] = useState(0);
  useEffect(() => {
    if (!processing) { setLabelIdx(0); return; }
    const id = window.setInterval(() => setLabelIdx((i) => (i + 1) % PROC_LABELS.length), 750);
    return () => window.clearInterval(id);
  }, [processing]);

  const W = 280;
  const H = 230;
  const CX = W / 2;
  const CY = H / 2;

  return (
    <motion.div
      style={{
        position: "fixed",
        left: center.x - W / 2,
        top: center.y - H / 2,
        width: W,
        height: H,
        zIndex: 6,
        pointerEvents: "none",
      }}
      initial={{ opacity: 0 }}
      animate={{ opacity: visible ? 1 : 0 }}
      transition={{ duration: 1.0, delay: visible ? 0.8 : 0 }}
    >
      {/* Radial blur background */}
      <div
        style={{
          position: "absolute", left: "50%", top: "50%",
          width: 380, height: 260,
          transform: "translate(-50%, -50%)",
          borderRadius: 999,
          background: "radial-gradient(ellipse at center, rgba(245,224,207,0.96) 0%, rgba(245,224,207,0.80) 40%, rgba(245,224,207,0.15) 70%, transparent 100%)",
          filter: "blur(14px)",
          zIndex: -1,
        }}
      />

      {/* SVG rings + labels */}
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} style={{ overflow: "visible", display: "block" }}>
        <circle cx={CX} cy={CY} r={100} fill="none" stroke="rgba(27,58,75,0.06)" strokeWidth={0.5} strokeDasharray="6 14">
          <animateTransform attributeName="transform" type="rotate" from={`360 ${CX} ${CY}`} to={`0 ${CX} ${CY}`} dur="36s" repeatCount="indefinite" />
        </circle>
        <circle cx={CX} cy={CY} r={72} fill="none" stroke="rgba(27,58,75,0.10)" strokeWidth={0.6} strokeDasharray="4 10">
          <animateTransform attributeName="transform" type="rotate" from={`0 ${CX} ${CY}`} to={`360 ${CX} ${CY}`} dur="22s" repeatCount="indefinite" />
        </circle>
        <motion.polygon
          points={`${CX},${CY - 88} ${CX + 82},${CY - 49} ${CX + 82},${CY + 49} ${CX},${CY + 88} ${CX - 82},${CY + 49} ${CX - 82},${CY - 49}`}
          fill={receiving || processing || done ? "rgba(27,58,75,0.03)" : "none"}
          stroke="rgba(27,58,75,0.12)"
          strokeWidth={0.7}
          animate={{ strokeOpacity: processing ? [0.08, 0.30, 0.08] : receiving ? [0.06, 0.18, 0.06] : done ? 0.20 : 0.08 }}
          transition={{ duration: 2, repeat: processing || receiving ? Infinity : 0 }}
        />
        <circle cx={CX} cy={CY} r={44} fill="none" stroke="rgba(27,58,75,0.14)" strokeWidth={0.7} strokeDasharray="3 8">
          <animateTransform attributeName="transform" type="rotate" from={`0 ${CX} ${CY}`} to={`-360 ${CX} ${CY}`} dur="14s" repeatCount="indefinite" />
        </circle>

        <text x={CX} y={CY - 16} textAnchor="middle" fill="#1B3A4B" fontSize={16} fontFamily="'JetBrains Mono', monospace" fontWeight={700} letterSpacing="0.16em" opacity={0.85}>
          AGGREGATED
        </text>
        <text x={CX} y={CY + 5} textAnchor="middle" fill="#1B3A4B" fontSize={15} fontFamily="'JetBrains Mono', monospace" fontWeight={700} letterSpacing="0.14em" opacity={0.65}>
          MODEL
        </text>
        <text x={CX} y={CY + 24} textAnchor="middle" fill="#5C7A8A" fontSize={11} fontFamily="'JetBrains Mono', monospace" fontWeight={600} letterSpacing="0.10em">
          ANONYMOUS INTELLIGENCE
        </text>
      </svg>

      {/* Status text below */}
      <div style={{
        position: "absolute",
        top: H + 8,
        left: "50%",
        transform: "translateX(-50%)",
        width: 420,
        textAlign: "center",
        height: 28,
        overflow: "hidden",
      }}>
        <AnimatePresence mode="wait">
          {processing && (
            <motion.div key={labelIdx} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.25 }}
              style={{ fontSize: 13, fontWeight: 600, fontFamily: '"JetBrains Mono", monospace', color: "#5C7A8A" }}>
              {PROC_LABELS[labelIdx]}
            </motion.div>
          )}
          {receiving && (
            <motion.div key="receiving" initial={{ opacity: 0 }} animate={{ opacity: 0.6 }}
              style={{ fontSize: 13, fontWeight: 600, fontFamily: '"JetBrains Mono", monospace', color: "#5C7A8A" }}>
              Monitoring encrypted agent exchange…
            </motion.div>
          )}
          {done && (
            <motion.div key="done" initial={{ opacity: 0 }} animate={{ opacity: 1 }}
              style={{ fontSize: 13, fontWeight: 600, fontFamily: '"JetBrains Mono", monospace', color: "#1B3A4B" }}>
              Synthesis complete · private feedback open
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}
