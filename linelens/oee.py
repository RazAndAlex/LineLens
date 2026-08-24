"""OEE module: Availability / Performance / Quality / OEE + bottles lost (M4).

Computes the four KPIs from the event-interval frame and the per-stop-cause
"bottles lost" impact currency (CONTEXT.md) that M5's Pareto and M6's what-if
report in. The formulas and the Idle/`planned` decisions are pinned in
``docs/adr/0003-oee-availability-scope.md``; read that for the reasoning.

Two entry points:

* ``compute_oee(...)`` — the **pure KPI core**: a function of aligned per-row
  arrays. It re-runs under any inputs, so M6 (what-if sliders) and M7 (banded
  forecast) feed it hypothetical downtime/speed without rebuilding a context.
* ``oee_from_context(ctx)`` — the convenience path: pulls the per-row inputs
  from a loaded, coerced ``ValidationContext`` (the same one ``summaries``
  builds), reusing ``summaries._event_durations`` for the duration axis.

Availability is strict OEE: ``A = run / (run + unplanned_stops + idle)``, with
planned stops (``planned == True``) excluded from the denominator. Empty
Running → Performance 0.0; no parts → Quality 0.0 (never NaN, so OEE stays a
clean product). Bottles lost is priced for **unplanned** causes only, at the
duration-weighted target speed of each cause's rows.

The module owns KPIs; ``summaries`` owns totals + aggregation diagnostics.
They share ``_event_durations`` rather than duplicating it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .models import CanonicalRole
from .summaries import _event_durations
from .validation import ValidationContext

_SECONDS_PER_HOUR = 3600.0

# States that carry meaning for the KPI math. Matched case-insensitively on
# the coerced `state` column, the same convention `summaries` groups by.
_RUNNING = "running"
_IDLE = "idle"


@dataclass(frozen=True)
class BottlesLost:
    """Bottles lost attributed to one stop cause (unplanned only)."""

    cause: str
    seconds_lost: float  # unplanned downtime seconds for this cause
    weighted_target: float  # duration-weighted mean speed_target (bottles/hr)
    bottles: float  # seconds_lost * weighted_target / 3600


@dataclass(frozen=True)
class OEEResult:
    """The four KPIs plus the time breakdown and per-cause bottles lost.

    ``duration_source`` records where the duration axis came from, mirroring
    ``summaries.SummaryReport``. For empty/degenerate inputs (no run time, no
    parts) the KPI fields yield 0.0, never NaN, so OEE = A * P * Q is a clean
    product. Values are in [0, 1] for non-negative, finite inputs; corrupt
    inputs (negative counts, infinite speeds) are not clamped here and are
    expected to be caught upstream (e.g. ``NEGATIVE_DURATION`` in
    ``validation``).
    """

    availability: float
    performance: float
    quality: float
    oee: float
    # The time breakdown, in seconds, that the KPIs were computed from. Exposed
    # so M5 can label cards and so the looser (generator-style) Availability is
    # one ratio away if a future user wants it.
    run_time: float
    unplanned_stop_time: float
    planned_stop_time: float
    idle_time: float
    good: float
    reject: float
    bottles_lost: tuple[BottlesLost, ...] = field(default_factory=tuple)
    duration_source: str | None = None
    # Why the result might be degenerate (e.g. "no Running rows"), for callers
    # that want to render a "not enough data" state instead of a bare 0%.
    notes: tuple[str, ...] = field(default_factory=tuple)


def compute_oee(
    state: pd.Series,
    stop_cause: pd.Series,
    duration: pd.Series,
    planned: pd.Series | None,
    speed_target: pd.Series,
    speed_actual: pd.Series,
    good: pd.Series,
    reject: pd.Series,
    duration_source: str | None = None,
) -> OEEResult:
    """Compute A/P/Q/OEE + per-cause bottles lost from aligned per-row arrays.

    Every array must share one index (one entry per event interval). ``state``,
    ``stop_cause`` are string-valued; ``duration``, ``speed_*``, ``good``,
    ``reject`` numeric; ``planned`` is a nullable boolean (True/False/NA), or
    None when the `planned` role isn't mapped (treated as all-unplanned). NaN
    durations are skipped (pandas skipna). Pure and re-runnable: pass modified
    arrays to recompute under a what-if. See ADR-0003 for the formulas.
    """
    # Align everything to the duration index and coerce to the dtypes the math
    # needs. Index alignment is intentional — M6 may pass a sub-frame.
    duration = pd.to_numeric(pd.Series(duration), errors="coerce")
    index = duration.index
    state = pd.Series(state).astype("string").reindex(index)
    stop_cause = pd.Series(stop_cause).astype("string").reindex(index)
    speed_target = pd.to_numeric(pd.Series(speed_target), errors="coerce").reindex(index)
    speed_actual = pd.to_numeric(pd.Series(speed_actual), errors="coerce").reindex(index)
    good = pd.to_numeric(pd.Series(good), errors="coerce").reindex(index)
    reject = pd.to_numeric(pd.Series(reject), errors="coerce").reindex(index)
    if planned is None:
        # `planned` role unmapped → every stop is unplanned (no scheduled
        # exclusion). Modeled as all-False so the planned mask is empty.
        planned_mask = pd.Series(False, index=index)
    else:
        planned_series = pd.Series(planned).reindex(index)
        # Nullable boolean: True stays True; False or NA -> not planned
        # (conservative — an unknown schedule status is a loss, not a free
        # pass; ADR-0003). fillna collapses NA to False so the boolean mask is
        # NA-free for the `&` / `~` ops below.
        planned_mask = planned_series.fillna(False).astype(bool)

    state_lower = state.str.strip().str.lower()

    has_cause = stop_cause.notna() & (stop_cause.str.strip() != "")
    is_running = state_lower == _RUNNING
    is_idle = state_lower == _IDLE

    # Only positive durations count toward time-based KPIs. This excludes NaN
    # (already skipna'd in sums, but kept out of the masks for consistency),
    # negative durations (invalid — they would push KPIs outside [0,1] and are
    # flagged by the NEGATIVE_DURATION rule in the real-data path), and
    # zero-duration rows (contribute 0 to every sum, so excluding them is a
    # no-op for the KPIs — but it keeps a 0-duration stop cause from producing
    # a NaN bottles-lost entry via a 0/0 weighted target). See ADR-0003.
    valid_duration = duration > 0
    negative_duration_rows = int((duration < 0).sum())

    run_time = float(duration[is_running & valid_duration].sum())
    idle_time = float(duration[is_idle & valid_duration].sum())

    # Planned stops are dropped from the Availability denominator entirely;
    # unplanned stops are the downtime Availability penalizes.
    is_planned_stop = has_cause & planned_mask & valid_duration
    is_unplanned_stop = has_cause & ~planned_mask & valid_duration
    planned_stop_time = float(duration[is_planned_stop].sum())
    unplanned_stop_time = float(duration[is_unplanned_stop].sum())

    # Availability (strict OEE): run / (run + unplanned + idle).
    avail_den = run_time + unplanned_stop_time + idle_time
    availability = run_time / avail_den if avail_den > 0 else 0.0

    # Performance: time-weighted actual vs target over Running rows. Speeds are
    # bottles/hr, durations seconds; the 3600 cancels in the ratio, so we keep
    # seconds and skip the unit round-trip (documented in ADR-0003).
    perf_num = float((speed_actual * duration)[is_running & valid_duration].sum())
    perf_den = float((speed_target * duration)[is_running & valid_duration].sum())
    performance = perf_num / perf_den if perf_den > 0 else 0.0

    # Quality: good / (good + reject), summed over all rows.
    good_total = float(good.sum())
    reject_total = float(reject.sum())
    parts = good_total + reject_total
    quality = good_total / parts if parts > 0 else 0.0

    oee = availability * performance * quality

    notes: list[str] = []
    if negative_duration_rows:
        notes.append(
            f"{negative_duration_rows} row(s) with negative duration excluded from KPIs"
        )
    if avail_den == 0:
        notes.append("no run, stop, or idle time — Availability undefined (0.0)")
    if perf_den == 0:
        # perf_den is Σ(target·dur) over Running rows; it is 0 either when
        # there is no positive-duration Running time, or when Running rows
        # exist but carry no target throughput. Distinguish so a caller doesn't
        # render a false "no run" message over a real run with zero target.
        if run_time == 0:
            notes.append("no Running time — Performance undefined (0.0)")
        else:
            notes.append(
                "Running rows have zero target throughput — Performance undefined (0.0)"
            )
    if parts == 0:
        notes.append("no parts produced — Quality undefined (0.0)")

    bottles_lost = _bottles_lost(
        duration, stop_cause, speed_target, is_unplanned_stop
    )

    return OEEResult(
        availability=availability,
        performance=performance,
        quality=quality,
        oee=oee,
        run_time=run_time,
        unplanned_stop_time=unplanned_stop_time,
        planned_stop_time=planned_stop_time,
        idle_time=idle_time,
        good=good_total,
        reject=reject_total,
        bottles_lost=bottles_lost,
        duration_source=duration_source,
        notes=tuple(notes),
    )


def _bottles_lost(
    duration: pd.Series,
    stop_cause: pd.Series,
    speed_target: pd.Series,
    is_unplanned_stop: pd.Series,
) -> tuple[BottlesLost, ...]:
    """Per-cause bottles lost for unplanned causes, sorted by bottles desc.

    bottles = cause_seconds * (Σ(target·dur) / Σ(dur)) / 3600 — the cause's
    downtime priced at the duration-weighted target speed of its own rows
    (handles multi-recipe). Planned causes are excluded (a Changeover isn't
    lost production). Sorted descending by bottles so M5's Pareto gets a ready
    ranking; ties break on cause name for deterministic order.
    """
    if not is_unplanned_stop.any():
        return ()
    cause = stop_cause[is_unplanned_stop]
    dur = duration[is_unplanned_stop]
    tgt = speed_target[is_unplanned_stop]
    seconds_by_cause = dur.groupby(cause).sum()
    # duration-weighted mean target per cause: Σ(target·dur)/Σ(dur)
    weighted = (tgt * dur).groupby(cause).sum() / seconds_by_cause
    rows: list[BottlesLost] = []
    for cause_name in seconds_by_cause.index:
        secs = float(seconds_by_cause[cause_name])
        wt = float(weighted[cause_name])
        rows.append(
            BottlesLost(
                cause=str(cause_name),
                seconds_lost=secs,
                weighted_target=wt,
                bottles=secs * wt / _SECONDS_PER_HOUR,
            )
        )
    rows.sort(key=lambda b: (-b.bottles, b.cause))
    return tuple(rows)


def _arrays_from_context(
    ctx: ValidationContext,
) -> tuple | None:
    """The aligned per-row arrays ``compute_oee`` needs, pulled from a loaded,
    coerced ``ValidationContext``.

    Returns ``(state, stop_cause, duration, planned, speed_target,
    speed_actual, good, reject, duration_source)`` or ``None`` when the KPIs are
    undefined — no duration axis (no DURATION column and no start/end pair), or
    no STATE column. Optional roles default to zero-filled / NA-filled series so
    the pure core yields a 0.0-with-note rather than crashing (see
    ``compute_oee``). Shared by ``oee_from_context`` and
    ``whatif.whatif_from_context`` so the "arrays from a context" extraction has
    one source of truth — and the what-if baseline (empty reductions) is
    byte-identical to the OEE baseline.
    """
    durations, duration_source = _event_durations(ctx)
    if durations is None:
        return None
    data = ctx.data

    def _src_col(role: CanonicalRole) -> pd.Series | None:
        name = ctx.mapping.source_for(role)
        return data[name] if name is not None and name in data.columns else None

    state = _src_col(CanonicalRole.STATE)
    # Without state the Availability split is impossible; the KPIs are blank.
    if state is None:
        return None

    stop_cause = _src_col(CanonicalRole.STOP_CAUSE)
    speed_target = _src_col(CanonicalRole.SPEED_TARGET)
    speed_actual = _src_col(CanonicalRole.SPEED_ACTUAL)
    good = _src_col(CanonicalRole.GOOD_COUNT)
    reject = _src_col(CanonicalRole.REJECT_COUNT)
    planned = _src_col(CanonicalRole.PLANNED)

    # Speeds/counts are required for Performance/Quality; if unmapped, pass
    # zeros so the guard yields a 0.0-with-note rather than crashing.
    if speed_target is None:
        speed_target = pd.Series(0.0, index=data.index)
    if speed_actual is None:
        speed_actual = pd.Series(0.0, index=data.index)
    if good is None:
        good = pd.Series(0.0, index=data.index)
    if reject is None:
        reject = pd.Series(0.0, index=data.index)
    if stop_cause is None:
        stop_cause = pd.Series(pd.NA, index=data.index, dtype="string")

    return (
        state, stop_cause, durations, planned,
        speed_target, speed_actual, good, reject, duration_source,
    )


def oee_from_context(ctx: ValidationContext) -> OEEResult | None:
    """Compute OEE from a loaded, coerced ValidationContext.

    Reuses ``summaries._event_durations`` for the duration axis and reads the
    per-row columns from ``ctx.data`` via ``ctx.mapping`` — no re-load, no
    re-coerce. Returns None when the duration axis can't be derived (no
    DURATION column and no start/end timestamps mapped) or there is no STATE
    column, since the KPIs are time- and state-based and meaningless without
    them. The array extraction lives in ``_arrays_from_context``, shared with
    the what-if path.
    """
    arrays = _arrays_from_context(ctx)
    if arrays is None:
        return None
    return compute_oee(*arrays)


def performance_by_day(ctx: ValidationContext) -> pd.DataFrame | None:
    """The duration-weighted Performance ratio per calendar day (ADR-0003/0005).

    The same Performance identity as ``compute_oee`` —
    ``Σ(speed_actual·dur) / Σ(speed_target·dur)`` over Running rows with positive
    duration — grouped by the start timestamp's calendar day. Returns a tidy
    ``[date, performance]`` frame sorted by date, one row per day that has Running
    time with positive target throughput; days whose target throughput is zero
    (Performance undefined) are dropped, matching the overall KPI's degenerate
    path rather than emitting a misleading 0.0.

    ``None`` when the KPIs are undefined (``_arrays_from_context`` returns None:
    no duration axis or no STATE) or no start timestamp is mapped (can't group by
    day). The mask and defensive coercion mirror ``compute_oee`` exactly, so a
    single-day context yields the same Performance as ``oee_from_context`` —
    pinned by a cross-check in ``tests/test_oee.py``. M8's Act-4 degradation
    forecast consumes this series; it must not disagree with the Now-section KPI.

    pandas-only (no ``ui`` extra): unit-testable like ``compute_oee``.
    """
    arrays = _arrays_from_context(ctx)
    if arrays is None:
        return None
    state, _cause, duration, _planned, speed_target, speed_actual, _g, _r, _ds = arrays
    start_src = ctx.mapping.source_for(CanonicalRole.TIMESTAMP_START)
    if start_src is None or start_src not in ctx.data.columns:
        return None
    # Mirror compute_oee's coercion + Running/valid mask (ADR-0003) so the per-day
    # ratio is the same identity as the overall KPI, byte-for-byte on one day.
    duration = pd.to_numeric(pd.Series(duration), errors="coerce")
    speed_target = pd.to_numeric(pd.Series(speed_target), errors="coerce")
    speed_actual = pd.to_numeric(pd.Series(speed_actual), errors="coerce")
    state_lower = pd.Series(state).astype("string").str.strip().str.lower()
    day = ctx.data[start_src].dt.floor("D")
    run = (state_lower == _RUNNING) & (duration > 0) & day.notna()
    num = (speed_actual * duration).where(run, 0.0)
    den = (speed_target * duration).where(run, 0.0)
    g_num = num.groupby(day).sum()
    g_den = den.groupby(day).sum()
    frame = pd.DataFrame({"date": g_den.index, "num": g_num.values, "den": g_den.values})
    frame = frame[frame["den"] > 0].sort_values("date").reset_index(drop=True)
    frame["performance"] = frame["num"] / frame["den"]
    return frame[["date", "performance"]]
