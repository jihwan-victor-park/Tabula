export type StoreDef = {
  id: string;
  name: string;
  short: string;
  color: string;
  glow: string;
  specialty: string;
  area: string;
  signalLines: string[];
  encryptedLines: string[];
  recommendation: string;
  planSummary: string[];
};

export const STORES: StoreDef[] = [
  {
    id: "store_a",
    name: "Pebble",
    short: "Pebble",
    color: "#ffffff",
    glow: "rgba(255,255,255,0.30)",
    specialty: "Toy + gift retail",
    area: "Broadway / York",
    signalLines: ["STEM kits sell-through +14%", "low on educational sets", "gift basket size up on weekends", "reorder depth insufficient"],
    encryptedLines: ["Σ(p₁)·κ = 0.84", "H(inv) → a84f…91c", "μ_weekend ∈ [1.12,1.18]", "∂R/∂t · ω₃ < θ_min"],
    recommendation: "Expand educational toy reorder depth before weekend peak",
    planSummary: [
      "Raise educational toy buy by 18-22% for the next order cycle.",
      "Trim slow doll SKUs and reassign shelf space to STEM endcaps.",
      "Bundle teacher gifts near checkout for higher basket size.",
      "Keep cash exposure controlled by limiting deep buys in slow novelty categories.",
    ],
  },
  {
    id: "store_b",
    name: "Elm & Iron Cafe",
    short: "Elm & Iron",
    color: "#d9d9d9",
    glow: "rgba(255,255,255,0.22)",
    specialty: "Cafe + pantry goods",
    area: "Elm Street",
    signalLines: ["coffee beans usage +9%", "pastry margin compressed", "morning traffic steady", "labor window inefficient"],
    encryptedLines: ["Δ(c₂)=+0.09·ε", "π_pastry < θ_min", "ρ_am ≈ const", "λ_labor → ∅ · β₂"],
    recommendation: "Shift mix toward higher-margin grab-and-go pantry bundles",
    planSummary: [
      "Reduce low-margin pastry waste by tightening late-day baking quantities.",
      "Promote pantry add-ons with morning drink orders.",
      "Negotiate bean replenishment cadence before finals-week traffic.",
      "Protect labor margin by consolidating slow mid-afternoon prep windows.",
    ],
  },
  {
    id: "store_c",
    name: "Chapel Street Market",
    short: "Chapel Market",
    color: "#ededed",
    glow: "rgba(255,255,255,0.24)",
    specialty: "Corner grocery",
    area: "Chapel Street",
    signalLines: ["snack velocity rising", "cold drink inventory tight", "price sensitivity elevated", "combo demand increasing"],
    encryptedLines: ["v_snack ↑ · λ₄", "τ_cold < reorder", "δ_price → σ_high", "Ψ(combo) ≥ 0.73·κ"],
    recommendation: "Prioritize beverages and snack replenishment while holding premium imports",
    planSummary: [
      "Increase cold drink replenishment frequency from twice weekly to three times.",
      "Hold premium import orders until demand broadens beyond convenience items.",
      "Use smaller case sizes on volatile snack categories to reduce spoilage risk.",
      "Push combo signage near coolers for basket efficiency.",
    ],
  },
  {
    id: "store_d",
    name: "Audubon Prints",
    short: "Audubon Prints",
    color: "#cecece",
    glow: "rgba(255,255,255,0.20)",
    specialty: "Art + stationery",
    area: "Audubon District",
    signalLines: ["journal demand up", "frame sales soft", "event-driven spikes observed", "campus event correlation"],
    encryptedLines: ["Δ(j₇)=+0.17", "frame_f < τ", "event(x) → ψ_peak", "ρ(campus,t) ≡ ∇·μ₅"],
    recommendation: "Lean into journals and event bundles instead of heavy frame restocks",
    planSummary: [
      "Double down on journals, pens, and small-format gifts for event weeks.",
      "Reduce new frame intake until gallery conversion improves.",
      "Create Yale-themed stationery bundles timed to campus milestones.",
      "Concentrate visual merchandising on portable high-margin items.",
    ],
  },
  {
    id: "store_e",
    name: "Broadway Bikes",
    short: "Broadway Bikes",
    color: "#f2f2f2",
    glow: "rgba(255,255,255,0.26)",
    specialty: "Bike shop",
    area: "Broadway",
    signalLines: ["repair queue lengthening", "helmet turns healthy", "parts availability uneven", "service backlog growing"],
    encryptedLines: ["q_repair → 1.3x", "turn(helmet)=good", "parts ∈ mixed_state", "∂Q/∂t > α·θ_max"],
    recommendation: "Move capital into repair parts and accessories, not full bike inventory",
    planSummary: [
      "Prioritize brake, chain, and tire inventory to shorten service backlog.",
      "Delay broad bike model expansion until parts reliability stabilizes.",
      "Promote accessory attachments during repair pickup.",
      "Reserve labor slots for high-value repairs during peak commute windows.",
    ],
  },
  {
    id: "store_f",
    name: "Ninth Square Florist",
    short: "Ninth Florist",
    color: "#dbdbdb",
    glow: "rgba(255,255,255,0.22)",
    specialty: "Floral + gifts",
    area: "Ninth Square",
    signalLines: ["preorder bouquets rising", "same-day waste improved", "gift add-ons underused", "event date correlation"],
    encryptedLines: ["pre(bq)+=0.13", "waste↓ · α₂", "attach_rate < θ", "E(date) → Φ[t+1]·ε"],
    recommendation: "Scale preorder bundles and add gift attachment prompts",
    planSummary: [
      "Push preorder pickup bundles for high-certainty event dates.",
      "Keep same-day stem volume conservative to protect margin.",
      "Train staff to upsell candles and cards at order close.",
      "Use reservation data to smooth labor and procurement planning.",
    ],
  },
  {
    id: "store_g",
    name: "York Noodle Bar",
    short: "York Noodle",
    color: "#cfcfcf",
    glow: "rgba(255,255,255,0.20)",
    specialty: "Fast casual restaurant",
    area: "York Street",
    signalLines: ["late-night orders +11%", "protein cost pressure", "combo uptake improving", "throughput bottleneck"],
    encryptedLines: ["late(x)=+0.11", "c_protein > τ", "bundle(y) ↑", "Ω(throughput) · ν < 1"],
    recommendation: "Lean into combo menus and protect margin on protein-heavy dishes",
    planSummary: [
      "Rebalance menu highlights toward higher-margin combo sets.",
      "Use smaller protein-heavy specials until input costs normalize.",
      "Keep late-night staffing flexible around Thursday-Saturday surges.",
      "Promote fast pickup bundles to improve throughput during campus rushes.",
    ],
  },
  {
    id: "store_h",
    name: "Whitney Games",
    short: "Whitney Games",
    color: "#e4e4e4",
    glow: "rgba(255,255,255,0.24)",
    specialty: "Board games + hobby retail",
    area: "Whitney Ave",
    signalLines: ["starter games trending", "premium boxes slower", "community nights converting", "preorder demand shifting"],
    encryptedLines: ["starter ↑ · 0.16", "premium_box < τ", "conv(event)=strong", "Δ(pre,t) ∈ Ψ·γ₃"],
    recommendation: "Expand entry-level tabletop assortment and event-linked bundles",
    planSummary: [
      "Increase depth in beginner-friendly games with proven conversion.",
      "Reduce premium slow movers unless tied to event demand.",
      "Package event-night promos with snacks or accessories.",
      "Use preorders for expensive niche titles instead of stocking wide.",
    ],
  },
];
