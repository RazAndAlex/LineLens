# LineLens

A diagnostic instrument for machine-production data. It reads a machine CSV
export, computes deterministic totals and KPIs from it, surfaces the numbers
that do not add up, and draws the results as charts.

## Language

**State interval**:
One continuous period the machine spent in a single state, for example Running
06:00 to 06:45. This is the atomic unit of the data model. Every total is a sum
of intervals.
_Avoid_: event, record, log entry, row

**Tag snapshot**:
A point-in-time dump of PLC tag values, each already aggregated over a window: a
state's total seconds, a lifetime bottle count, an already-computed KPI. This is
the real machine's native export shape. It is a different grain from state
intervals, and it is reference-only in v2.5.
_Avoid_: export, dump, reading

**Stop cause**:
The canonical category of a stop interval, drawn from the machine's own
`AlarmStatus` families: Fault, External, Starvation (upstream empty), Buildup
(downstream full), Operator, and Supplies. Changeover and Maintenance are
planned service stops and are always `planned`. The stop cause is the unit of
both the Pareto chart and the what-if sliders. Maintenance causes are the
labelled service events the maintenance forecast learns from.
_Avoid_: downtime reason, fault code, error

**Bottles lost**:
The impact currency. It is the time lost to a stop cause multiplied by target
speed, so it counts the bottles that would have been made had that time run at
target. It is the Pareto's y-axis, and the unit the what-if sliders report
improvement in.
_Avoid_: deficit, shortfall, loss

**Baseline**:
The OEE computed from the data as it stands. It is the reference the what-if
measures improvement against. Dragging a slider never changes it. Each what-if
is priced as a delta off the baseline.
_Avoid_: actual, current value, real OEE

**Reduction**:
The what-if lever. It is the fraction, from 0 to 100 percent, by which a stop
cause's unplanned downtime is hypothetically cut. The freed time runs at the
line's current speed, so Availability and throughput rise while Performance and
Quality stay at baseline. See ADR-0005.
_Avoid_: saving, gain, improvement target

**Bottles recovered**:
The what-if payoff. It is the bottles-lost removed by a reduction, summed across
the moved causes. Reducing cause X by r recovers exactly r times that cause's
bottles-lost. This is the delta the sliders report.
_Avoid_: saved bottles, gained production, recovered loss

**Service interval**:
The learned service rhythm. It is the number of bottles between consecutive
service events, which are Maintenance stops and repair-length Faults. It is
reported as a median with a spread, never as a bare number. It needs at least 2
service events to learn at all. Below that the maintenance view shows the
service counter only, and says so.

**Due window**:
The maintenance forecast output. It is the date range, with a remaining bottle
count, within which the next service falls due. It is computed from the learned
service interval counted down by the service counter. Condition signals, such as
a worsening fault-rate trend or Performance degradation, pull it **earlier
only**, and the reason is always stated. Like every future quantity in LineLens
it is a band, never a confident date.
_Avoid_: maintenance date, next service at, countdown

**Trend**:
The straight-line direction the period's daily production is moving. It is fit
by ordinary least squares on the dated daily good-parts series. See ADR-0006. It
is drawn as a dashed line. It summarizes where the data is heading. It does not
measure any one day.
_Avoid_: forecast, prediction, regression line (to a reader), best fit

**Service counter**:
The maintenance trip counter. It is the bottles produced since the last service
event, counted from the incremental `good_count` and `reject_count` of the
intervals after it. Production volume was chosen over calendar time or run-hours
because a line can sit powered down, accruing neither wear nor bottles. Volume is
the truest analogue of a car's kilometers, and it matches the machine's own
`Bottles_Counter` odometer. The maintenance forecast counts the service counter
down against the learned service interval.
_Avoid_: maintenance hours, time since service

**Forecast band**:
The plus or minus one sigma shaded ribbon around the trend's extrapolation. It is
the only place uncertainty appears. See ADR-0002. It is a widening prediction
interval, and it grows with the horizon, because the further ahead you look the
less the past determines the future. The band is the forecast, not the trend
line. A future day is always shown as a range inside it, never as a single
confident number.
_Avoid_: confidence interval, error bar, prediction (unqualified), forecast value

**Horizon**:
How far the trend is extrapolated past the last observed day, which is 7 calendar
days. See ADR-0006. A projection needs at least 7 observed daily points to draw
at all. With fewer, the chart says so rather than invent a line.
_Avoid_: lookahead, forecast window, lead time

**Projection**:
The deterministic fallback forecast. It is an arithmetic read-out of where the
data is heading, extrapolating the recent direction with a widening band. It is
deliberately not a *prediction*: it states no confident future number, and it
assumes the recent trend continues. It is used when there is too little history
to train a Forecast. See ADR-0007. With enough data the learned Forecast
replaces it.
_Avoid_: prediction, estimate (of a future value)

**Forecast**:
The learned prediction of a future daily series, which is production. It is a
gradient-boosted model with a conformal-calibrated band, trained on history,
unlike a Projection. It is always emitted as a range with a *measured* coverage
guarantee, never as a single confident number. It is drawn only with enough
history, roughly 3 months or more. Otherwise the deterministic Projection is
used. Do not confuse it with the **Forecast band** entry above, which is the
Projection's own one sigma ribbon. See ADR-0006 and ADR-0007.
_Avoid_: point prediction, confident number, the AI predicts
