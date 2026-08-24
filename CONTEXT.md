# LineLens

A diagnostic instrument for machine-production data: it ingests a machine CSV export, computes deterministic totals and KPIs from it, surfaces the numbers that don't add up, and renders the results as charts.

## Language

**State interval**:
One continuous period the machine spent in a single state (e.g. Running 06:00–06:45). The atomic unit of the data model — totals are sums of intervals.
_Avoid_: event, record, log entry, row

**Tag snapshot**:
A point-in-time dump of PLC tag values, each already aggregated over a window (a state's total seconds, a lifetime bottle count, an already-computed KPI). The real machine's native export shape — a different grain from state intervals, and reference-only in v2.5.
_Avoid_: export, dump, reading

**Stop cause**:
The canonical category of a stop interval, drawn from the machine's native `AlarmStatus` families — Fault, External, Starvation (upstream empty), Buildup (downstream full), Operator, Supplies — plus Changeover and Maintenance (planned service stops, always `planned`). The unit of both the Pareto chart and the what-if sliders. Maintenance causes are the labeled service events the maintenance forecast learns from.
_Avoid_: downtime reason, fault code, error

**Bottles lost**:
The impact currency — time lost to a stop cause multiplied by target speed — the bottles that would have been made had that time run at target. The Pareto's y-axis and the unit the what-if sliders report improvement in.
_Avoid_: deficit, shortfall, loss

**Baseline**:
The OEE computed from the data as-is — the reference the what-if measures improvement against. Dragging a slider never mutates it; each what-if is priced as a delta off the baseline.
_Avoid_: actual, current value, real OEE

**Reduction**:
The what-if lever: the fraction (0–100%) by which a stop cause's unplanned downtime is hypothetically cut. The freed time becomes run at the line's current speed, so Availability and throughput rise while Performance and Quality stay at baseline (ADR-0005).
_Avoid_: saving, gain, improvement target

**Bottles recovered**:
The what-if's payoff — the bottles-lost removed by a reduction, summed across the moved causes. Reducing cause X by r recovers exactly r × that cause's bottles-lost; it is the delta the sliders report.
_Avoid_: saved bottles, gained production, recovered loss

**Service interval**:
The learned service rhythm — the bottles between consecutive service events (Maintenance stops and repair-length Faults), reported as a median with a spread, never a bare number. Needs ≥ 2 service events to learn at all; below that the maintenance view shows the service counter only and says so.

**Due window**:
The maintenance forecast's output — the date range (and remaining bottle count) within which the next service falls due, computed from the learned service interval counted down by the service counter, and pulled **earlier only** when condition signals (fault-rate trend, Performance degradation) worsen — always with the reason stated. Like every future quantity in LineLens, it is a band, never a confident date.
_Avoid_: maintenance date, next service at, countdown

**Trend**:
The straight-line direction the period's daily production is moving, fit by ordinary least-squares on the dated daily good-parts series (ADR-0006). Drawn as a dashed line — a summary of where the data is heading, not a measurement of any one day.
_Avoid_: forecast, prediction, regression line (to a reader), best fit

**Service counter**:
The maintenance "trip counter" — bottles produced since the last service event, counted from the incremental `good_count`/`reject_count` of the intervals after it. Chosen over calendar time or run-hours because a line can sit powered-down accruing neither wear nor bottles; production volume is the truest analogue of a car's kilometers (and matches the machine's own `Bottles_Counter` odometer). The maintenance forecast counts the service counter down against the learned service interval.
_Avoid_: maintenance hours, time since service

**Forecast band**:
The ±1σ shaded ribbon around the trend's extrapolation — the only place uncertainty appears (ADR-0002). It is a widening prediction interval: it grows with the horizon because the further ahead, the less the past determines the future. The band — not the trend line — is the forecast; a future day is always shown as a range inside it, never a single confident number.
_Avoid_: confidence interval, error bar, prediction (unqualified), forecast value

**Horizon**:
How far the trend is extrapolated past the last observed day: 7 calendar days (ADR-0006). A projection needs ≥ 7 observed daily points to draw at all; with fewer the chart says so rather than invent a line.
_Avoid_: lookahead, forecast window, lead time

**Projection**:
The deterministic fallback forecast: an arithmetic read-out of "where is this heading," extrapolating the recent direction with a widening band. Deliberately not a *prediction* — it states no confident future number and assumes the recent trend persists. Used when there is too little history to train a Forecast (ADR-0007); with enough data the learned Forecast supersedes it.
_Avoid_: prediction, estimate (of a future value)

**Forecast**:
The learned prediction of a future daily series (production) — a gradient-boosted model with a conformal-calibrated band, trained on history (unlike a Projection). Always emitted as a range with a *measured* coverage guarantee, never a single confident number; drawn only with enough history (≥ ~3 months), otherwise the deterministic Projection is used. Not to be confused with the **Forecast band** entry above, which is the Projection's own ±1σ ribbon (ADR-0006/0007).
_Avoid_: point prediction, confident number, the AI predicts

