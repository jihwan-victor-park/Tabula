import { motion, AnimatePresence } from "framer-motion";
import { useEffect, useState } from "react";
import type { DemoPhase } from "../types";
import type { StoreDef } from "../data/stores";
import type { Point } from "../hooks/useLayout";

type Props = {
  store: StoreDef;
  pos: Point;
  phase: DemoPhase;
  index: number;
  isPebble: boolean;
  onSelect: () => void;
};

const CIPHER = "ΣΔΩλμκ∂∇∈∅→·≈≡αβγθψξζ0123456789abcdef";

const ANON_IDS = ["#7f3a", "#a31d", "#1db8", "#b84e", "#4ec2", "#c29a", "#9a0f"];

const ANON_STATUS: Record<DemoPhase, string> = {
  idle: "",
  signals: "analyzing local data…",
  encrypt: "encrypting identity…",
  communicate: "sharing encrypted intel…",
  aggregate: "submitting to model…",
  recommend: "receiving guidance…",
  complete: "cycle complete",
};

const EASE: [number, number, number, number] = [0.33, 1, 0.68, 1];

function ScrambleText({ from, to, active, delay = 0, speed = 28 }: { from: string; to: string; active: boolean; delay?: number; speed?: number }) {
  const [display, setDisplay] = useState(from);

  useEffect(() => {
    if (!active) { setDisplay(from); return; }
    let interval: number;
    const timeout = window.setTimeout(() => {
      let frame = 0;
      const len = to.length;
      const total = len * 2;
      interval = window.setInterval(() => {
        frame++;
        const settled = Math.floor((frame / total) * len);
        let r = "";
        for (let i = 0; i < len; i++) {
          r += to[i] === " " ? " " : i < settled ? to[i] : CIPHER[Math.floor(Math.random() * CIPHER.length)];
        }
        setDisplay(r);
        if (frame >= total) { clearInterval(interval); setDisplay(to); }
      }, speed);
    }, delay);
    return () => { clearTimeout(timeout); clearInterval(interval); };
  }, [from, to, active, delay, speed]);

  return <>{display}</>;
}

function EncryptedFormulas({ signals, encrypted, active, delay }: { signals: string[]; encrypted: string[]; active: boolean; delay: number }) {
  return (
    <AnimatePresence>
      {active && (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.4, delay: delay * 0.001 }}
          style={{
            marginTop: 6,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 3,
            whiteSpace: "nowrap",
          }}
        >
          {signals.map((sig, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.2, delay: delay * 0.001 + i * 0.18 }}
              style={{
                fontSize: 8,
                fontFamily: '"JetBrains Mono", monospace',
                fontWeight: 600,
                letterSpacing: "0.02em",
                color: "#1B3A4B",
                padding: "1px 5px",
                borderRadius: 3,
                background: "rgba(255,255,255,0.55)",
                border: "1px solid rgba(232,212,198,0.45)",
                lineHeight: 1.3,
              }}
            >
              <ScrambleText from={sig} to={encrypted[i] ?? sig} active={active} delay={delay + i * 200} speed={14} />
            </motion.div>
          ))}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function StoreNode({ store, pos, phase, index, isPebble, onSelect }: Props) {
  const isMapView = phase === "idle" || phase === "signals";
  const isScrambling = phase === "encrypt";

  if (isPebble) return <PebbleNode store={store} pos={pos} phase={phase} onSelect={onSelect} />;
  return <AnonNode store={store} pos={pos} phase={phase} index={index} isMapView={isMapView} isScrambling={isScrambling} />;
}

function AnonNode({
  store, pos, phase, index, isMapView, isScrambling,
}: {
  store: StoreDef; pos: Point; phase: DemoPhase; index: number; isMapView: boolean; isScrambling: boolean;
}) {
  const anonId = `Agent ${ANON_IDS[index - 1] ?? "#??"}`;
  const isActive = phase !== "idle";
  const isCircle = !isMapView && !isScrambling;

  const size = isMapView ? 110 : 130;

  return (
    <motion.div
      initial={{ left: pos.x - size / 2, top: pos.y - size / 2, opacity: 0, scale: 0.75 }}
      animate={{ left: pos.x - size / 2, top: pos.y - size / 2, opacity: 1, scale: 1 }}
      transition={{
        left: { duration: 1.8, ease: EASE },
        top: { duration: 1.8, ease: EASE },
        opacity: { duration: 0.5, delay: index * 0.04 },
        scale: { duration: 0.5, delay: index * 0.04 },
      }}
      style={{
        position: "fixed",
        zIndex: 5,
        textAlign: "center",
        pointerEvents: "none",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
      }}
    >
      <div
        style={{
          width: size,
          height: size,
          borderRadius: "50%",
          border: isScrambling
            ? "1.5px solid rgba(232,101,74,0.30)"
            : isCircle ? "1px solid rgba(232,212,198,0.6)" : "1px solid transparent",
          background: isScrambling
            ? "rgba(255,255,255,0.92)"
            : isCircle ? "rgba(255,255,255,0.70)" : "transparent",
          boxShadow: isScrambling
            ? "0 0 36px rgba(232,101,74,0.10), 0 4px 18px rgba(0,0,0,0.06)"
            : isCircle ? "0 4px 14px rgba(0,0,0,0.06)" : "none",
          transition: "border 0.6s, background 0.6s, box-shadow 0.6s",
          display: "flex",
          flexDirection: "column" as const,
          alignItems: "center",
          justifyContent: "center",
          overflow: "hidden",
          flexShrink: 0,
        }}
      >
        {isMapView && (
          <div
            style={{
              width: 14,
              height: 14,
              borderRadius: 2,
              transform: "rotate(45deg)",
              position: "relative",
              flexShrink: 0,
              border: "1.5px solid rgba(27,58,75,0.35)",
              marginBottom: 4,
            }}
          >
            <div
              style={{
                position: "absolute",
                inset: 2,
                background: "#1B3A4B",
              }}
            />
          </div>
        )}

        {isScrambling && (
          <div style={{ fontSize: 16, lineHeight: 1, opacity: 0.7 }}>🔒</div>
        )}

        <div
          style={{
            marginTop: isScrambling ? 4 : 0,
            fontSize: 15,
            fontFamily: '"JetBrains Mono", monospace',
            fontWeight: 700,
            letterSpacing: "0.03em",
            lineHeight: 1.2,
            color: isScrambling
              ? "#E8654A"
              : isMapView ? "#1B3A4B" : "#5C7A8A",
            transition: "color 0.6s, font-size 0.6s",
          }}
        >
          {isScrambling
            ? <ScrambleText from={store.name} to={anonId} active delay={index * 180} speed={22} />
            : isMapView ? store.name : anonId}
        </div>

        {isScrambling && (
          <div
            style={{
              marginTop: 3,
              fontSize: 10,
              fontFamily: '"JetBrains Mono", monospace',
              fontWeight: 700,
              color: "#E8654A",
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              opacity: 0.7,
            }}
          >
            encrypting
          </div>
        )}

        {isMapView && (
          <div
            style={{
              marginTop: 2,
              fontSize: 11,
              fontFamily: '"JetBrains Mono", monospace',
              fontWeight: 600,
              color: "#9AAFBC",
            }}
          >
            {store.area}
          </div>
        )}

        {isActive && isCircle && (
          <div
            style={{
              marginTop: 3,
              fontSize: 11,
              fontFamily: '"JetBrains Mono", monospace',
              fontWeight: 600,
              color: "#9AAFBC",
              lineHeight: 1.25,
              letterSpacing: "0.02em",
              maxWidth: 100,
            }}
          >
            {ANON_STATUS[phase]}
          </div>
        )}
      </div>

      <EncryptedFormulas
        signals={store.signalLines}
        encrypted={store.encryptedLines}
        active={isScrambling}
        delay={index * 300}
      />
    </motion.div>
  );
}

function PebbleNode({
  store, pos, phase, onSelect,
}: {
  store: StoreDef; pos: Point; phase: DemoPhase; onSelect: () => void;
}) {
  const isMapView = phase === "idle" || phase === "signals";
  const isScrambling = phase === "encrypt";
  const isCircle = !isMapView && !isScrambling;
  const canClick = phase === "recommend" || phase === "complete";
  const isActive = phase !== "idle";

  const PEBBLE_STATUS: Record<DemoPhase, string> = {
    idle: "",
    signals: "analyzing local data…",
    encrypt: "encrypting identity…",
    communicate: "sharing encrypted intel…",
    aggregate: "submitting to model…",
    recommend: "receiving guidance…",
    complete: "cycle complete",
  };

  const size = isMapView ? 130 : 150;

  return (
    <motion.div
      initial={{ left: pos.x - size / 2, top: pos.y - size / 2, opacity: 0, scale: 0.85 }}
      animate={{ left: pos.x - size / 2, top: pos.y - size / 2, opacity: 1, scale: 1 }}
      transition={{
        left: { duration: 1.8, ease: EASE },
        top: { duration: 1.8, ease: EASE },
        opacity: { duration: 0.5 },
        scale: { duration: 0.5 },
      }}
      style={{
        position: "fixed",
        zIndex: 7,
        textAlign: "center",
        pointerEvents: canClick ? "auto" : "none",
        cursor: canClick ? "pointer" : "default",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
      }}
      onClick={() => canClick && onSelect()}
    >
      <div
        style={{
          width: size,
          height: size,
          borderRadius: "50%",
          border: isScrambling
            ? "1.5px solid rgba(232,101,74,0.40)"
            : isCircle ? "1.5px solid rgba(232,101,74,0.25)" : "1.5px solid rgba(27,58,75,0.15)",
          background: isScrambling
            ? "rgba(255,255,255,0.96)"
            : isCircle ? "rgba(255,255,255,0.85)" : "rgba(255,255,255,0.80)",
          boxShadow: isScrambling
            ? "0 0 40px rgba(232,101,74,0.12), 0 4px 20px rgba(0,0,0,0.08)"
            : "0 4px 18px rgba(0,0,0,0.08)",
          transition: "border 0.6s, background 0.6s, box-shadow 0.6s",
          display: "flex",
          flexDirection: "column" as const,
          alignItems: "center",
          justifyContent: "center",
          overflow: "hidden",
          flexShrink: 0,
        }}
      >
        {isMapView && (
          <div
            style={{
              width: 16,
              height: 16,
              borderRadius: 2,
              transform: "rotate(45deg)",
              position: "relative",
              flexShrink: 0,
              border: "1.5px solid rgba(232,101,74,0.50)",
              marginBottom: 4,
              boxShadow: "0 0 10px rgba(232,101,74,0.12)",
            }}
          >
            <div
              style={{
                position: "absolute",
                inset: 2,
                background: "#E8654A",
              }}
            />
          </div>
        )}

        {isScrambling && (
          <div style={{ fontSize: 18, lineHeight: 1, opacity: 0.7 }}>🔒</div>
        )}

        <div
          style={{
            marginTop: isScrambling ? 4 : 0,
            fontSize: 17,
            fontFamily: '"JetBrains Mono", monospace',
            fontWeight: 800,
            letterSpacing: "0.03em",
            lineHeight: 1.2,
            color: "#E8654A",
            transition: "color 0.6s",
          }}
        >
          Pebble
        </div>

        <div
          style={{
            marginTop: 2,
            fontSize: 11,
            fontFamily: '"JetBrains Mono", monospace',
            fontWeight: 700,
            color: "#5C7A8A",
            letterSpacing: "0.06em",
            textTransform: "uppercase",
          }}
        >
          your agent
        </div>

        {isScrambling && (
          <div
            style={{
              marginTop: 3,
              fontSize: 10,
              fontFamily: '"JetBrains Mono", monospace',
              fontWeight: 700,
              color: "#E8654A",
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              opacity: 0.7,
            }}
          >
            encrypting
          </div>
        )}

        {isMapView && (
          <div
            style={{
              marginTop: 2,
              fontSize: 11,
              fontFamily: '"JetBrains Mono", monospace',
              fontWeight: 600,
              color: "#9AAFBC",
            }}
          >
            {store.area}
          </div>
        )}

        {isActive && isCircle && (
          <div
            style={{
              marginTop: 3,
              fontSize: 11,
              fontFamily: '"JetBrains Mono", monospace',
              fontWeight: 600,
              color: "#5C7A8A",
              lineHeight: 1.25,
              letterSpacing: "0.02em",
              maxWidth: 110,
            }}
          >
            {PEBBLE_STATUS[phase]}
          </div>
        )}

        {canClick && (
          <div
            style={{
              marginTop: 4,
              fontSize: 10,
              fontFamily: '"JetBrains Mono", monospace',
              fontWeight: 700,
              color: "#E8654A",
              opacity: 0.7,
            }}
          >
            click for plan
          </div>
        )}
      </div>

      <EncryptedFormulas
        signals={store.signalLines}
        encrypted={store.encryptedLines}
        active={isScrambling}
        delay={0}
      />
    </motion.div>
  );
}
