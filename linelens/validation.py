"""Validation engine: rule registry, runner, and the rule set."""
from __future__ import annotations

import statistics
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import pandas as pd

from .models import (
    CanonicalRole,
    ColumnMapping,
    CounterColumn,
    CounterKind,
    DatasetProfile,
    Finding,
    Severity,
)
from .schema import ColumnCoercion, coerce
from .counters import (
    REAL_PRECISION_WALL,
    RESET_CAUSE_ANOMALOUS,
    classify_counter,
    detect_resets,
)


@dataclass(frozen=True)
class ValidationContext:
    """Everything a validation rule needs to inspect."""

    mapping: ColumnMapping
    raw: pd.DataFrame  # original, untouched
    data: pd.DataFrame  # coerced (timestamps parsed, numerics coerced)
    profile: DatasetProfile
    coercion: tuple[ColumnCoercion, ...]
    counters: tuple[CounterColumn, ...] = ()  # classified pointed-at counters (M4)


Rule = Callable[[ValidationContext], Iterable[Finding]]

_REGISTRY: list[Rule] = []


def rule(func: Rule) -> Rule:
    """Register a validation rule. The function returns an iterable of Findings."""
    _REGISTRY.append(func)
    return func


def registered_rules() -> tuple[Rule, ...]:
    return tuple(_REGISTRY)


def run_validation(ctx: ValidationContext) -> list[Finding]:
    """Run every registered rule; return a deterministically sorted list."""
    findings: list[Finding] = []
    for func in _REGISTRY:
        findings.extend(func(ctx))
    findings.sort(key=_sort_key)
    return findings


def _sort_key(finding: Finding) -> tuple[str, float]:
    # Stable order: rule_id, then first affected source row (row-less findings last).
    first_row = finding.affected_rows[0] if finding.affected_rows else float("inf")
    return (finding.rule_id, first_row)


def make_context(
    raw: pd.DataFrame, profile: DatasetProfile, mapping: ColumnMapping
) -> ValidationContext:
    """Build a ValidationContext by coercing the mapped columns.

    Pointed-at counters (mapping.counters) are classified once here so the M4
    rules share one inference result per column. Classification reads the raw
    column and the mapped start timestamps (if any) for gap-aware reset cause.
    """
    data, coercion = coerce(mapping, raw)
    timestamps = raw[mapping.roles[CanonicalRole.TIMESTAMP_START]] \
        if CanonicalRole.TIMESTAMP_START in mapping.roles else None
    classified = []
    for name in mapping.counters:
        if name not in raw.columns:
            continue
        kind, confidence, evidence = classify_counter(raw[name], timestamps)
        classified.append(
            CounterColumn(name, kind, confidence, evidence)
        )
    return ValidationContext(
        mapping=mapping,
        raw=raw,
        data=data,
        profile=profile,
        coercion=coercion,
        counters=tuple(classified),
    )


def _row_numbers(mask: pd.Series) -> tuple[int, ...]:
    """1-based source row numbers for True positions (header is row 1)."""
    return tuple(i + 2 for i, keep in enumerate(mask) if keep)


@rule
def coercion_failures(ctx: ValidationContext) -> Iterable[Finding]:
    """Report values that could not be coerced to their target type (INFO)."""
    for column in ctx.coercion:
        if not column.failed_rows:
            continue
        yield Finding(
            rule_id="COERCION_FAILURE",
            severity=Severity.INFO,
            title=f"Unparseable {column.target} values in {column.source!r}",
            description=(
                f"{len(column.failed_rows)} value(s) mapped to role "
                f"{column.role.value} could not be coerced to {column.target}."
            ),
            evidence={
                "source": column.source,
                "target": column.target,
                "count": len(column.failed_rows),
            },
            affected_rows=column.failed_rows,
        )


# --- timestamp rules (M3/T3.2) -------------------------------------------

GAP_FACTOR = 10.0  # a gap > 10x the median inter-record interval counts as "large"


def _column(ctx: ValidationContext, role: CanonicalRole) -> pd.Series | None:
    """Return the coerced series for a role, or None if it isn't mapped."""
    source = ctx.mapping.source_for(role)
    if not source or source not in ctx.data.columns:
        return None
    return ctx.data[source]


@rule
def missing_timestamp(ctx: ValidationContext) -> Iterable[Finding]:
    source = ctx.mapping.source_for(CanonicalRole.TIMESTAMP_START)
    if not source or source not in ctx.raw.columns:
        return
    rows = _row_numbers(ctx.raw[source].isna())
    if rows:
        yield Finding(
            rule_id="MISSING_TIMESTAMP",
            severity=Severity.WARNING,
            title="Missing start timestamp",
            description=f"{len(rows)} record(s) have no {source!r} value.",
            evidence={"column": source, "count": len(rows)},
            affected_rows=rows,
        )


@rule
def timestamp_end_before_start(ctx: ValidationContext) -> Iterable[Finding]:
    start = _column(ctx, CanonicalRole.TIMESTAMP_START)
    end = _column(ctx, CanonicalRole.TIMESTAMP_END)
    if start is None or end is None:
        return
    rows = _row_numbers(start.notna() & end.notna() & (end < start))
    if rows:
        yield Finding(
            rule_id="TIMESTAMP_END_BEFORE_START",
            severity=Severity.ERROR,
            title="End timestamp precedes start timestamp",
            description=f"{len(rows)} record(s) have an end earlier than their start.",
            evidence={"count": len(rows)},
            affected_rows=rows,
        )


@rule
def timestamps_not_sorted(ctx: ValidationContext) -> Iterable[Finding]:
    # ponytail: checks file order for a single machine; per-machine ordering is a
    # multi-machine concern, deferred.
    col = _column(ctx, CanonicalRole.TIMESTAMP_START)
    if col is None:
        return
    rows = _row_numbers(col.notna() & (col < col.shift(1)))
    if rows:
        yield Finding(
            rule_id="TIMESTAMPS_NOT_SORTED",
            severity=Severity.WARNING,
            title="Start timestamps are not in ascending order",
            description=f"{len(rows)} record(s) precede an earlier timestamp.",
            evidence={"count": len(rows)},
            affected_rows=rows,
        )


@rule
def duplicate_timestamps(ctx: ValidationContext) -> Iterable[Finding]:
    col = _column(ctx, CanonicalRole.TIMESTAMP_START)
    if col is None:
        return
    rows = _row_numbers(col.notna() & col.duplicated(keep=False))
    if rows:
        yield Finding(
            rule_id="DUPLICATE_TIMESTAMPS",
            severity=Severity.WARNING,
            title="Duplicate start timestamps",
            description=(
                f"{len(rows)} record(s) share a start timestamp with another record."
            ),
            evidence={"count": len(rows)},
            affected_rows=rows,
        )


@rule
def duplicate_events(ctx: ValidationContext) -> Iterable[Finding]:
    if ctx.raw.empty:
        return
    rows = _row_numbers(ctx.raw.duplicated(keep=False))
    if rows:
        yield Finding(
            rule_id="DUPLICATE_EVENTS",
            severity=Severity.WARNING,
            title="Fully duplicated records",
            description=(
                f"{len(rows)} record(s) are exact duplicates of another record."
            ),
            evidence={"count": len(rows)},
            affected_rows=rows,
        )


@rule
def overlapping_events(ctx: ValidationContext) -> Iterable[Finding]:
    start = _column(ctx, CanonicalRole.TIMESTAMP_START)
    end = _column(ctx, CanonicalRole.TIMESTAMP_END)
    if start is None or end is None:
        return
    pairs = [
        (start.iloc[i], end.iloc[i], i)
        for i in range(len(start))
        if pd.notna(start.iloc[i]) and pd.notna(end.iloc[i])
    ]
    if len(pairs) < 2:
        return
    pairs.sort(key=lambda item: item[0])
    flagged: set[int] = set()
    running_max_end = pairs[0][1]
    for _start, _end, i in pairs[1:]:
        if _start < running_max_end:  # touching intervals (==) are allowed
            flagged.add(i)
        if _end > running_max_end:
            running_max_end = _end
    rows = tuple(i + 2 for i in sorted(flagged))
    if rows:
        yield Finding(
            rule_id="OVERLAPPING_EVENTS",
            severity=Severity.WARNING,
            title="Overlapping events",
            description=f"{len(rows)} record(s) overlap a preceding event.",
            evidence={"count": len(rows)},
            affected_rows=rows,
        )


@rule
def large_time_gap(ctx: ValidationContext) -> Iterable[Finding]:
    col = _column(ctx, CanonicalRole.TIMESTAMP_START)
    if col is None:
        return
    present = [(col.iloc[i], i) for i in range(len(col)) if pd.notna(col.iloc[i])]
    if len(present) < 3:
        return
    present.sort(key=lambda item: item[0])
    diffs = [
        (present[k][0] - present[k - 1][0]).total_seconds()
        for k in range(1, len(present))
    ]
    positive = [d for d in diffs if d > 0]
    if not positive:
        return
    median = statistics.median(positive)
    threshold = median * GAP_FACTOR
    flagged = {
        present[k][1] for k, diff in enumerate(diffs, start=1) if diff > threshold
    }
    rows = tuple(i + 2 for i in sorted(flagged))
    if rows:
        yield Finding(
            rule_id="LARGE_TIME_GAP",
            severity=Severity.INFO,
            title="Unexpectedly large gap between records",
            description=(
                f"{len(rows)} record(s) follow a gap > {threshold:.0f}s "
                f"({GAP_FACTOR}x the median interval of {median:.0f}s)."
            ),
            evidence={
                "count": len(rows),
                "median_interval_seconds": median,
                "threshold_seconds": threshold,
            },
            affected_rows=rows,
        )


# --- duration rules (M3/T3.3) --------------------------------------------

DURATION_TOLERANCE_SECONDS = 1.0
SECONDS_PER_DAY = 86_400


@rule
def missing_duration(ctx: ValidationContext) -> Iterable[Finding]:
    source = ctx.mapping.source_for(CanonicalRole.DURATION)
    if not source or source not in ctx.raw.columns:
        return
    rows = _row_numbers(ctx.raw[source].isna())
    if rows:
        yield Finding(
            rule_id="MISSING_DURATION",
            severity=Severity.WARNING,
            title="Missing duration",
            description=f"{len(rows)} record(s) have no duration value.",
            evidence={"column": source, "count": len(rows)},
            affected_rows=rows,
        )


@rule
def negative_duration(ctx: ValidationContext) -> Iterable[Finding]:
    col = _column(ctx, CanonicalRole.DURATION)
    if col is None:
        return
    rows = _row_numbers(col.notna() & (col < 0))
    if rows:
        yield Finding(
            rule_id="NEGATIVE_DURATION",
            severity=Severity.ERROR,
            title="Negative duration",
            description=f"{len(rows)} record(s) have a duration below zero.",
            evidence={"count": len(rows)},
            affected_rows=rows,
        )


@rule
def duration_inconsistent(ctx: ValidationContext) -> Iterable[Finding]:
    dur = _column(ctx, CanonicalRole.DURATION)
    start = _column(ctx, CanonicalRole.TIMESTAMP_START)
    end = _column(ctx, CanonicalRole.TIMESTAMP_END)
    if dur is None or start is None or end is None:
        return
    computed = (end - start).dt.total_seconds()
    mask = dur.notna() & start.notna() & end.notna() & (
        (dur - computed).abs() > DURATION_TOLERANCE_SECONDS
    )
    rows = _row_numbers(mask)
    if rows:
        yield Finding(
            rule_id="DURATION_INCONSISTENT",
            severity=Severity.WARNING,
            title="Duration disagrees with start/end timestamps",
            description=(
                f"{len(rows)} record(s) have a duration differing from "
                f"(end - start) by more than {DURATION_TOLERANCE_SECONDS}s."
            ),
            evidence={
                "tolerance_seconds": DURATION_TOLERANCE_SECONDS,
                "count": len(rows),
            },
            affected_rows=rows,
        )


@rule
def total_duration_exceeds_span(ctx: ValidationContext) -> Iterable[Finding]:
    dur = _column(ctx, CanonicalRole.DURATION)
    start = _column(ctx, CanonicalRole.TIMESTAMP_START)
    if dur is None or start is None:
        return
    total = dur.sum(skipna=True)
    if pd.isna(total) or len(start.dropna()) < 2:
        return
    end = _column(ctx, CanonicalRole.TIMESTAMP_END)
    span_source = end if end is not None else start
    span = (span_source.max() - start.min()).total_seconds()
    if span <= 0:
        return
    if total > span + DURATION_TOLERANCE_SECONDS:
        yield Finding(
            rule_id="TOTAL_DURATION_EXCEEDS_SPAN",
            severity=Severity.WARNING,
            title="Total duration exceeds the time span",
            description=(
                f"Sum of durations ({total:.0f}s) exceeds the covered span "
                f"({span:.0f}s) -- impossible without overlap or double counting."
            ),
            observed_value=float(total),
            maximum_possible_value=float(span),
            evidence={"total_seconds": float(total), "span_seconds": float(span)},
            affected_rows=(),
        )


@rule
def daily_duration_exceeds_86400(ctx: ValidationContext) -> Iterable[Finding]:
    dur = _column(ctx, CanonicalRole.DURATION)
    start = _column(ctx, CanonicalRole.TIMESTAMP_START)
    if dur is None or start is None:
        return
    frame = pd.DataFrame({"start": start, "dur": dur}).dropna(subset=["start"])
    if frame.empty:
        return
    frame["day"] = frame["start"].dt.floor("D")
    for day, group in frame.groupby("day", sort=True):
        total = group["dur"].sum(skipna=True)
        if pd.isna(total) or total <= SECONDS_PER_DAY + DURATION_TOLERANCE_SECONDS:
            continue
        rows = tuple(int(i) + 2 for i in group.index.tolist())
        yield Finding(
            rule_id="DAILY_DURATION_EXCEEDS_86400",
            severity=Severity.ERROR,
            title="Daily duration exceeds 86,400 seconds",
            description=(
                f"Sum of durations on {day.date()} is {total:.0f}s, more than "
                f"the {SECONDS_PER_DAY}s in a day."
            ),
            period_start=day.to_pydatetime(),
            period_end=(day + pd.Timedelta(days=1)).to_pydatetime(),
            observed_value=float(total),
            maximum_possible_value=float(SECONDS_PER_DAY),
            evidence={"day": day.date().isoformat(), "total_seconds": float(total)},
            affected_rows=rows,
        )


# --- state rules (M3/T3.4) -----------------------------------------------

# ponytail: a conservative default state taxonomy. Real machines use different
# vocabularies, so UNKNOWN_STATE is a tunable heuristic (WARNING), not truth.
KNOWN_STATES = frozenset(
    {
        "running",
        "idle",
        "stopped",
        "alarmed",
        "down",
        "setup",
        "blocked",
        "paused",
        "waiting",
        "off",
    }
)


@rule
def missing_state(ctx: ValidationContext) -> Iterable[Finding]:
    source = ctx.mapping.source_for(CanonicalRole.STATE)
    if not source or source not in ctx.raw.columns:
        return
    rows = _row_numbers(ctx.raw[source].isna())
    if rows:
        yield Finding(
            rule_id="MISSING_STATE",
            severity=Severity.WARNING,
            title="Missing machine state",
            description=f"{len(rows)} record(s) have no state value.",
            evidence={"column": source, "count": len(rows)},
            affected_rows=rows,
        )


@rule
def unknown_state(ctx: ValidationContext) -> Iterable[Finding]:
    source = ctx.mapping.source_for(CanonicalRole.STATE)
    if not source or source not in ctx.data.columns:
        return
    col = ctx.data[source]
    mask = col.notna() & ~col.str.lower().isin(KNOWN_STATES)
    rows = _row_numbers(mask)
    if rows:
        yield Finding(
            rule_id="UNKNOWN_STATE",
            severity=Severity.WARNING,
            title="Unknown machine state",
            description=(
                f"{len(rows)} record(s) use a state not in the known set "
                f"(tunable): {sorted(KNOWN_STATES)}."
            ),
            evidence={"known_states": sorted(KNOWN_STATES), "count": len(rows)},
            affected_rows=rows,
        )


@rule
def stop_cause_while_running(ctx: ValidationContext) -> Iterable[Finding]:
    state = ctx.mapping.source_for(CanonicalRole.STATE)
    cause = ctx.mapping.source_for(CanonicalRole.STOP_CAUSE)
    if (
        not state
        or state not in ctx.raw.columns
        or not cause
        or cause not in ctx.raw.columns
    ):
        return
    state_col = ctx.raw[state]
    cause_col = ctx.raw[cause]
    mask = state_col.notna() & (state_col.str.lower() == "running") & cause_col.notna()
    rows = _row_numbers(mask)
    if rows:
        yield Finding(
            rule_id="STOP_CAUSE_WHILE_RUNNING",
            severity=Severity.WARNING,
            title="Stop cause present while Running",
            description=(
                f"{len(rows)} Running record(s) carry a stop cause, which is unexpected."
            ),
            evidence={"count": len(rows)},
            affected_rows=rows,
        )


@rule
def stop_cause_missing_while_stopped(ctx: ValidationContext) -> Iterable[Finding]:
    state = ctx.mapping.source_for(CanonicalRole.STATE)
    cause = ctx.mapping.source_for(CanonicalRole.STOP_CAUSE)
    if (
        not state
        or state not in ctx.raw.columns
        or not cause
        or cause not in ctx.raw.columns
    ):
        return
    state_col = ctx.raw[state]
    cause_col = ctx.raw[cause]
    mask = state_col.notna() & (state_col.str.lower() == "stopped") & cause_col.isna()
    rows = _row_numbers(mask)
    if rows:
        yield Finding(
            rule_id="STOP_CAUSE_MISSING_WHILE_STOPPED",
            severity=Severity.WARNING,
            title="Stop cause missing while Stopped",
            description=f"{len(rows)} Stopped record(s) have no stop cause.",
            evidence={"count": len(rows)},
            affected_rows=rows,
        )


# --- counter rules (M4b) --------------------------------------------------
# Counters are arbitrary numeric columns the user points at (mapping.counters),
# classified once in make_context. The headline "aggregation problem" finding
# (a cumulative column summed by a dashboard) is M5 and consumes correct_total.

# ponytail: a single CV threshold separates "smooth enough to be interpolated"
# from "noisy enough to be a real sensor". Tune if real historians mis-fire.
SMOOTH_CV_MAX = 0.2


@rule
def counter_kind_unknown(ctx: ValidationContext) -> Iterable[Finding]:
    """A pointed-at counter could not be classified -> ask the user to set its kind."""
    for cc in ctx.counters:
        if cc.kind is not CounterKind.UNKNOWN:
            continue
        reason = cc.evidence.get("reason", "not_cumulative")
        yield Finding(
            rule_id="COUNTER_KIND_UNKNOWN",
            severity=Severity.INFO,
            title=f"Counter type unclear for {cc.source_name!r}",
            description=(
                f"Could not classify {cc.source_name!r} as cumulative, incremental, "
                f"or instantaneous from its shape ({reason}). Set its kind manually so "
                f"period totals are computed by the right method."
            ),
            evidence={
                "column": cc.source_name,
                "reason": reason,
                "sample_count": cc.evidence.get("sample_count"),
            },
            affected_rows=(),
            signal=cc.source_name,
            confidence=cc.confidence,
            suggested_action="Set the counter kind (cumulative / incremental / instantaneous).",
        )


@rule
def probable_counter_reset(ctx: ValidationContext) -> Iterable[Finding]:
    """Endorsed resets in a cumulative counter, with cause + reset rows."""
    timestamps = _column(ctx, CanonicalRole.TIMESTAMP_START)
    for cc in ctx.counters:
        if cc.kind is not CounterKind.CUMULATIVE:
            continue
        resets = detect_resets(ctx.raw[cc.source_name], timestamps)
        if not resets:
            continue
        causes = sorted({cause for _row, _mag, cause in resets})
        anomalous = RESET_CAUSE_ANOMALOUS in causes
        rows = tuple(row for row, _mag, _cause in resets)
        drop_summary = [
            {"row": row, "drop": mag, "cause": cause}
            for row, mag, cause in resets
        ]
        yield Finding(
            rule_id="PROBABLE_COUNTER_RESET",
            severity=Severity.WARNING if anomalous else Severity.INFO,
            title=f"{len(resets)} reset(s) detected in counter {cc.source_name!r}",
            description=(
                f"{len(resets)} endorsed reset(s) in cumulative counter "
                f"{cc.source_name!r}. Cause(s): {', '.join(causes)}. "
                f"Affected rows are the post-drop readings."
            ),
            evidence={
                "column": cc.source_name,
                "reset_count": len(resets),
                "causes": causes,
                "resets": drop_summary,
            },
            affected_rows=rows,
            signal=cc.source_name,
            suspected_cause=causes[0] if len(causes) == 1 else None,
            confidence=cc.confidence,
        )


@rule
def possible_interpolated_export(ctx: ValidationContext) -> Iterable[Finding]:
    """Smooth cumulative call with no stair-step export and no reset -> may be interpolated.

    Historian interpolation fabricates *smooth* ramps; a noisy monotonic series is
    a real sensor read, so it is excluded by the smoothness (diff CV) gate. The
    finding is INFO -- "may be" -- never a hard claim.
    """
    for cc in ctx.counters:
        if cc.kind is not CounterKind.CUMULATIVE:
            continue
        ev = cc.evidence
        if ev.get("stair_step_export") or not ev.get("no_reset_observed"):
            continue
        if ev.get("diff_cv", 1.0) > SMOOTH_CV_MAX:  # noisy -> real sensor, not interpolation
            continue
        yield Finding(
            rule_id="POSSIBLE_INTERPOLATED_EXPORT",
            severity=Severity.INFO,
            title=f"Counter {cc.source_name!r} may be an interpolated export",
            description=(
                f"No repeated-value (stair-step) samples, no reset, and a smooth ramp "
                f"in {cc.source_name!r}; values may have been fabricated by historian "
                f"interpolation. Classification confidence is downgraded accordingly."
            ),
            evidence={
                "column": cc.source_name,
                "stair_step_export": False,
                "no_reset_observed": True,
                "diff_cv": ev.get("diff_cv"),
            },
            affected_rows=(),
            signal=cc.source_name,
            confidence=cc.confidence,
        )


@rule
def possible_real_precision_loss(ctx: ValidationContext) -> Iterable[Finding]:
    """A counter's max value passes the single-precision (2**24) wall."""
    for cc in ctx.counters:
        max_value = cc.evidence.get("max_value")
        if not cc.evidence.get("possible_precision_loss") or max_value is None:
            continue
        yield Finding(
            rule_id="POSSIBLE_REAL_PRECISION_LOSS",
            severity=Severity.INFO,
            title=f"Counter {cc.source_name!r} may exceed 32-bit float precision",
            description=(
                f"Max value {max_value:.3g} is past the ~{REAL_PRECISION_WALL:g} "
                f"(2**24) single-precision wall; small increments may be lost and the "
                f"corrected total is a lower bound."
            ),
            evidence={"column": cc.source_name, "max_value": max_value},
            affected_rows=(),
            signal=cc.source_name,
            observed_value=float(max_value),
        )
