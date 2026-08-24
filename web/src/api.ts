/**
 * Typed client for the LineLens FastAPI backend (server/app.py).
 * Interfaces mirror server/serialize.py field-for-field — that module is the
 * contract; if a payload shape changes there, change it here.
 */

// --- primitives ---------------------------------------------------------------

/** JSON-safe scalar as serialize._json_safe emits it (null / string / number / boolean). */
export type Scalar = string | number | boolean | null;

export type RecordRow = Record<string, Scalar>;

// --- upload -------------------------------------------------------------------

export interface DatasetProfileDict {
  row_count: number;
  columns: string[];
  dtypes: Record<string, string>;
  null_counts: Record<string, number>;
  head_preview: string[][];
}

export interface RoleSuggestion {
  role: string | null;
  confidence: number;
}

export interface UploadResponse {
  dataset_id: string;
  name: string;
  profile: DatasetProfileDict;
  preview: RecordRow[];
  preview_summary: string;
  suggested_roles: Record<string, RoleSuggestion>;
  auto_roles: Record<string, string>;
  auto_counters: string[];
  numeric_counter_options: string[];
  capabilities: Record<string, boolean>;
}

// --- analyze deck ---------------------------------------------------------------

export interface FindingDict {
  rule_id: string;
  severity: 'error' | 'warning' | 'info';
  title: string;
  description: string;
  evidence: Record<string, Scalar>;
  affected_rows: number[];
  machine_id: string | null;
  signal: string | null;
  period_start: string | null;
  period_end: string | null;
  observed_value: number | null;
  maximum_possible_value: number | null;
  calculated_value: number | null;
  suspected_cause: string | null;
  confidence: number | null;
  suggested_action: string | null;
}

export interface ReportDict {
  state_totals: RecordRow[];
  production_totals: RecordRow[];
  downtime_by_reason: RecordRow[];
  duration_source: string | null;
}

export interface BottlesLostDict {
  cause: string;
  seconds_lost: number;
  weighted_target: number;
  bottles: number;
}

export interface OEEDict {
  availability: number;
  performance: number;
  quality: number;
  oee: number;
  run_time: number;
  unplanned_stop_time: number;
  planned_stop_time: number;
  idle_time: number;
  good: number;
  reject: number;
  bottles_lost: BottlesLostDict[];
  duration_source: string | null;
  notes: string[];
}

export interface MaintenanceDict {
  bottles_since_service: number;
  last_service_end: string | null;
  n_service_events: number;
  repair_threshold_s: number | null;
  interval: { median: number; q1: number; q3: number; n: number } | null;
  due: {
    remaining_early: number;
    remaining_late: number;
    date_early: string | null;
    date_late: string | null;
    adjusted_earlier: boolean;
    reasons: string[];
  } | null;
  notes: string[];
}

export interface ForecastViewDict {
  line_dates: string[];
  central: number[];
  band_dates: string[];
  lower: number[];
  upper: number[];
  slope: number;
  r_squared: number;
  technique: 'gradient-boosted' | 'linear';
}

export type ForecastReason = 'ok' | 'too_few' | 'zero_scatter' | 'no_series';

export interface ForecastDict {
  reason: ForecastReason;
  view: ForecastViewDict | null;
}

export interface DailySeriesDict {
  dates: string[];
  values: number[];
}

export interface ParetoDict {
  causes: string[];
  bottles: number[];
  cumulative_pct: number[];
}

export interface StateInterval {
  start: string | null;
  end: string | null;
  state: Scalar;
  machine: string | null;
}

/** The state timeline in whichever form the window can show.
 *
 *  The server picks the mode (server/serialize.py `state_timeline`). Short
 *  windows send every interval for the gantt. Wider windows send seconds per
 *  state per day, already bucketed, because shipping every interval for a
 *  six-month file cost 924 KB the client only collapsed into daily bars. */
export type StateTimelineDict =
  | { mode: 'empty' }
  | { mode: 'gantt'; intervals: StateInterval[] }
  | {
      mode: 'composition';
      /** 'week' once the window is too wide for one bar per day. */
      grain: 'day' | 'week';
      days: string[];
      states: string[];
      grid: number[][];
    };

export interface MtbfDict {
  median: number;
  q1: number;
  q3: number;
}

export interface AnalyzeResponse {
  fingerprint: string;
  mapping: { roles: Record<string, string>; counters: string[] };
  findings: FindingDict[];
  severity_counts: Record<string, number>;
  contrast_rows: RecordRow[];
  report: ReportDict;
  oee: OEEDict | null;
  maintenance: MaintenanceDict | null;
  planned_causes: string[];
  pareto: ParetoDict;
  daily_good: DailySeriesDict | null;
  forecast: ForecastDict;
  daily_performance: DailySeriesDict | null;
  performance_forecast: ForecastDict;
  performance_concern: number;
  performance_crossing: string | null;
  degradation_caption: string | null;
  mtbf: MtbfDict | null;
  fault_interval_count: number;
  date_span: [string, string] | null;
  state_timeline: StateTimelineDict;
  capabilities: Record<string, boolean>;
}

// --- scope / whatif -------------------------------------------------------------

export interface MappingBody {
  roles: Record<string, string>;
  counters: string[];
}

export interface ScopeResponse {
  fingerprint: string;
  narrowed: boolean;
  range: [string | null, string | null];
  state_timeline: StateTimelineDict;
  report: ReportDict;
}

export interface LeverDelta {
  cause: string;
  bottles: number;
}

export interface WhatIfResponse {
  fingerprint: string;
  baseline: OEEDict | null;
  hypo: OEEDict | null;
  recovered: number;
  lever_deltas: LeverDelta[];
  /** Horizon segment of the production forecast lifted by the recovered
   *  bottles (dates[0]/values[0] anchor at the last observed day). Null when
   *  no lever moved or no honest forecast exists. */
  forecast_lift: { dates: string[]; values: number[] } | null;
}

// --- errors -----------------------------------------------------------------------

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : JSON.stringify(detail));
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }

  /** The 422 mapping-problem list, when the backend sent one. */
  get problems(): string[] | null {
    if (
      this.detail &&
      typeof this.detail === 'object' &&
      'problems' in this.detail &&
      Array.isArray((this.detail as { problems: unknown }).problems)
    ) {
      return (this.detail as { problems: string[] }).problems;
    }
    return null;
  }
}

async function parseOrThrow(r: Response) {
  if (r.ok) return r.json();
  let detail: unknown = r.statusText;
  try {
    detail = (await r.json()).detail ?? detail;
  } catch {
    /* non-JSON error body — keep statusText */
  }
  throw new ApiError(r.status, detail);
}

// --- client -----------------------------------------------------------------------

export async function uploadCsv(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append('file', file, file.name);
  const r = await fetch('/api/upload', { method: 'POST', body: form });
  return parseOrThrow(r);
}

export async function analyze(datasetId: string, mapping: MappingBody): Promise<AnalyzeResponse> {
  const r = await fetch(`/api/datasets/${datasetId}/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mapping }),
  });
  return parseOrThrow(r);
}

export async function scope(
  datasetId: string,
  mapping: MappingBody,
  start: string | null,
  end: string | null,
): Promise<ScopeResponse> {
  const r = await fetch(`/api/datasets/${datasetId}/scope`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mapping, start, end }),
  });
  return parseOrThrow(r);
}

export async function whatif(
  datasetId: string,
  mapping: MappingBody,
  reductions: Record<string, number>,
): Promise<WhatIfResponse> {
  const r = await fetch(`/api/datasets/${datasetId}/whatif`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mapping, reductions }),
  });
  return parseOrThrow(r);
}

export function exportUrl(datasetId: string, kind: 'cleaned.csv' | 'findings.json' | 'findings.csv', fingerprint: string): string {
  return `/api/datasets/${datasetId}/export/${kind}?fingerprint=${encodeURIComponent(fingerprint)}`;
}
