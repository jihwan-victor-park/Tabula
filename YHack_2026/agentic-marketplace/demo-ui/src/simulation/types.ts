export type Trend = {
  category: string;
  direction: string;
  strength: number;
  signal_count: number;
  consensus: string;
};

export type PipelineResults = {
  cycle_id?: string;
  scenario?: string;
  generated_at?: string;
  market_trends: Trend[];
};

export type DemoPhase =
  | "idle"
  | "signals"
  | "encrypt"
  | "communicate"
  | "aggregate"
  | "recommend"
  | "complete";
