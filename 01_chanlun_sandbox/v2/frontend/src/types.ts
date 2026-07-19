export type LifecycleState =
  | "candidate"
  | "confirmed"
  | "risk_downgraded"
  | "invalidated"
  | "expired";

export interface StockInfo {
  symbol: string;
  name: string;
  periods: string[];
  quality: string;
  last_synced_at?: string | null;
}

export interface MarketBar {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  amount: number;
  vwap?: number;
}

export interface Lifecycle {
  state: LifecycleState;
  event_at: string;
  detected_at: string;
  confirmed_at?: string | null;
  invalidated_at?: string | null;
  expired_at?: string | null;
}

export interface ChanSignal {
  id: string;
  level: string;
  label: string;
  display_label?: string;
  side?: "buy" | "sell";
  price: number;
  confidence: number;
  divergence_class: string;
  structure_guard: number;
  risk_guard: number;
  lifecycle: Lifecycle;
  evidence: Record<string, unknown>;
}

export interface CrossLevelEvent {
  id: string;
  source_level: "5m";
  target_level: "30m";
  direction: "up" | "down";
  label: string;
  source_signal_id: string;
  source_signal_label: string;
  source_price: number;
  break_boundary: number;
  risk_guard: number;
  lifecycle: {
    state: "candidate" | "triggered" | "confirmed" | "invalidated" | "expired";
    event_at: string;
    detected_at: string;
    triggered_at?: string | null;
    confirmed_at?: string | null;
    invalidated_at?: string | null;
    expired_at?: string | null;
  };
  evidence: Record<string, any>;
}

export interface ChanLine {
  id: string;
  level: string;
  start_at: string;
  end_at: string;
  confirmed_at: string;
  direction: "up" | "down";
  start_price: number;
  end_price: number;
  stroke_count: number;
  is_sure: boolean;
  source_kind: "stroke" | "segment" | "higher_segment";
}

export interface ChanCenter {
  id: string;
  level: string;
  start_at: string;
  end_at: string;
  zd: number;
  zg: number;
  dd?: number | null;
  gg?: number | null;
  state: "active" | "completed";
  component_count: number;
  extension_count: number;
  is_sure: boolean;
}

export interface ChanLayer {
  engine: string;
  engine_commit: string;
  level: string;
  pivots: Array<Record<string, any>>;
  strokes: ChanLine[];
  segments: ChanLine[];
  higher_segments: ChanLine[];
  centers: ChanCenter[];
  segment_centers: ChanCenter[];
  signals: ChanSignal[];
  signal_history: ChanSignal[];
  current: Record<string, any>;
  summary: Record<string, number>;
}

export interface RadarPivot {
  id: string;
  level: string;
  kind: "top" | "bottom";
  event_at: string;
  confirmed_at: string;
  price: number;
}

export interface RadarSwing {
  id: string;
  level: string;
  direction: "up" | "down";
  start_at: string;
  end_at: string;
  confirmed_at: string;
  start_price: number;
  end_price: number;
  low: number;
  high: number;
}

export interface RadarZone {
  id: string;
  level: string;
  start_at: string;
  formed_at: string;
  end_at: string;
  departure_scan_at: string;
  zd: number;
  zg: number;
  low: number;
  high: number;
  component_count: number;
  extension_count: number;
  state: "active" | "completed";
  market_state: string;
}

export interface RadarEvent {
  id: string;
  level: string;
  type: string;
  zone_id: string;
  event_at: string;
  confirmed_at: string;
  price: number;
  boundary: number;
  risk_line: number;
  status: "confirmed";
  evidence: {
    relative_volume?: number | null;
    volume_status: "supportive" | "neutral" | "weak" | "unavailable";
    dif?: number | null;
    dea?: number | null;
    histogram?: number | null;
    macd_status: "supportive" | "neutral" | "conflicting" | "unavailable";
  };
}

export interface RadarLayer {
  version: string;
  level: string;
  pivots: RadarPivot[];
  swings: RadarSwing[];
  zones: RadarZone[];
  events: RadarEvent[];
  current: {
    level: string;
    state: string;
    price: number;
    zone?: RadarZone | null;
    last_pivot?: RadarPivot | null;
    last_swing?: RadarSwing | null;
    last_event?: RadarEvent | null;
    risk_line?: number | null;
    observation: string;
  };
  summary: Record<string, number>;
}

export interface AnalysisResponse {
  schema_version: string;
  model_version: string;
  config_hash: string;
  data_hash: string;
  as_of: string;
  visible_bar_end: string;
  symbol: string;
  stock_name: string;
  levels: { decision: string; execution: string; higher: string; display: string };
  data_quality: Record<string, unknown>;
  bars: MarketBar[];
  indicators: {
    macd: { dif: Array<number | null>; dea: Array<number | null>; histogram: Array<number | null> };
    wyckoff: Record<string, Array<number | null>>;
  };
  radar: { version: string; execution: RadarLayer; decision: RadarLayer; higher: RadarLayer };
  chan: {
    execution: ChanLayer;
    decision: ChanLayer;
    higher: ChanLayer;
  };
  cross_level: {
    version: string;
    source_level: "5m";
    target_level: "30m";
    events: CrossLevelEvent[];
    active: CrossLevelEvent[];
    summary: Record<string, number>;
  };
  wyckoff: Record<string, any>;
  wave: Record<string, any>;
  fusion: { grade: "A" | "B" | "C" | "D"; structure: string; supply_demand: string; path: string; conflicts: string[] };
  plan: {
    trigger: string;
    invalidation: string;
    action: string;
    forbidden: string;
    next_observation: string;
    position_tier: string;
  };
  warnings: string[];
}

export interface AnalyzePayload {
  symbol: string;
  decision_level: "30m";
  execution_level: "5m";
  display_level: "5m" | "30m";
  start?: string;
  end?: string;
  as_of?: string;
  profile: "production" | "balanced" | "research";
  benchmark?: string;
  include_invalidated: boolean;
}
