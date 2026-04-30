import { motion, AnimatePresence } from "framer-motion";
import { useEffect, useMemo, useRef, useState } from "react";
import type { DemoPhase } from "../types";
import type { StoreDef } from "../data/stores";
import type { Point } from "../hooks/useLayout";

type Particle = { id: number; from: Point; to: Point; color: string; dur: number };

type Props = {
  circlePositions: Point[];
  center: Point;
  stores: StoreDef[];
  phase: DemoPhase;
  w: number;
  h: number;
};

const ANON_IDS = ["College Deli", "#7f3a", "#a31d", "#1db8", "#b84e", "#4ec2", "#c29a", "#9a0f"];
const MSG_DURATION = 1800;

const CHAT_MSGS: { from: number; to: number; text: string; at: number }[] = [
  { from: 0, to: 3, text: "seeing strong demand signals this cycle", at: 400 },
  { from: 3, to: 0, text: "same — been rising consistently all week", at: 1800 },
  { from: 5, to: 7, text: "my encrypted analysis shows +14% velocity", at: 3000 },
  { from: 7, to: 5, text: "interesting — my model is converging too", at: 4200 },
  { from: 1, to: 4, text: "inventory pressure building on fast movers", at: 5200 },
  { from: 4, to: 1, text: "should we flag supply chain risk?", at: 6200 },
  { from: 0, to: 2, text: "weekend forecast predicts 1.2× baseline", at: 7200 },
  { from: 2, to: 6, text: "lead times extending — flagging upstream", at: 8200 },
  { from: 6, to: 3, text: "agreed — submitting consolidated update", at: 9200 },
  { from: 0, to: 5, text: "aligning consensus before aggregation", at: 10200 },
];

const ALL_CROSS_PAIRS: [number, number][] = [
  [0, 2], [0, 3], [0, 5], [0, 7],
  [1, 3], [1, 4], [1, 5], [1, 6],
  [2, 4], [2, 5], [2, 6],
  [3, 5], [3, 7],
  [4, 6],
  [5, 7],
];

function pairKey(a: number, b: number) {
  return a < b ? `${a}-${b}` : `${b}-${a}`;
}

export function SecureTunnels({ circlePositions: cPos, center, stores, phase, w, h }: Props) {
  const [elapsed, setElapsed] = useState(0);
  const [particles, setParticles] = useState<Particle[]>([]);
  const nextId = useRef(0);

  useEffect(() => {
    if (phase !== "communicate") { setElapsed(0); return; }
    const t0 = Date.now();
    const id = window.setInterval(() => setElapsed(Date.now() - t0), 80);
    return () => window.clearInterval(id);
  }, [phase]);

  const activeMessages = useMemo(
    () => phase === "communicate"
      ? CHAT_MSGS.filter((m) => elapsed >= m.at && elapsed < m.at + MSG_DURATION)
      : [],
    [phase, elapsed],
  );
  const activePairSet = useMemo(
    () => new Set(activeMessages.map((m) => pairKey(m.from, m.to))),
    [activeMessages],
  );
  const isActive = (a: number, b: number) => activePairSet.has(pairKey(a, b));

  const showCross = phase === "communicate";
  const showRadial = phase === "aggregate" || phase === "recommend" || phase === "complete";
  const faintMesh = phase !== "idle" && phase !== "signals";

  useEffect(() => {
    if (phase === "communicate") {
      let cursor = 0;
      const id = window.setInterval(() => {
        if (activeMessages.length === 0) return;
        const msg = activeMessages[cursor % activeMessages.length]!;
        const reverse = cursor % 2 === 1;
        const from = cPos[reverse ? msg.to : msg.from]!;
        const to = cPos[reverse ? msg.from : msg.to]!;
        nextId.current++;
        const involvesPebble = msg.from === 0 || msg.to === 0;
        setParticles((prev) => [
          ...prev.slice(-60),
          { id: nextId.current, from, to, color: involvesPebble ? "rgba(232,101,74,0.85)" : "rgba(27,58,75,0.50)", dur: 0.85 },
        ]);
        cursor++;
      }, 130);
      return () => window.clearInterval(id);
    }

    if (phase === "aggregate") {
      let cursor = 0;
      const id = window.setInterval(() => {
        const idx = cursor % stores.length;
        nextId.current++;
        setParticles((prev) => [
          ...prev.slice(-50),
          { id: nextId.current, from: cPos[idx]!, to: center, color: idx === 0 ? "rgba(232,101,74,0.80)" : "rgba(27,58,75,0.40)", dur: 1.0 },
        ]);
        cursor++;
      }, 175);
      return () => window.clearInterval(id);
    }

    if (phase === "recommend") {
      let cursor = 0;
      const id = window.setInterval(() => {
        const idx = cursor % stores.length;
        nextId.current++;
        setParticles((prev) => [
          ...prev.slice(-35),
          { id: nextId.current, from: center, to: cPos[idx]!, color: idx === 0 ? "#E8654A" : "rgba(27,58,75,0.18)", dur: 1.0 },
        ]);
        cursor++;
      }, 210);
      return () => window.clearInterval(id);
    }

    setParticles([]);
  }, [phase, activeMessages, cPos, center, stores.length]);

  if (!faintMesh && !showCross && !showRadial && particles.length === 0 && activeMessages.length === 0) return null;

  return (
    <>
      <svg viewBox={`0 0 ${w} ${h}`} style={{ position: "fixed", inset: 0, width: "100%", height: "100%", pointerEvents: "none", zIndex: 2 }}>
        <defs>
          <filter id="glow">
            <feGaussianBlur stdDeviation="2.5" result="b" />
            <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>

        {/* Cross-connections */}
        {ALL_CROSS_PAIRS.map(([a, b]) => {
          const from = cPos[a]!;
          const to = cPos[b]!;
          const active = showCross && isActive(a, b);
          const involvesPebble = a === 0 || b === 0;
          return (
            <motion.line
              key={`c-${a}-${b}`}
              x1={from.x} y1={from.y} x2={to.x} y2={to.y}
              stroke={involvesPebble ? "rgba(232,101,74,0.35)" : "rgba(27,58,75,0.18)"}
              strokeWidth={active ? (involvesPebble ? 1.4 : 1.0) : 0.4}
              strokeDasharray={active ? "4 8" : "2 14"}
              filter="url(#glow)"
              animate={{ opacity: active ? (involvesPebble ? 0.65 : 0.40) : faintMesh ? 0.08 : 0 }}
              transition={{ duration: 0.35 }}
            />
          );
        })}

        {/* Radial lines to center */}
        {cPos.map((store, i) => (
          <motion.line
            key={`r-${i}`}
            x1={store.x} y1={store.y} x2={center.x} y2={center.y}
            stroke={i === 0 ? "rgba(232,101,74,0.30)" : "rgba(27,58,75,0.12)"}
            strokeWidth={i === 0 ? 1.3 : 0.7}
            strokeDasharray="4 10"
            filter="url(#glow)"
            animate={{ opacity: showRadial ? (i === 0 ? 0.50 : 0.20) : 0 }}
            transition={{ duration: 0.5, delay: showRadial ? i * 0.06 : 0 }}
          />
        ))}
      </svg>

      {/* Chat bubbles */}
      <AnimatePresence>
        {activeMessages.map((msg, idx) => {
          const from = cPos[msg.from]!;
          const to = cPos[msg.to]!;
          const mx = from.x * 0.62 + to.x * 0.38;
          const my = from.y * 0.62 + to.y * 0.38 - 12;
          const sender = ANON_IDS[msg.from] ?? "??";
          const involvesPebble = msg.from === 0 || msg.to === 0;
          return (
            <motion.div
              key={`msg-${msg.at}-${idx}`}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.3 }}
              style={{
                position: "fixed",
                left: mx,
                top: my,
                transform: "translateX(-50%)",
                padding: "3px 8px",
                borderRadius: 999,
                background: involvesPebble
                  ? "rgba(255,255,255,0.55)"
                  : "rgba(253,245,239,0.45)",
                border: involvesPebble
                  ? "1px solid rgba(232,101,74,0.18)"
                  : "1px solid rgba(232,212,198,0.35)",
                boxShadow: "0 2px 8px rgba(0,0,0,0.04)",
                backdropFilter: "blur(6px)",
                zIndex: 9,
                pointerEvents: "none",
                whiteSpace: "nowrap",
              }}
            >
              <span
                style={{
                  fontSize: 10,
                  fontFamily: '"JetBrains Mono", monospace',
                  color: msg.from === 0 ? "#E8654A" : "#5C7A8A",
                  fontWeight: 700,
                  marginRight: 4,
                }}
              >
                {sender}
              </span>
              <span
                style={{
                  fontSize: 10,
                  fontFamily: '"JetBrains Mono", monospace',
                  fontWeight: 600,
                  color: involvesPebble ? "#1B3A4B" : "#5C7A8A",
                }}
              >
                {msg.text}
              </span>
            </motion.div>
          );
        })}
      </AnimatePresence>

      {/* Particles */}
      {particles.map((p) => {
        const steps = 16;
        const xArr = Array.from({ length: steps + 1 }, (_, j) => p.from.x + (p.to.x - p.from.x) * (j / steps));
        const yArr = Array.from({ length: steps + 1 }, (_, j) => p.from.y + (p.to.y - p.from.y) * (j / steps));
        const opArr = Array.from({ length: steps + 1 }, (_, j) => {
          const t = j / steps;
          if (t < 0.1) return t / 0.1;
          if (t > 0.85) return (1 - t) / 0.15;
          return 1;
        });
        return (
          <motion.div
            key={p.id}
            style={{
              position: "fixed", left: 0, top: 0,
              width: 7, height: 3, marginLeft: -3.5, marginTop: -1.5,
              borderRadius: 999, background: p.color,
              boxShadow: `0 0 8px ${p.color}`,
              zIndex: 4, pointerEvents: "none",
            }}
            animate={{ x: xArr, y: yArr, opacity: opArr }}
            transition={{ duration: p.dur, ease: "linear" }}
          />
        );
      })}
    </>
  );
}
