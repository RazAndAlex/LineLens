"""What-if model (M6): deterministic OEE re-pricing under hypothetical downtime.

The "predictive model" what-if half of ADR-0002: each of the Pareto's top stop
causes becomes a slider, and dragging it cuts that cause's unplanned downtime by
a fraction ``r``, recomputing OEE → bottles live off the M4 pure core. No ML, no
randomness — pure arithmetic. The banded trend forecast (M7) is the only place
uncertainty appears; it is not this module.

Two entry points, mirroring ``linelens.oee``:

* ``perturb(arrays, reductions)`` — the **pure** what-if core: a function of the
  aligned per-row arrays plus a ``{cause: r}`` map. It rebuilds the arrays and
  re-runs ``compute_oee``, so it stays unit-testable without a context or the
  ``ui`` extra.
* ``whatif_from_context(ctx, reductions)`` — the convenience path: pulls the
  baseline arrays via ``oee._arrays_from_context`` (shared with
  ``oee_from_context``) and delegates to ``perturb``. Returns ``None`` under the
  same conditions as ``oee_from_context`` (no duration axis / no STATE).

Freed-time semantics (ADR-0005): the seconds freed by cutting a cause become
run time at the line's **current effective speed**, so Performance and Quality
are held at the baseline while Availability / OEE / good / bottles-lost move.
We reject "freed time runs at target speed" — it has no physical basis (a
line that stops starved doesn't run *faster* once fed) and would double-count
the gain by raising Performance too.
"""
from __future__ import annotations

import pandas as pd

from .oee import _RUNNING, _arrays_from_context, compute_oee

# Label appended for the single synthetic "freed time" Running row. A string so
# it never collides with a real (integer) row index regardless of the frame.
_FREED_LABEL = "__whatif_freed__"


def perturb(
    state: pd.Series,
    stop_cause: pd.Series,
    duration: pd.Series,
    planned: pd.Series | None,
    speed_target: pd.Series,
    speed_actual: pd.Series,
    good: pd.Series,
    reject: pd.Series,
    reductions: dict[str, float],
    duration_source: str | None = None,
):
    """Recompute OEE under a what-if: cut each cause's unplanned downtime.

    Each ``reductions`` entry ``{cause: r}`` shrinks that cause's unplanned-stop
    row durations by ``(1 - r)`` (``r`` clamped to ``[0, 1]``). The freed
    seconds become one synthetic Running row priced at the line's effective
    actual/target speeds and split at the baseline quality ratio, then the whole
    thing is fed back through ``compute_oee``. Performance and Quality are held
    at the baseline (~1e-12: the algebra is exact, but Quality can drift one
    IEEE ULP ~1e-16 in multi-recipe sums); Availability / OEE / good /
    bottles-lost move (ADR-0005). Empty/zero/absent-cause reductions are a
    no-op: the result is byte-identical to ``compute_oee`` on the same arrays.

    The held-P/Q guarantee assumes ``run_time > 0`` and ``parts > 0`` (otherwise
    the result is ``compute_oee``'s degenerate-with-note path, not a real ratio
    preserved by construction) and that rows are exclusively Running or
    stopped-with-cause — the same data-quality assumption ``compute_oee`` makes.
    """
    # Align + coerce to a common index, mirroring compute_oee so the reduction
    # masks select exactly the rows compute_oee would price as unplanned.
    duration = pd.to_numeric(pd.Series(duration), errors="coerce")
    index = duration.index
    state = pd.Series(state).astype("string").reindex(index)
    stop_cause = pd.Series(stop_cause).astype("string").reindex(index)
    speed_target = pd.to_numeric(pd.Series(speed_target), errors="coerce").reindex(index)
    speed_actual = pd.to_numeric(pd.Series(speed_actual), errors="coerce").reindex(index)
    good = pd.to_numeric(pd.Series(good), errors="coerce").reindex(index)
    reject = pd.to_numeric(pd.Series(reject), errors="coerce").reindex(index)
    if planned is None:
        planned_mask = pd.Series(False, index=index)
    else:
        planned_mask = pd.Series(planned).reindex(index).fillna(False).astype(bool)

    state_lower = state.str.strip().str.lower()
    has_cause = stop_cause.notna() & (stop_cause.str.strip() != "")
    valid_duration = duration > 0
    is_running = state_lower == _RUNNING
    is_unplanned_stop = has_cause & ~planned_mask & valid_duration

    # Scale each reduced cause's unplanned durations; collect the freed time.
    # Float working copy: a fractional (1 - r) scale must hold non-integral
    # seconds, and the source duration column is often int64 (pandas-3 refuses
    # to silently upcast on assignment).
    new_duration = duration.astype(float)
    freed = 0.0
    for cause, raw_r in reductions.items():
        r = min(max(float(raw_r), 0.0), 1.0)  # clamp to [0, 1]
        if not r:
            continue
        # Match compute_oee's grouping key (the raw stop_cause value), so the
        # reduction targets exactly the rows priced under that cause.
        mask = is_unplanned_stop & (stop_cause == cause)
        secs = float(duration[mask].sum())
        if secs <= 0:
            continue  # absent cause, or a planned cause (no unplanned rows)
        # ponytail: scale every matching row by (1 - r). Preserves the cause's
        # duration-weighted target speed, so its bottles-lost drops by exactly r.
        new_duration.loc[mask] = duration[mask] * (1.0 - r)
        freed += r * secs

    common = {
        "state": state, "stop_cause": stop_cause, "planned": planned_mask,
        "speed_target": speed_target, "speed_actual": speed_actual,
        "good": good, "reject": reject, "duration_source": duration_source,
    }
    if freed <= 0:
        # No reductions moved anything -> the baseline arrays, unchanged.
        return compute_oee(duration=duration, **common)

    # Effective speeds over the baseline Running rows (duration-weighted means).
    # actual_eff / target_eff == baseline Performance by construction, so the
    # appended row leaves Performance exactly unchanged (ADR-0005 decision 2).
    run_time = float(duration[is_running & valid_duration].sum())
    perf_num = float((speed_actual * duration)[is_running & valid_duration].sum())
    perf_den = float((speed_target * duration)[is_running & valid_duration].sum())
    actual_eff = perf_num / run_time if run_time > 0 else 0.0
    target_eff = perf_den / run_time if run_time > 0 else 0.0
    parts_total = float(good.sum()) + float(reject.sum())
    q_base = float(good.sum()) / parts_total if parts_total > 0 else 0.0

    # The freed time produces parts at the effective actual speed, split at the
    # baseline quality ratio -> Quality is held (good/reject scale alike; ~1e-12).
    parts_added = freed * actual_eff / 3600.0

    def _ext(s, val):
        return pd.concat([s, pd.Series([val], index=[_FREED_LABEL])])

    return compute_oee(
        state=_ext(state, "Running"),
        stop_cause=_ext(stop_cause, pd.NA),
        duration=_ext(new_duration, freed),
        planned=planned_mask,  # reindexed inside compute_oee; freed row -> NaN -> False
        speed_target=_ext(speed_target, target_eff),
        speed_actual=_ext(speed_actual, actual_eff),
        good=_ext(good, parts_added * q_base),
        reject=_ext(reject, parts_added * (1.0 - q_base)),
        duration_source=duration_source,
    )


def spread_recovered(horizon_values, recovered: float) -> list[float]:
    """Spread ``recovered`` bottles across the horizon proportional to each day's
    forecast level (M8 node 4): ``out[d] = v[d] + recovered · v[d] / Σ_h v``.

    Proportional to the forecast → the what-if line stays parallel to the forecast
    *shape* (a low weekend day gets a smaller bump, a high weekday a bigger one),
    preserving the weekly rhythm. Pure: no context, no UI, no randomness — a
    function of the horizon's forecast levels + a scalar, so it is unit-testable
    without the ``ui`` extra, like ``perturb``. The returned series is what the
    future-line chart overlays as the hypothetical "what-if" line.

    Edge cases (pinned by tests in ``tests/test_whatif.py``):
    - *empty horizon* → ``[]`` (no days to spread across).
    - *recovered == 0* → the horizon levels unchanged (zero-slider → the
      what-if line coincides with the forecast, the correct baseline view).
    - *Σ horizon == 0* → a zero-level forecast can't be proportioned, so the
      recovered bottles distribute *flatly* (``recovered / len(horizon)`` each);
      avoids a divide-by-zero while still summing to ``recovered``.

    The output is *not* clipped at zero: the what-if line is the forecast plus a
    non-negative addend, so it can only go negative when the forecast itself does
    — and ADR-0006 holds that a line crossing zero is the honest "this trend is
    unsustainable" signal, not something to hide. Clipping would also break the
    exact invariant below.

    The bridge invariant the lever waterfall also relies on:
    ``Σ out[d] − Σ horizon_values == recovered`` exactly for every non-empty,
    non-zero-sum input — the spread adds back exactly the recovered bottles,
    with no float drift (it is linear in ``recovered``).
    """
    vals = [float(v) for v in horizon_values]
    if not vals:
        return []
    total = sum(vals)
    if recovered == 0.0:
        return vals
    if total <= 0.0:
        # zero (or net-negative) forecast level: can't proportion -> flat spread.
        # per is >= 0 (recovered >= 0, len > 0), so the max(0,.) is defensive only.
        per = recovered / len(vals)
        return [max(0.0, per) for _ in vals]
    return [v + recovered * v / total for v in vals]


def whatif_from_context(ctx, reductions: dict[str, float]):
    """Recompute OEE from a loaded context under a what-if (convenience path).

    Pulls the baseline per-row arrays via ``oee._arrays_from_context`` (the same
    extraction ``oee_from_context`` uses) and delegates to ``perturb``. Returns
    ``None`` when the KPIs are undefined (no duration axis / no STATE), mirroring
    ``oee_from_context``; with empty ``reductions`` the result reproduces
    ``oee_from_context`` exactly.
    """
    arrays = _arrays_from_context(ctx)
    if arrays is None:
        return None
    state, stop_cause, duration, planned, speed_target, speed_actual, good, reject, ds = arrays
    return perturb(
        state, stop_cause, duration, planned, speed_target, speed_actual, good, reject,
        reductions, duration_source=ds,
    )
