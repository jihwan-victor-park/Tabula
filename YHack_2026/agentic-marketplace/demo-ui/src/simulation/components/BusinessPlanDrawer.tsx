import { motion } from "framer-motion";
import type { StoreDef } from "../data/stores";

type Props = {
  business: StoreDef | null;
  onClose: () => void;
};

export function BusinessPlanDrawer({ business, onClose }: Props) {
  if (!business) return null;

  return (
    <motion.aside
      initial={{ x: 360, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      exit={{ x: 360, opacity: 0 }}
      transition={{ type: "spring", damping: 28, stiffness: 260 }}
      style={{
        position: "fixed",
        right: 18,
        top: 86,
        bottom: 18,
        width: 304,
        zIndex: 18,
        borderRadius: 12,
        background: "rgba(255,255,255,0.97)",
        border: "1px solid #E8D4C6",
        boxShadow: "0 18px 42px rgba(0,0,0,0.10)",
        backdropFilter: "blur(16px)",
        padding: "16px 16px 18px",
        overflow: "auto",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
        <div>
          <div
            style={{
              fontSize: 10,
              fontFamily: '"JetBrains Mono", monospace',
              letterSpacing: "0.14em",
              textTransform: "uppercase",
              color: "#9AAFBC",
            }}
          >
            private company plan
          </div>
          <h3 style={{ margin: "7px 0 0", fontSize: 18, color: "#1B3A4B" }}>{business.name}</h3>
          <div
            style={{
              marginTop: 5,
              fontSize: 10,
              fontFamily: '"JetBrains Mono", monospace',
              color: "#5C7A8A",
            }}
          >
            {business.area} · {business.specialty}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          style={{
            border: "1px solid #E8D4C6",
            background: "#FDF5EF",
            color: "#1B3A4B",
            borderRadius: 7,
            padding: "5px 8px",
            fontSize: 10,
            cursor: "pointer",
          }}
        >
          Close
        </button>
      </div>

      <div
        style={{
          marginTop: 16,
          padding: "10px 12px",
          borderRadius: 9,
          background: "#FDF5EF",
          border: "1px solid #E8D4C6",
        }}
      >
        <div
          style={{
            fontSize: 9,
            fontFamily: '"JetBrains Mono", monospace',
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            color: "#E8654A",
            marginBottom: 7,
          }}
        >
          Recommended action
        </div>
        <div style={{ fontSize: 13, lineHeight: 1.45, color: "#1B3A4B" }}>{business.recommendation}</div>
      </div>

      <div
        style={{
          marginTop: 16,
          fontSize: 9,
          fontFamily: '"JetBrains Mono", monospace',
          letterSpacing: "0.1em",
          textTransform: "uppercase",
          color: "#9AAFBC",
        }}
      >
        Local signals used
      </div>
      <div style={{ marginTop: 8, display: "grid", gap: 6 }}>
        {business.signalLines.map((line) => (
          <div
            key={line}
            style={{
              padding: "8px 9px",
              borderRadius: 7,
              background: "#FDF5EF",
              border: "1px solid #E8D4C6",
              fontSize: 11,
              color: "#5C7A8A",
            }}
          >
            {line}
          </div>
        ))}
      </div>

      <div
        style={{
          marginTop: 16,
          fontSize: 9,
          fontFamily: '"JetBrains Mono", monospace',
          letterSpacing: "0.1em",
          textTransform: "uppercase",
          color: "#9AAFBC",
        }}
      >
        Detailed plan summary
      </div>
      <div style={{ marginTop: 8, display: "grid", gap: 8 }}>
        {business.planSummary.map((line, idx) => (
          <div
            key={line}
            style={{
              display: "grid",
              gridTemplateColumns: "24px 1fr",
              gap: 9,
              alignItems: "start",
              padding: "8px 6px 8px 0",
              borderBottom: idx === business.planSummary.length - 1 ? "none" : "1px solid #E8D4C6",
            }}
          >
            <div
              style={{
                width: 24,
                height: 24,
                borderRadius: "50%",
                border: "1px solid #E8D4C6",
                display: "grid",
                placeItems: "center",
                color: "#E8654A",
                fontSize: 10,
                fontFamily: '"JetBrains Mono", monospace',
              }}
            >
              {idx + 1}
            </div>
            <div style={{ fontSize: 12, lineHeight: 1.45, color: "#1B3A4B" }}>{line}</div>
          </div>
        ))}
      </div>
    </motion.aside>
  );
}
