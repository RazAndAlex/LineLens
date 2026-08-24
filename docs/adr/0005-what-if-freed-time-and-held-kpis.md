# What-if: freed-time semantics and the held-vs-live KPIs

## Status

Accepted (2026-07-23, M6). Implements plan row 6 ("What-if model + sliders fed
by the Pareto's top causes") and pins the arithmetic `linelens/whatif.py`
computes. Supersedes nothing. ADR-0002 (deterministic prediction) and
ADR-0003 (OEE formulas) stand. This one fills in the what-if half.

## Context

M6 turns the Pareto's biggest bars into sliders: "what if we cut Starvation
downtime by X%?" The slider change must recompute OEE → bottles live, off the
M4 pure `compute_oee` core (ADR-0003), without rebuilding a `ValidationContext`.
Four questions had to be decided *before* code, because the dataset, the UI,
and the test oracle all depend on the answer:

1. **Where does freed time go?** Cutting a cause's downtime frees seconds.
   Standard what-if says they become productive time. But *productive at what
   speed*? "At target speed" (the line runs perfectly) raises Performance as
   well as Availability. "at the line's current speed" raises only Availability.
2. **What moves and what's held?** Reducing downtime obviously grows run time.
   Does `good` recompute? Does Performance re-derive, or stay at the baseline
   ratio? ADR-0003 computes Performance as a speed integral over Running rows.
   The answer determines whether the slider moves one KPI or three.
3. **Which causes get sliders, and how many?** Every priced cause, or only the
   Pareto's top bars? And can a `planned` cause (Changeover) ever be a lever?
4. **Where does the view plug in?** A new section after "4 · OEE" is cleanest,
   but it renumbers the sections below it.

The model also had to stay **deterministic** (ADR-0002): no randomness, no
learned model. The what-if is arithmetic. The banded forecast (M7) is the
only place uncertainty appears, and it is not M6.

## Decision

### 1. Freed time becomes run time at the line's current effective speed

When a cause's unplanned downtime shrinks by fraction `r`, the freed seconds
become **Running** time at the line's **duration-weighted actual speed** over
its existing Running rows (`actual_eff = Σ(actual·dur) / run_time`), producing
parts at the baseline quality ratio. We **reject** the alternative (freed time
runs at target speed): it has no physical basis and double-counts the gain
(raising both Availability *and* Performance), overstating the recoverable
bottles.

This is the physically correct model across every stop family: eliminating
*Starvation* (upstream empty), *Buildup* (downstream full), or *Supplies* means
the line runs **more**, not **faster.** The same filler at the same speed, just
without the gaps. Eliminating *Fault* / *Operator* / *External* likewise buys
run time at the machine's normal speed. In no case does removing a stop change
the line's speed envelope, so Performance must not move. (ADR-0002's phrase "run
time at target speed" is read as "productive run time," not "perfectly at
target". The operative clause there is "Performance ratio ~unchanged since
speeds don't move," which this decision honors exactly.)

### 2. Performance and Quality are held. Availability, OEE, good, bottles are live

Modeled by rebuilding the per-row arrays and re-running `compute_oee`
(ADR-0003):

- Each reduced cause's unplanned-stop row durations are scaled by `(1 - r)`.
  This preserves the cause's duration-weighted target speed, so its bottles-lost
  drops by **exactly** `r`. The recoverable bottles are a clean linear lever.
- The total freed seconds (`Σ r · cause_seconds`) are appended as **one
  synthetic Running row** carrying `actual_eff` / `target_eff` (the baseline
  running-row weighted means) and `good`/`reject` split at the baseline quality
  ratio.

Because `actual_eff / target_eff` equals the baseline Performance ratio by
construction, and the appended parts preserve the good/reject ratio, re-running
`compute_oee` yields **Performance and Quality held at baseline (~1e-12)**.
The algebra is exact. Performance lands bit-equal (a `·c`/`·c` multiplicative
identity), while Quality can drift one IEEE ULP (~1e-16) in multi-recipe sums
because its numerator and denominator accumulate in a different operation
order, which is well inside the tolerance. Meanwhile Availability rises (more
run time, less unplanned, and the denominator `run + unplanned + idle` is
invariant, since freed time moves from `unplanned` to `run`), OEE rises with
Availability, `good`
rises, and the reduced causes' bottles-lost fall. The math is coherent
end-to-end (the M6 oracle asserts P and Q held to `1e-12`).

The held-P/Q guarantee presumes `run_time > 0` and `parts > 0` (without run time
or parts there is no real ratio to preserve. The result is `compute_oee`'s
degenerate-with-note path, unreachable on the real dataset) and the standard
data-quality assumption that a row is exclusively Running or stopped-with-cause
(M3's rules are the upstream guard).

### 3. Sliders: top-5 of `bottles_lost`, one 0–100% reduction each. Planned causes never

One slider per cause in the top **5** of the baseline `OEEResult.bottles_lost`
(M4 already sorts it descending by bottles). The Pareto's whole point is that a
few causes drive most of the loss. On `fictional_month.csv` the top 5
(Starvation ≫ External > Buildup > Fault > Operator) are ~98% of recoverable
bottles, and the tail (Supplies, 6,431) is not an actionable lever. Each slider
is a 0–100% **reduction** in that cause's unplanned downtime.

**Planned causes are never sliders.** ADR-0003 already excludes them from
`bottles_lost` (a Changeover is scheduled, not lost production), so the top-N
set naturally excludes Changeover. And `whatif.perturb` only ever scales
**unplanned** stop rows, so even a reduction keyed on a planned cause name is a
no-op (there are no unplanned rows to scale). Scheduled maintenance is not a
loss lever.

### 4. Plug-in: a new "5 · What-if" section, Charts → 6, Export → 7

The what-if belongs immediately after the OEE cards + Pareto it perturbs
("here is the loss. Here is what would move it"), before the generic charts and
export. `app.py` gains a `_render_whatif` that renders the sliders, calls
`whatif.whatif_from_context(ctx, reductions)`, reuses the existing
`_render_kpi_cards` with the hypothetical `OEEResult` (so the live A/P/Q/OEE
tiles update as you drag), and adds a focused "bottles recovered vs baseline"
readout. The baseline is the `result["oee"]` M5 already stores. Consumed, not
recomputed.

## Consequences

- **Deterministic and pure.** `whatif.perturb(arrays, reductions) -> OEEResult`
  is a pure function of per-row arrays + a `{cause: r}` map. No context, no
  randomness. It lives in `linelens/` so it is unit-testable without the `ui`
  extra, exactly like `compute_oee`. A thin `whatif_from_context(ctx,
  reductions)` mirrors `oee_from_context` for the UI. Both share
  `oee._arrays_from_context` so the extraction has one source of truth and the
  what-if baseline (empty reductions) is byte-identical to the OEE baseline.
- **No re-load, no re-coerce, no context rebuild.** The what-if mutates copies
  of the baseline arrays and re-runs the pure core. The contract ADR-0003
  established precisely so M6 could do this.
- **The denominator is invariant. Availability moves one-for-one with freed
  time.** `A_new = (run_time + freed) / (run_time + unplanned + idle)`. The
  same denominator as baseline, because freed time leaves `unplanned` and enters
  `run`. This is the identity the M6 oracle checks.
- **Recoverable bottles are linear in `r` and additive across causes.**
  Reducing cause X by `r` recovers exactly `r · bottles_lost[X]`. Multiple
  sliders sum. The ceiling is the total unplanned bottles-lost (all sliders at
  100%), reachable because P/Q are held (the line can absorb the freed time at
  its current speed. The model assumes no new bottleneck appears, which is the
  known ceiling: a real line may hit a different constraint first).
- **No scenario save/load, no per-recipe or per-shift sliders.** The slider set
  is the whole-period top-5. That is the Pareto's message. Granular what-ifs
  (by shift, by recipe, persisted scenarios) are explicitly out of scope for
  row 6. Add when a real ask arrives.
- **Performance/Quality held is a modeling assumption, not a measurement.** It
  is the honest default (removing a stop doesn't speed the line), and the UI
  states it. If a user believes cutting a cause *would* change speed, that is a
  different what-if (a speed slider, M7+), not this one.
