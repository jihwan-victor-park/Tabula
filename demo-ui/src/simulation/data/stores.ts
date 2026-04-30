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
    name: "College Convenience & Deli",
    short: "College Deli",
    color: "#ffffff",
    glow: "rgba(255,255,255,0.30)",
    specialty: "Convenience store + deli",
    area: "College Street",
    signalLines: ["sandwich combo sales +17%", "energy drink inventory low", "late-night snack traffic surging", "deli meat reorder behind schedule"],
    encryptedLines: ["Σ(s₁)·κ = 0.91", "H(inv) → b72e…44d", "μ_latenight ∈ [1.21,1.34]", "∂R/∂t · ω₃ < θ_min"],
    recommendation: "Restock energy drinks and deli supplies before late-night rush window",
    planSummary: [
      "Increase deli meat and bread orders by 20% for the next cycle.",
      "Expand energy drink and grab-and-go snack facings near the register.",
      "Introduce a late-night combo deal (sandwich + drink + chips) to lift basket size.",
      "Reduce slow-moving canned goods to free shelf space for high-velocity items.",
    ],
  },
  {
    id: "store_b",
    name: "Grails",
    short: "Grails",
    color: "#d9d9d9",
    glow: "rgba(255,255,255,0.22)",
    specialty: "Sneakers + streetwear",
    area: "Chapel Street",
    signalLines: ["limited-edition drop sell-through 96%", "hoodie margin expanding", "weekend foot traffic +13%", "resale price premium holding"],
    encryptedLines: ["Δ(d₂)=+0.96·ε", "π_hoodie > θ_high", "ρ_weekend ↑ 0.13", "λ_resale → Φ · β₂"],
    recommendation: "Prioritize limited drops and high-margin streetwear over basic inventory",
    planSummary: [
      "Secure early allocation on upcoming Nike and New Balance limited drops.",
      "Expand hoodie and graphic tee depth — margins are strong and turns are fast.",
      "Create weekend-exclusive bundles (sneaker + accessory) for walk-in traffic.",
      "Reduce basic tee and sock reorders to free capital for hype releases.",
    ],
  },
  {
    id: "store_c",
    name: "Edible Arrangements",
    short: "Edible",
    color: "#ededed",
    glow: "rgba(255,255,255,0.24)",
    specialty: "Fruit arrangements + gifts",
    area: "Whalley Avenue",
    signalLines: ["holiday preorders +22%", "chocolate-dipped strawberry demand spiking", "corporate gift orders rising", "same-day delivery requests up"],
    encryptedLines: ["v_preorder ↑ · λ₄", "τ_choc < reorder", "δ_corp → σ_high", "Ψ(sameday) ≥ 0.81·κ"],
    recommendation: "Scale preorder capacity and fresh fruit supply ahead of gifting season",
    planSummary: [
      "Increase fresh strawberry and melon procurement by 25% for upcoming holidays.",
      "Promote corporate gift packages with volume discount tiers.",
      "Add same-day delivery slots on Fridays and Saturdays to capture last-minute orders.",
      "Trim low-performing novelty items and focus display on signature fruit arrangements.",
    ],
  },
  {
    id: "store_d",
    name: "Tinaliah Designs",
    short: "Tinaliah",
    color: "#cecece",
    glow: "rgba(255,255,255,0.20)",
    specialty: "Custom jewelry + accessories",
    area: "Audubon Street",
    signalLines: ["custom name necklace orders +19%", "gold-plated pieces outpacing silver", "event-driven spikes around graduation", "personalization requests growing"],
    encryptedLines: ["Δ(j₇)=+0.19", "gold_f > τ_silver", "event(x) → ψ_grad", "ρ(custom,t) ≡ ∇·μ₅"],
    recommendation: "Invest in gold-plated custom stock and graduation-themed collections",
    planSummary: [
      "Increase gold-plated chain and pendant blanks for the custom name necklace line.",
      "Launch a graduation capsule collection — class year charms and initial pendants.",
      "Reduce broad silver assortment and focus on bestselling silhouettes.",
      "Offer express personalization turnaround to capture last-minute gift buyers.",
    ],
  },
  {
    id: "store_e",
    name: "The Marketa",
    short: "Marketa",
    color: "#f2f2f2",
    glow: "rgba(255,255,255,0.26)",
    specialty: "Local artisan market",
    area: "State Street",
    signalLines: ["handmade candle sales +15%", "local honey consistently sold out", "vendor booth occupancy at 94%", "weekend market foot traffic surging"],
    encryptedLines: ["q_candle → 1.15x", "turn(honey)=high", "booth ∈ near_full", "∂Q/∂t > α·θ_wknd"],
    recommendation: "Expand vendor capacity and restock high-demand artisan staples",
    planSummary: [
      "Add two weekend vendor slots to meet booth demand and diversify offerings.",
      "Coordinate with local honey and candle makers for larger batch commitments.",
      "Introduce a curated 'Marketa Box' bundle for online and in-person sales.",
      "Promote artisan spotlight events to drive midweek foot traffic.",
    ],
  },
  {
    id: "store_f",
    name: "York Street Noodle House",
    short: "York Noodle",
    color: "#dbdbdb",
    glow: "rgba(255,255,255,0.22)",
    specialty: "Asian noodles + bubble tea",
    area: "York Street",
    signalLines: ["bubble tea orders +21%", "spicy ramen combo most popular", "late-night delivery demand growing", "taro and matcha flavors trending"],
    encryptedLines: ["boba(t)+=0.21", "ramen↑ · α₂", "delivery_rate > θ", "E(flavor) → Φ[taro]·ε"],
    recommendation: "Scale bubble tea capacity and add late-night delivery window",
    planSummary: [
      "Increase tapioca pearl and taro powder stock by 30% for next order cycle.",
      "Extend kitchen hours to 1 AM on Thursday–Saturday for late-night orders.",
      "Promote spicy ramen + bubble tea combo deal for higher average ticket.",
      "Use delivery platform data to optimize prep timing and reduce wait times.",
    ],
  },
  {
    id: "store_g",
    name: "Book Trader Cafe",
    short: "Book Trader",
    color: "#cfcfcf",
    glow: "rgba(255,255,255,0.20)",
    specialty: "Used books + coffee",
    area: "Whitney Avenue",
    signalLines: ["used fiction turnover +12%", "espresso drink margins strong", "study-session traffic steady", "rare book inquiries increasing"],
    encryptedLines: ["fict(x)=+0.12", "c_espresso > τ", "study(y) ≈ const", "Ω(rare) · ν ↑ 0.08"],
    recommendation: "Expand curated fiction sections and promote espresso pairings",
    planSummary: [
      "Source more used literary fiction and classics — fastest turning category.",
      "Bundle coffee + book deals for study-session regulars to lift basket size.",
      "Create a rotating 'staff picks' shelf to move mid-tier inventory faster.",
      "List rare and collectible finds online to reach buyers beyond walk-in traffic.",
    ],
  },
  {
    id: "store_h",
    name: "Atticus Bookstore",
    short: "Atticus",
    color: "#e4e4e4",
    glow: "rgba(255,255,255,0.24)",
    specialty: "Books + cafe + gifts",
    area: "Chapel Street",
    signalLines: ["new release presales climbing", "cafe pastry attach rate +10%", "gift wrap requests up at holidays", "author event attendance strong"],
    encryptedLines: ["presale ↑ · 0.18", "pastry_attach > τ", "conv(gift)=rising", "Δ(event,t) ∈ Ψ·γ₃"],
    recommendation: "Double down on new releases, author events, and cafe-gift bundles",
    planSummary: [
      "Increase new release presale allocations for high-profile spring titles.",
      "Promote 'book + pastry + gift wrap' bundles near the cafe counter.",
      "Schedule monthly author events to drive repeat traffic and social buzz.",
      "Reduce deep backlist overstock and redirect capital to curated gift items.",
    ],
  },
];
