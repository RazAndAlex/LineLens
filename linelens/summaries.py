"""Summaries & aggregation diagnostics (M5).

See docs/m5-summaries-design.md (approved v1). One entry point:

    summarize(ctx: ValidationContext) -> SummaryReport

Produces trustworthy totals (time-in-state, parts, downtime) from a CSV whose
column meanings are user-mapped, plus the aggregation-problem diagnostic: for
every pointed-at cumulative counter, the contrast between a naive sum (what a
dashboard does) and the honest period increase (brief §5).

Two stances from the design, baked in:
- Totals are summed as-is; overlapping events are M3's job to flag, not M5's to
  dedup (no interval-union in v1).
- "Downtime" = records carrying a stop cause, not a hard-coded state taxonomy.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .counters import correct_total
from .models import CanonicalRole, CounterKind, Finding, Severity
from .validation import ValidationContext

_FRAME_COLUMNS: dict[str, tuple[str, ...]] = {
    "state_totals": ("scope", "scope_value", "state", "seconds"),
    "production_totals": ("scope", "scope_value", "metric", "value"),
    "downtime_by_reason": ("scope", "scope_value", "reason", "seconds"),
}

# Aggregation-problem cause (brief §5): a cumulative totalizer (odometer) that a
# dashboard sums instead of differences. Owned by summaries (aggregation
# correctness), not counters (data quality); stable string per decision log #9.
CUMULATIVE_TOTALIZER_SUMMED = "cumulative_totalizer_summed"


@dataclass(frozen=True)
class SummaryReport:
    """Tidy long-form aggregation frames plus aggregation-problem findings.

    Each frame carries the overall row(s) plus one row per day and per shift
    (when the source columns exist). `scope_value` is None for overall, a date
    for day, the shift label for shift. `duration_source` records where event
    durations came from, or None when no time-based totals could be computed.
    """

    state_totals: pd.DataFrame
    production_totals: pd.DataFrame
    downtime_by_reason: pd.DataFrame
    aggregation_findings: list[Finding] = field(default_factory=list)
    duration_source: str | None = None  # "duration_column" | "end_minus_start" | None


def summarize(ctx: ValidationContext) -> SummaryReport:
    """Aggregate the mapped event data into state / production / downtime totals."""
    data = ctx.data
    durations, duration_source = _event_durations(ctx)
    scopes = _scopes(ctx, data)

    state_totals = _empty("state_totals")
    downtime = _empty("downtime_by_reason")
    if durations is not None:
        state_src = ctx.mapping.source_for(CanonicalRole.STATE)
        reason_src = ctx.mapping.source_for(CanonicalRole.STOP_CAUSE)
        rows: list[tuple] = []
        down_rows: list[tuple] = []
        for scope, scope_value, mask in scopes:
            if state_src is not None:
                grouped = durations[mask].groupby(data.loc[mask, state_src]).sum()
                rows.extend(
                    (scope, scope_value, str(state), float(seconds))
                    for state, seconds in grouped.items()
                )
            if reason_src is not None:
                has_reason = data[reason_src].notna()
                grouped = durations[mask & has_reason].groupby(
                    data.loc[mask & has_reason, reason_src]
                ).sum()
                down_rows.extend(
                    (scope, scope_value, str(reason), float(seconds))
                    for reason, seconds in grouped.items()
                )
        state_totals = pd.DataFrame(rows, columns=_FRAME_COLUMNS["state_totals"])
        downtime = pd.DataFrame(down_rows, columns=_FRAME_COLUMNS["downtime_by_reason"])

    return SummaryReport(
        state_totals=state_totals,
        production_totals=_production(ctx, scopes),
        downtime_by_reason=downtime,
        aggregation_findings=_aggregation_findings(ctx),
        duration_source=duration_source,
    )


# --- internals ------------------------------------------------------------


def _empty(frame: str) -> pd.DataFrame:
    return pd.DataFrame(columns=list(_FRAME_COLUMNS[frame]))


def _event_durations(ctx: ValidationContext) -> tuple[pd.Series | None, str | None]:
    """Per-record durations: mapped DURATION column, else end - start, else None.

    Rows whose duration is missing/unparseable stay NaN and are excluded from
    sums (pandas skipna); M3's duration rules already name those rows.
    """
    data = ctx.data
    duration_src = ctx.mapping.source_for(CanonicalRole.DURATION)
    if duration_src is not None:
        return pd.to_numeric(data[duration_src], errors="coerce"), "duration_column"
    start_src = ctx.mapping.source_for(CanonicalRole.TIMESTAMP_START)
    end_src = ctx.mapping.source_for(CanonicalRole.TIMESTAMP_END)
    if start_src is not None and end_src is not None:
        delta = data[end_src] - data[start_src]
        return delta.dt.total_seconds(), "end_minus_start"
    return None, None


def _scopes(
    ctx: ValidationContext, data: pd.DataFrame
) -> list[tuple[str, object, pd.Series]]:
    """(scope, scope_value, row-mask) triples: overall, then per day, then per shift."""
    all_rows = pd.Series(True, index=data.index)
    scopes: list[tuple[str, object, pd.Series]] = [("overall", None, all_rows)]

    start_src = ctx.mapping.source_for(CanonicalRole.TIMESTAMP_START)
    if start_src is not None:
        days = data[start_src].dt.floor("D")
        for day, positions in days.groupby(days).groups.items():
            scopes.append(("day", day.date(), data.index.isin(positions)))

    shift_src = ctx.mapping.source_for(CanonicalRole.SHIFT)
    if shift_src is not None:
        for label, positions in data.groupby(data[shift_src]).groups.items():
            scopes.append(("shift", str(label), data.index.isin(positions)))
    return scopes


def _production(
    ctx: ValidationContext, scopes: list[tuple[str, object, pd.Series]]
) -> pd.DataFrame:
    """Good/reject/total parts and yield per scope; empty unless both are mapped.

    These roles are incremental-by-convention, so summing is correct. (A user
    pointing at a *cumulative* production counter gets the aggregation
    diagnostic instead -- _aggregation_findings.)
    """
    good_src = ctx.mapping.source_for(CanonicalRole.GOOD_COUNT)
    reject_src = ctx.mapping.source_for(CanonicalRole.REJECT_COUNT)
    if good_src is None or reject_src is None:
        return _empty("production_totals")
    good = pd.to_numeric(ctx.data[good_src], errors="coerce")
    reject = pd.to_numeric(ctx.data[reject_src], errors="coerce")

    rows: list[tuple] = []
    for scope, scope_value, mask in scopes:
        g = float(good[mask].sum())
        r = float(reject[mask].sum())
        total = g + r
        rows.append((scope, scope_value, "good", g))
        rows.append((scope, scope_value, "reject", r))
        rows.append((scope, scope_value, "total", total))
        rows.append((scope, scope_value, "yield", g / total if total else None))
    return pd.DataFrame(rows, columns=_FRAME_COLUMNS["production_totals"])


# --- aggregation diagnostics (M5b) ----------------------------------------


def _aggregation_findings(ctx: ValidationContext) -> list[Finding]:
    """One WARNING per pointed-at cumulative counter: naive sum vs honest total.

    A cumulative totalizer (odometer) summed by a dashboard double-counts every
    prior reading; its honest period increase is last - first (+ resets), from
    counters.correct_total. The contrast is the brief §5 diagnosis, and is the
    same contrast whether or not a reset occurs (summing a clean totalizer is
    still wrong). Non-cumulative counters are summed legitimately and get no
    finding. (classify_counter returns CUMULATIVE or UNKNOWN, never INCREMENTAL,
    so an incremental counter that classifies UNKNOWN is simply left alone -- no
    false alarm; INSTANTANEOUS vs INCREMENTAL stays inseparable, per M4.)
    """
    findings: list[Finding] = []
    for cc in ctx.counters:
        if cc.kind is not CounterKind.CUMULATIVE:
            continue
        values = ctx.raw[cc.source_name]
        observed = float(pd.to_numeric(values, errors="coerce").sum(min_count=1))
        calculated, calc_ev = correct_total(values, kind=CounterKind.CUMULATIVE)
        if calculated is None or pd.isna(observed):
            continue
        findings.append(
            Finding(
                rule_id="CUMULATIVE_TOTALIZER_SUMMED",
                severity=Severity.WARNING,
                title=f"Summing cumulative counter {cc.source_name!r} overstates its total",
                description=(
                    f"A dashboard that sums {cc.source_name!r} would show {observed:g}, but it "
                    f"is a cumulative totalizer whose honest period increase is {calculated:g} "
                    f"(last - first, plus resets). Summing a running total double-counts."
                ),
                evidence={
                    "column": cc.source_name,
                    "naive_sum": observed,
                    "honest_total": calculated,
                    "method": calc_ev.get("method"),
                    "reset_count": calc_ev.get("reset_count", 0),
                    "by_day": _per_day_breakdown(ctx, cc.source_name),
                },
                affected_rows=(),
                signal=cc.source_name,
                observed_value=observed,
                calculated_value=calculated,
                suspected_cause=CUMULATIVE_TOTALIZER_SUMMED,
                confidence=cc.confidence,
            )
        )
    return findings


def _per_day_breakdown(ctx: ValidationContext, source_name: str) -> list[dict]:
    """Naive sum vs honest total per day, so a single ballooned day is visible.

    Day = TIMESTAMP_START floored to the day (naive local, decision log #2).
    Empty when no start timestamp is mapped; the overall contrast in the finding
    still stands without it.
    """
    start_src = ctx.mapping.source_for(CanonicalRole.TIMESTAMP_START)
    if start_src is None or start_src not in ctx.data.columns:
        return []
    days = ctx.data[start_src].dt.floor("D").dropna()
    rows: list[dict] = []
    for day, idx in days.groupby(days).groups.items():
        day_values = ctx.raw.loc[idx, source_name]
        naive = float(pd.to_numeric(day_values, errors="coerce").sum(min_count=1))
        if pd.isna(naive):
            continue
        honest, _ev = correct_total(day_values, kind=CounterKind.CUMULATIVE)
        rows.append(
            {
                "day": day.date().isoformat(),
                "naive_sum": naive,
                "honest_total": honest if honest is not None else None,
            }
        )
    return rows
