import { motion } from "framer-motion";

export function Background({ showMap }: { showMap: boolean }) {
  return (
    <div aria-hidden style={{ position: "fixed", inset: 0, zIndex: 0 }}>
      <div style={{ position: "absolute", inset: 0, background: "#F5E0CF" }} />

      {/* ── Map layer ── */}
      <motion.svg
        animate={{ opacity: showMap ? 0.88 : 0 }}
        transition={{ duration: 1.6 }}
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
        viewBox="0 0 1440 900"
        preserveAspectRatio="xMidYMid slice"
      >
        <rect width="1440" height="900" fill="#F5E0CF" />

        {/* City blocks */}
        <g fill="#EDD5C4" stroke="#E8D4C6" strokeWidth="0.8" opacity="0.85">
          <rect x="90" y="90" width="180" height="92" rx="7" />
          <rect x="90" y="208" width="180" height="96" rx="7" />
          <rect x="90" y="332" width="180" height="70" rx="7" />
          <rect x="90" y="454" width="180" height="70" rx="7" />
          <rect x="306" y="90" width="122" height="92" rx="7" />
          <rect x="306" y="208" width="122" height="96" rx="7" />
          <rect x="306" y="332" width="122" height="70" rx="7" />
          <rect x="464" y="90" width="110" height="92" rx="7" />
          <rect x="464" y="208" width="110" height="96" rx="7" />
          <rect x="778" y="90" width="138" height="92" rx="7" />
          <rect x="778" y="208" width="138" height="96" rx="7" />
          <rect x="778" y="332" width="138" height="70" rx="7" />
          <rect x="952" y="90" width="140" height="92" rx="7" />
          <rect x="952" y="208" width="140" height="96" rx="7" />
          <rect x="952" y="332" width="140" height="70" rx="7" />
          <rect x="1128" y="90" width="212" height="92" rx="7" />
          <rect x="1128" y="208" width="212" height="96" rx="7" />
          <rect x="1128" y="332" width="212" height="70" rx="7" />
          <rect x="616" y="454" width="126" height="70" rx="7" />
          <rect x="778" y="454" width="138" height="70" rx="7" />
          <rect x="952" y="454" width="140" height="70" rx="7" />
          <rect x="1128" y="454" width="212" height="70" rx="7" />
          <rect x="90" y="552" width="180" height="108" rx="7" />
          <rect x="306" y="552" width="122" height="108" rx="7" />
          <rect x="778" y="552" width="138" height="108" rx="7" />
          <rect x="952" y="552" width="140" height="108" rx="7" />
          <rect x="1128" y="552" width="212" height="108" rx="7" />
          <rect x="90" y="688" width="180" height="92" rx="7" />
          <rect x="778" y="688" width="138" height="92" rx="7" />
          <rect x="1128" y="688" width="212" height="92" rx="7" />
        </g>

        {/* Green/park blocks */}
        <g fill="#E0D8CF" stroke="#D4C8BC" strokeWidth="0.8" opacity="0.78">
          <rect x="576" y="325" width="178" height="105" rx="12" />
          <rect x="768" y="208" width="124" height="90" rx="9" />
          <rect x="612" y="198" width="116" height="94" rx="9" />
        </g>

        {/* Major roads — thick */}
        <g fill="none" stroke="#1B3A4B" strokeWidth="14" strokeLinecap="round" strokeLinejoin="round" opacity="0.08">
          <path d="M 76 386 L 1360 386" />
          <path d="M 70 504 L 1368 504" />
          <path d="M 118 264 L 1310 264" />
          <path d="M 92 621 L 1348 621" />
          <path d="M 205 72 L 205 806" />
          <path d="M 446 72 L 446 806" />
          <path d="M 590 72 L 590 806" />
          <path d="M 756 72 L 756 806" />
          <path d="M 928 72 L 928 806" />
          <path d="M 1084 72 L 1084 806" />
        </g>

        {/* Road center lines */}
        <g fill="none" stroke="#1B3A4B" strokeWidth="2.8" strokeLinecap="round" opacity="0.12">
          <path d="M 76 386 L 1360 386" />
          <path d="M 70 504 L 1368 504" />
          <path d="M 118 264 L 1310 264" />
          <path d="M 92 621 L 1348 621" />
          <path d="M 205 72 L 205 806" />
          <path d="M 446 72 L 446 806" />
          <path d="M 590 72 L 590 806" />
          <path d="M 756 72 L 756 806" />
          <path d="M 928 72 L 928 806" />
          <path d="M 1084 72 L 1084 806" />
        </g>

        {/* Street names */}
        <g fill="#5C7A8A" fontFamily="'JetBrains Mono', monospace" fontSize="11" letterSpacing="0.10em">
          <text x="505" y="375">CHAPEL ST</text>
          <text x="510" y="493">CROWN ST</text>
          <text x="510" y="252">ELM ST</text>
          <text x="520" y="610">GEORGE ST</text>
          <text x="217" y="136" transform="rotate(90 217 136)">WHITNEY AVE</text>
          <text x="458" y="140" transform="rotate(90 458 140)">TEMPLE ST</text>
          <text x="602" y="126" transform="rotate(90 602 126)">COLLEGE ST</text>
          <text x="768" y="118" transform="rotate(90 768 118)">HIGH ST</text>
          <text x="940" y="124" transform="rotate(90 940 124)">YORK ST</text>
          <text x="1096" y="144" transform="rotate(90 1096 144)">BROADWAY</text>
        </g>

        {/* Landmark labels */}
        <g fill="#1B3A4B" fontFamily="'JetBrains Mono', monospace" fontSize="14" letterSpacing="0.12em">
          <text x="624" y="368">NEW HAVEN GREEN</text>
        </g>
        <g fill="#5C7A8A" fontFamily="'JetBrains Mono', monospace" fontSize="14" letterSpacing="0.14em" opacity="0.52">
          <text x="640" y="232">YALE UNIVERSITY</text>
        </g>
        <g fill="#9AAFBC" fontFamily="'JetBrains Mono', monospace" fontSize="9" letterSpacing="0.09em">
          <text x="787" y="226">OLD CAMPUS</text>
          <text x="640" y="262">STERLING</text>
        </g>
      </motion.svg>

      {/* ── Circle guide layer ── */}
      <motion.svg
        animate={{ opacity: showMap ? 0 : 1 }}
        transition={{ duration: 1.4, delay: showMap ? 0 : 1.0 }}
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
        viewBox="0 0 100 100"
        preserveAspectRatio="xMidYMid slice"
      >
        <circle cx="50" cy="50" r="32" fill="none" stroke="rgba(27,58,75,0.06)" strokeWidth="0.08" />
        <circle cx="50" cy="50" r="22" fill="none" stroke="rgba(27,58,75,0.04)" strokeWidth="0.06" />
        <circle cx="50" cy="50" r="12" fill="none" stroke="rgba(27,58,75,0.03)" strokeWidth="0.05" />
        <circle cx="50" cy="50" r="42" fill="none" stroke="rgba(27,58,75,0.025)" strokeWidth="0.06" strokeDasharray="0.3 1.8" />
        <line x1="50" y1="8" x2="50" y2="92" stroke="rgba(27,58,75,0.015)" strokeWidth="0.04" />
        <line x1="8" y1="50" x2="92" y2="50" stroke="rgba(27,58,75,0.015)" strokeWidth="0.04" />
        <line x1="18" y1="16" x2="82" y2="84" stroke="rgba(27,58,75,0.01)" strokeWidth="0.04" />
        <line x1="82" y1="16" x2="18" y2="84" stroke="rgba(27,58,75,0.01)" strokeWidth="0.04" />
        {Array.from({ length: 16 }).map((_, i) => {
          const angle = (i * Math.PI * 2) / 16;
          const r1 = 31;
          const r2 = 33;
          return (
            <line
              key={i}
              x1={50 + r1 * Math.cos(angle)} y1={50 + r1 * Math.sin(angle)}
              x2={50 + r2 * Math.cos(angle)} y2={50 + r2 * Math.sin(angle)}
              stroke="rgba(27,58,75,0.06)"
              strokeWidth="0.06"
            />
          );
        })}
      </motion.svg>

      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "radial-gradient(ellipse 82% 72% at 50% 50%, transparent 0%, rgba(245,224,207,0.92) 62%)",
        }}
      />
    </div>
  );
}
