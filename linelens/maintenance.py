"""Predictive maintenance (M9): service counter + learned due window (ADR-0009).

The CSV now carries labeled service events — `Maintenance` stops (the 8th stop
cause, always planned) and repair-length Faults (corrective service: "it broke
and they fixed it" genuinely refreshes the machine). This module turns them
into the car-style maintenance act:

* **service counter** — bottles produced since the last service event (the
  odometer; bottles, not hours, because a powered-down line accrues no wear);
* **service interval** — the learned rhythm: median + spread (IQR) of bottles
  between consecutive service events, never a bare number;
* **due window** — the interval counted down by the counter into a date range,
  pulled *earlier only* when condition signals (fault-rate surge, Performance
  degradation) worsen, with the reason always stated. Always a window, never a
  date — ADR-0002/0007's band ethic applied to maintenance.

Thin data (ADR-0009 decision 5): the counter always renders (pure arithmetic);
the interval and due window need >= 2 service events; below that the report
says so instead of inventing a default interval.

The split between routine faults and the repair tail is *learned*, not fixed:
a Tukey fence (q3 + 1.5*IQR) over the Fault durations — long repairs are
duration outliers by construction, so the fence separates them without a
hardcoded number.

Same purity contract as ``compute_oee`` / ``whatif.perturb`` / ``reliability``:
pandas + stdlib only (no ``ui``/``forecast`` extras), pure helpers over aligned
arrays plus one thin ``*_from_context`` wrapper. The app consumes the report;
it never recomputes.
"""
from __future__ import annotations

import itertools
import math
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from .models import CanonicalRole
from .validation import ValidationContext

# The stop-cause families a service event maps to (CONTEXT.md): Maintenance is
# the labeled planned service stop; Fault carries the repair tail. Matched
# case-insensitively on the coerced stop_cause column (reliability convention).
_SERVICE = "maintenance"
_FAULT = "fault"

# The repair/routine split is a Tukey fence over Fault durations. Fewer than
# 4 Faults -> no meaningful IQR -> no threshold -> Maintenance-only events
# (mirrors reliability._MIN_INTERVALS_FOR_BAND's "too few to summarize" floor).
_MIN_FAULTS_FOR_THRESHOLD = 4
_TUKEY_K = 1.5

# Condition-signal floors (ADR-0009 decision 4: earlier only, reason stated).
# ponytail: fixed floors, chosen conservative so ordinary jitter never fires
# them. _PERF_SLOPE_FLOOR is a Performance-ratio OLS slope of -0.05 pts/day
# (~-1.5 pts/month sustained); _FAULT_RATE_SURGE is a >= 25% rise of the recent
# 30-day faults-per-bottle rate vs the earlier baseline.
_PERF_SLOPE_FLOOR = -0.0005
_FAULT_RATE_SURGE = 1.25
_FAULT_RATE_RECENT_DAYS = 30

# Days of trailing daily production the due window's bottle->date conversion
# rates against (the line's current pace, not the whole-file average).
_RATE_WINDOW_DAYS = 14


@dataclass(frozen=True)
class ServiceEvent:
    """One labeled service event: a Maintenance stop or a repair-length Fault."""

    start: pd.Timestamp
    end: pd.Timestamp
    kind: str  # "maintenance" | "repair"
    duration_s: float


@dataclass(frozen=True)
class ServiceInterval:
    """The learned service rhythm: bottles between consecutive service events.

    Median + IQR, never a bare number. With exactly one observed gap (2 service
    events — the ADR-0009 floor) q1 == median == q3: the rhythm is learned but
    its spread is unknown, and ``n`` says so honestly.
    """

    median: float
    q1: float
    q3: float
    n: int  # observed bottles-between-services gaps (events - 1)


def repair_threshold(fault_durations) -> float | None:
    """The learned routine/repair split: q3 + 1.5*IQR over Fault durations.

    Long repairs are duration outliers among faults by construction (routine
    faults are minutes; corrective service is an hour-scale), so the Tukey
    fence separates the tail without a hardcoded duration. ``None`` when there
    are fewer than 4 Fault durations — the same minimum-count ethic as
    ``reliability.mtbf_band``'s 4-interval floor: too few to summarize
    honestly.
    """
    vals = sorted(float(v) for v in fault_durations if pd.notna(v) and v > 0)
    if len(vals) < _MIN_FAULTS_FOR_THRESHOLD:
        return None
    q1, _median, q3 = statistics.quantiles(vals, n=4, method="inclusive")
    return q3 + _TUKEY_K * (q3 - q1)


def service_events(ctx: ValidationContext, threshold: float | None) -> tuple[ServiceEvent, ...]:
    """The labeled service events, start-ordered: Maintenance stops + repair Faults.

    A Maintenance stop always counts (the planned service label). A Fault counts
    only when its duration clears ``threshold`` (the learned repair fence);
    ``threshold=None`` means no repair inference (too few Faults), so only
    Maintenance stops are events. Long stops of other causes never count — a
    2-hour Starvation is upstream's problem, not service on this machine.
    Returns ``()`` when no stop_cause/start/end basis is mapped.
    """
    cause_src = ctx.mapping.source_for(CanonicalRole.STOP_CAUSE)
    start_src = ctx.mapping.source_for(CanonicalRole.TIMESTAMP_START)
    end_src = ctx.mapping.source_for(CanonicalRole.TIMESTAMP_END)
    dur_src = ctx.mapping.source_for(CanonicalRole.DURATION)
    if cause_src is None or start_src is None:
        return ()
    if cause_src not in ctx.data.columns or start_src not in ctx.data.columns:
        return ()
    data = ctx.data
    cause = data[cause_src].astype("string").str.strip().str.lower()
    starts = pd.to_datetime(data[start_src], errors="coerce")
    if end_src and end_src in data.columns:
        ends = pd.to_datetime(data[end_src], errors="coerce")
    elif dur_src and dur_src in data.columns:
        ends = starts + pd.to_timedelta(
            pd.to_numeric(data[dur_src], errors="coerce"), unit="s")
    else:
        return ()
    durations = (ends - starts).dt.total_seconds()

    is_service = cause == _SERVICE
    is_repair = (
        (cause == _FAULT) & durations.notna() & (durations > threshold)
        if threshold is not None
        else pd.Series(False, index=data.index)
    )
    events: list[ServiceEvent] = []
    for idx in data.index[is_service | is_repair]:
        if pd.isna(starts[idx]) or pd.isna(ends[idx]):
            continue
        events.append(ServiceEvent(
            start=starts[idx], end=ends[idx],
            kind="maintenance" if is_service[idx] else "repair",
            duration_s=float(durations[idx]),
        ))
    events.sort(key=lambda e: e.start)
    return tuple(events)


# --- the counter + the learned rhythm ------------------------------------------


def _production_axis(ctx: ValidationContext) -> tuple[pd.Series, pd.Series] | None:
    """(row start timestamps, row produced bottles = good + reject), or None.

    Produced counts good AND reject: wear accrues on every bottle through the
    machine, not just the shippable ones (the counter is an odometer, and the
    machine's own ``Bottles_Counter`` doesn't subtract scraps either). None
    when no start timestamp is mapped or both count roles are unmapped — the
    counter is bottle arithmetic and undefined without bottles.
    """
    start_src = ctx.mapping.source_for(CanonicalRole.TIMESTAMP_START)
    if start_src is None or start_src not in ctx.data.columns:
        return None
    good_src = ctx.mapping.source_for(CanonicalRole.GOOD_COUNT)
    reject_src = ctx.mapping.source_for(CanonicalRole.REJECT_COUNT)

    def _col(src: str | None) -> pd.Series:
        if src is None or src not in ctx.data.columns:
            return pd.Series(0.0, index=ctx.data.index)
        return pd.to_numeric(ctx.data[src], errors="coerce").fillna(0.0)

    starts = pd.to_datetime(ctx.data[start_src], errors="coerce")
    return starts, _col(good_src) + _col(reject_src)


def bottles_between(ctx: ValidationContext, events: tuple[ServiceEvent, ...]) -> tuple[float, ...]:
    """Bottles produced between consecutive service events (the rhythm series).

    Gap ``i`` is the production on intervals starting in
    ``[events[i].end, events[i+1].start)`` — from the moment the line comes back
    up after one service to the moment it goes down for the next. Fewer than 2
    events -> ``()`` (no gap, nothing to learn).
    """
    axis = _production_axis(ctx)
    if axis is None or len(events) < 2:
        return ()
    starts, produced = axis
    gaps: list[float] = []
    for prev, nxt in itertools.pairwise(events):
        mask = (starts >= prev.end) & (starts < nxt.start)
        gaps.append(float(produced[mask].sum()))
    return tuple(gaps)


def service_counter(ctx: ValidationContext, events: tuple[ServiceEvent, ...]) -> float | None:
    """The service counter: bottles produced since the last service event ended.

    With no service event in the data, the whole file's production — an honest
    odometer reading over the observed window (the last service predates the
    file; the report's notes say so). ``None`` when the bottle axis is
    undefined (no start timestamp, or neither count role mapped).
    """
    axis = _production_axis(ctx)
    if axis is None:
        return None
    starts, produced = axis
    if not events:
        return float(produced.sum())
    return float(produced[starts >= events[-1].end].sum())


def learn_service_interval(gaps) -> ServiceInterval | None:
    """Median + IQR of bottles-between-services, or None with no observed gap.

    ADR-0009's thin-data floor is >= 2 service events = >= 1 gap. A single gap
    learns the rhythm but not its spread: q1 == median == q3 and ``n == 1``
    says so (no invented spread). Inclusive quartiles, ``statistics`` stdlib
    only — the same estimator ``reliability.mtbf_band`` uses.
    """
    vals = sorted(float(g) for g in gaps)
    if not vals:
        return None
    median = statistics.median(vals)
    if len(vals) == 1:
        return ServiceInterval(median=median, q1=median, q3=median, n=1)
    q1, _m, q3 = statistics.quantiles(vals, n=4, method="inclusive")
    return ServiceInterval(median=median, q1=q1, q3=q3, n=len(vals))


# --- the due window --------------------------------------------------------------


@dataclass(frozen=True)
class DueWindow:
    """When the next service falls due: a window, never a date (ADR-0009).

    The learned interval counted down by the service counter: the edges are the
    remaining bottles until the early (q1) and late (q3) rhythm points, plus
    the same edges as calendar dates at the line's current production pace.
    ``date_*`` are None when the pace is zero (a stopped line accrues no
    bottles — a bottle->date conversion would invent one). Both edges sit at
    the last observed day when the counter has already passed the interval
    (due now). ``adjusted_earlier`` / ``reasons`` record the condition
    adjustment (ADR-0009: earlier only, reason always stated).
    """

    remaining_early: float
    remaining_late: float
    date_early: date | None
    date_late: date | None
    adjusted_earlier: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)


def condition_signals(perf_slope: float | None, fault_rate_ratio: float | None) -> tuple[str, ...]:
    """The fired condition signals, as human reasons (ADR-0009 decision 4).

    Two signals, both deliberately material so ordinary jitter never fires:
    a sustained Performance downtrend (OLS slope below ``_PERF_SLOPE_FLOOR``)
    and a fault-rate surge (recent faults-per-bottle >= ``_FAULT_RATE_SURGE``
    x the earlier baseline). None-valued signals can't fire (no series, no
    verdict — never a guess).
    """
    reasons: list[str] = []
    if perf_slope is not None and perf_slope < _PERF_SLOPE_FLOOR:
        reasons.append("Performance is trending down")
    if fault_rate_ratio is not None and fault_rate_ratio >= _FAULT_RATE_SURGE:
        reasons.append("Fault rate is rising")
    return tuple(reasons)


def due_window(
    counter: float,
    interval: ServiceInterval,
    last_day: date,
    daily_rate: float,
    signals: tuple[str, ...],
) -> DueWindow:
    """Count the service counter down against the learned interval -> a window.

    The edges are the learned rhythm's q1/q3 less the bottles already on the
    counter, floored at zero (past the interval = due now, never a negative
    countdown). Each fired condition signal pulls BOTH edges earlier by half
    the IQR — earlier only (ADR-0009), data-derived (the line's own rhythm
    spread, not an invented fudge), reasons carried through. Dates are the
    bottle edges at ``daily_rate`` (the trailing pace), or None when the rate
    is zero. With a single observed gap (q1 == q3) the pull is zero — there is
    no spread to move within, so the signal can't fabricate one.
    """
    pull = len(signals) * (interval.q3 - interval.q1) / 2.0
    early = max(0.0, interval.q1 - counter - pull)
    late = max(0.0, interval.q3 - counter - pull)

    def _to_date(bottles: float) -> date | None:
        if daily_rate <= 0:
            return None
        return last_day + timedelta(days=math.ceil(bottles / daily_rate))

    return DueWindow(
        remaining_early=early,
        remaining_late=late,
        date_early=_to_date(early),
        date_late=_to_date(late),
        adjusted_earlier=bool(signals) and pull > 0,
        reasons=tuple(signals),
    )


# --- the report + the thin context wrapper ---------------------------------------


@dataclass(frozen=True)
class MaintenanceReport:
    """The maintenance act's numbers: counter always, window when learned.

    ``bottles_since_service`` is the service counter (ADR-0009: always renders,
    pure arithmetic). ``interval`` / ``due`` are None below the thin-data floor
    (>= 2 service events) — nothing is invented. ``repair_threshold_s`` is the
    learned routine/repair fence (None with < 4 Faults). ``notes`` carries the
    honest caveats (no service events in the data, thin history, unknown
    spread) for the UI to render verbatim.
    """

    bottles_since_service: float
    last_service_end: pd.Timestamp | None
    n_service_events: int
    repair_threshold_s: float | None
    interval: ServiceInterval | None
    due: DueWindow | None
    notes: tuple[str, ...] = field(default_factory=tuple)


def _daily_produced(ctx: ValidationContext) -> pd.Series | None:
    """Daily produced bottles (good + reject) indexed by calendar day, or None."""
    axis = _production_axis(ctx)
    if axis is None:
        return None
    starts, produced = axis
    day = starts.dt.floor("D")
    daily = produced.groupby(day).sum()
    return daily[daily.index.notna()].sort_index()


def _current_daily_rate(daily: pd.Series) -> float:
    """The line's current pace: median daily production over the trailing
    ``_RATE_WINDOW_DAYS`` days (all days when fewer). 0.0 when no production —
    the due window then keeps its bottle edges and declines the dates."""
    if daily.empty:
        return 0.0
    return float(daily.tail(_RATE_WINDOW_DAYS).median())


def _fault_rate_ratio(ctx: ValidationContext, daily: pd.Series) -> float | None:
    """Recent vs earlier faults-per-bottle: the fault-rate condition signal.

    Recent = the trailing ``_FAULT_RATE_RECENT_DAYS``; earlier = everything
    before. A ratio >= ``_FAULT_RATE_SURGE`` fires the signal (computed in
    ``condition_signals``). None when either window has no production or the
    earlier baseline has no faults — a surge from a zero baseline is count
    noise, not a trend (conservative: the signal may stay quiet, never cries
    wolf).
    """
    cause_src = ctx.mapping.source_for(CanonicalRole.STOP_CAUSE)
    start_src = ctx.mapping.source_for(CanonicalRole.TIMESTAMP_START)
    if cause_src is None or start_src is None or daily.empty:
        return None
    starts = pd.to_datetime(ctx.data[start_src], errors="coerce")
    cause = ctx.data[cause_src].astype("string").str.strip().str.lower()
    cutoff = daily.index[-1] - pd.Timedelta(days=_FAULT_RATE_RECENT_DAYS - 1)
    is_fault = (cause == _FAULT).astype(float)
    recent = starts >= cutoff
    f_recent, f_earlier = float(is_fault[recent].sum()), float(is_fault[~recent].sum())
    p_recent = float(daily[daily.index >= cutoff].sum())
    p_earlier = float(daily[daily.index < cutoff].sum())
    if p_recent <= 0 or p_earlier <= 0 or f_earlier <= 0:
        return None
    return (f_recent / p_recent) / (f_earlier / p_earlier)


def _performance_slope(ctx: ValidationContext) -> float | None:
    """OLS slope of the dated daily Performance series (ratio/day), or None.

    Reuses ``oee.performance_by_day`` — the same identity the Now KPI and the
    Act-4 degradation chart use, so the condition signal can never disagree
    with either. Plain least squares over day ordinals (the same estimator
    ``forecast`` / ``forecast_ml`` diagnostics use); None without a series or
    with < 2 dated points.
    """
    from .oee import performance_by_day  # local: keeps module import light

    frame = performance_by_day(ctx)
    if frame is None or len(frame) < 2:
        return None
    x = pd.Series([d.toordinal() for d in frame["date"]], dtype=float)
    y = frame["performance"].astype(float)
    var = float(((x - x.mean()) ** 2).sum())
    if var == 0:
        return None
    return float(((x - x.mean()) * (y - y.mean())).sum() / var)


def maintenance_from_context(ctx: ValidationContext) -> MaintenanceReport | None:
    """The maintenance report from a loaded, coerced ValidationContext.

    Composes the pure pieces: learn the repair fence from the Fault durations,
    select the service events, read the service counter, learn the interval,
    rate the trailing production, fire the condition signals, and count the
    window down. Returns None only when the bottle axis itself is undefined
    (no start timestamp, or neither count role mapped) — the counter is the
    floor of the whole act, and without bottles there is no odometer at all.
    """
    axis = _production_axis(ctx)
    if axis is None:
        return None

    # The repair fence is learned from ALL Fault durations, routine included —
    # the fence's job is to find where the tail starts.
    cause_src = ctx.mapping.source_for(CanonicalRole.STOP_CAUSE)
    threshold = None
    if cause_src is not None and cause_src in ctx.data.columns:
        cause = ctx.data[cause_src].astype("string").str.strip().str.lower()
        durations, _ds = _durations_axis(ctx)
        if durations is not None:
            threshold = repair_threshold(durations[cause == _FAULT])

    events = service_events(ctx, threshold)
    counter = service_counter(ctx, events)
    gaps = bottles_between(ctx, events)
    interval = learn_service_interval(gaps)

    daily = _daily_produced(ctx)
    due = None
    if interval is not None and daily is not None and not daily.empty:
        signals = condition_signals(
            _performance_slope(ctx), _fault_rate_ratio(ctx, daily))
        due = due_window(
            counter, interval, daily.index[-1].date(),
            _current_daily_rate(daily), signals)

    notes: list[str] = []
    if not events:
        notes.append(
            "No Maintenance stop or repair-length Fault in this data — the "
            "counter covers the whole file; the last service predates it.")
    elif interval is None:
        notes.append(
            "Only one service event in this data — not enough service history "
            "to learn a service rhythm (need ≥ 2). The counter still reads.")
    elif interval.n == 1:
        notes.append(
            "The service rhythm is learned from a single observed interval — "
            "its spread is unknown, so the window is only as wide as the data.")

    return MaintenanceReport(
        bottles_since_service=counter,
        last_service_end=events[-1].end if events else None,
        n_service_events=len(events),
        repair_threshold_s=threshold,
        interval=interval,
        due=due,
        notes=tuple(notes),
    )


def _durations_axis(ctx: ValidationContext):
    """(per-row durations in seconds, source) via summaries' shared helper, or
    (None, None) — the repair fence needs durations even when the app never
    computes OEE. Same extraction ``oee`` / ``whatif`` reuse."""
    from .summaries import _event_durations  # local: avoids an import cycle

    return _event_durations(ctx)
