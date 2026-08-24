# OEE: Availability scope, the `planned` flag, and bottles lost

## Status

Accepted (2026-07-23, M4). Implements plan row 4 ("OEE module") and pins the
formulas the M4 `linelens/oee.py` computes. Supersedes nothing — ADR-0001
(grain) and ADR-0002 (deterministic prediction) stand; this one fills in the
KPI arithmetic.

## Context

M4 introduces the first real KPI computation in v2.5: Availability,
Performance, Quality, and OEE from the event-interval frame, plus the
"bottles lost" impact currency (CONTEXT.md) that M5's Pareto and M6's what-if
report in. Two questions had to be decided *before* code, because the dataset
and the downstream milestones both depend on the answer:

1. **Where does `Idle` sit in Availability?** The dataset has a small Idle
   component (~75,730s ≈ 0.9% of the month: short buffer/waiting fillers —
   *not* Starvation/Buildup, which the generator captures as `Stopped`+cause).
   Standard OEE treats scheduled production time not spent running as an
   Availability loss; the generator's `summarize()` instead excluded Idle.
2. **What does the `planned` flag exclude, and from what?** The flag marks
   scheduled stops (Changeover in this dataset). Availability must not penalize
   scheduled maintenance; Performance is only defined over Running rows; the
   `planned`/unplanned split is the lever M6's what-if sliders turn.

The formulas also had to be pinned so the M4 narrowest check — "KPI values
match a hand-computed sample" — has something to match against.

## Decision

We adopt **strict OEE**: Idle is an Availability loss, and the `planned` flag
excludes only *planned* stops from the Availability denominator.

```
Availability = run_time / (run_time + unplanned_stop_time + idle_time)
```

where:

- `run_time` = Σ duration over rows with `state == Running`.
- `unplanned_stop_time` = Σ duration over rows with a stop cause **and**
  `planned` is not True (False or NA). This is the downtime Availability
  *should* penalize.
- `idle_time` = Σ duration over rows with `state == Idle`.
- **Planned stops** (`planned == True`, e.g. Changeover) are dropped from the
  denominator entirely — scheduled maintenance is not downtime Availability
  measures. They still appear in the time breakdown for transparency.

The `planned` mask is read from `ctx.data['planned']` (the coerced nullable
`boolean`), so a blank planned flag is NA and treated as *unplanned* (the
conservative choice: an unknown schedule status is a loss, not a free pass).
This is the only place the NA semantics matter; M3's data has no blanks.

```
Performance = Σ(speed_actual · duration) / Σ(speed_target · duration)   over Running rows
```

Time-weighted over Running rows only (speed is bottles/hr; durations in
seconds, so the 3600 cancels in the ratio — we keep seconds throughout to
avoid a units round-trip and document this). With `good_count =
speed_actual · duration / 3600` in this dataset, `P ≈ good / (target·run_time)`;
we use the speed-integral form because it stays exact even when `good_count`
is rounded (the generator rounds `good_count`), and because M6 needs the same
form when it perturbs *speed*, not counts. Empty Running (no run time) →
Performance is **0.0**, not NaN — there is no run to perform against, and a
0 keeps OEE a clean product without poisoning downstream rendering.

```
Quality = good / (good + reject)
```

`good`/`reject` summed over all rows (incremental-by-convention; the
aggregation-problem diagnostic in `summaries` handles any cumulative counter
separately). No parts at all → Quality is **0.0** (same guard reasoning).

```
OEE = Availability · Performance · Quality
```

### Bottles lost (CONTEXT.md impact currency)

Per stop-cause: `bottles_lost = cause_time_lost × weighted_target_speed`, where
`cause_time_lost` is the cause's unplanned downtime seconds and
`weighted_target_speed` is the duration-weighted mean of `speed_target` over
that cause's rows, converted to bottles/sec (÷3600). Duration-weighting
handles multi-recipe datasets where a cause's rows span different targets
(this dataset has two recipes at 2200 and 2400 bottles/hr); for a single
target it collapses to the obvious `secs · target / 3600`.

Bottles lost is computed for **unplanned** causes only — a planned Changeover
isn't "lost" production, it's scheduled. (The math still reports it in the
time breakdown; it's just not priced as a loss.) This is the output M5 renders
on the Pareto y-axis and M6's what-if reports improvement in; the *computation*
belongs to M4 so M6 can re-price under hypothetical downtime without
re-deriving it.

### The compute is pure and recomputable

The KPI core is a pure function of plain numeric inputs
(`(durations_by_state, durations_by_cause, planned_mask, speed_actual,
speed_target, good, reject) -> OEE result`), **not** a method on a context.
This is deliberate: M6 (what-if sliders) and M7 (banded forecast) feed it
hypothetical downtime/speed numbers without rebuilding a `ValidationContext`.
A thin `oee_from_context(ctx)` wrapper reuses `summaries._event_durations` +
`ctx.data`/`ctx.mapping` to produce those inputs from a real loaded dataset —
that's the convenience path; the pure core is the contract the what-if holds.

## Consequences

- **Availability reads ~2.6 points lower than the generator's `summarize()`.**
  The generator used choice 2 (`A = run / (run + unplanned)`, Idle excluded).
  Strict OEE adds Idle to the denominator, so on `fictional_month.csv` the
  canonical A ≈ 0.889 vs the generator's ballpark 0.915 (OEE ≈ 0.802 vs
  0.825). Same order of magnitude; the difference is exactly the Idle
  treatment, which is the decision this ADR makes. The hand-computed M4 test
  fixtures match the *canonical* (strict) form, not the generator's.
- **Idle is never free.** A line that idles a lot will see Availability fall,
  which is the textbook behavior and what a "where is my time going" tool
  should surface. If a future user wants the generator's looser definition,
  the time breakdown (run / unplanned / planned / idle seconds) is exposed on
  the result so the looser A is one ratio away — but the default stays strict.
- **`planned == NA` is treated as unplanned** (conservative loss). Acceptable
  today (M3 data has no blanks); revisit if real exports carry blank planned
  flags and that turns out to mean "scheduled."
- **No re-load, no re-coerce.** `oee_from_context` consumes `ctx.data` (the
  coerced frame) and `ctx.mapping`, exactly like `summaries.summarize`. The
  OEE module owns KPIs; `summaries` owns totals/aggregation diagnostics. They
  share `_event_durations` rather than duplicating it.
- **No app/UI wiring in M4.** KPI card tiles + Pareto are M5. M4 ships the
  computation and its tests only.
