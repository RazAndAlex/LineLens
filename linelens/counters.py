"""Counter engine: classify a numeric column and compute its honest period total.

See docs/m4-counter-design.md (v2) for the algorithm and the two design reviews
that shaped it. Core stance: never silently guess. A reset is the decisive
evidence that a column is a totalizer (a measurement never resets); without one,
a monotonic series is genuinely ambiguous (rising signal vs counter) and is
reported as CUMULATIVE with reduced confidence and a `no_reset_observed` flag.
"""
from __future__ import annotations

import statistics

import pandas as pd

from .models import CounterKind

# --- tunable constants ----------------------------------------------------
MIN_SAMPLES = 10
MONOTONIC_THRESHOLD = 0.95
RESET_FRACTION = 0.5  # an endorsed reset drops by more than this * running max
OUTLIER_FACTOR = 20.0  # a value off the neighbor-midpoint by > this * typical step is a spike
REAL_PRECISION_WALL = 16_700_000  # 2**24-ish: REAL float totalizers lose precision past here
NO_RESET_CONFIDENCE_FACTOR = 0.6  # no reset observed -> could be a rising measurement

# --- reset cause (M4b) ----------------------------------------------------
# Causes are stable strings on Finding.suspected_cause (an enum is YAGNI while
# only one consumer branches on them); add an enum the day a second consumer needs it.
RESET_CAUSE_POWER_COMMS = "probable_power_or_comms_reset"
RESET_CAUSE_WRAP = "counter_wrap"
RESET_CAUSE_ANOMALOUS = "anomalous_decrease"
# ponytail: SCHEDULED_RESET (midnight/shift boundary) deferred -- needs a shift
# schedule (decision log #1) and a non-arbitrary "near boundary" tolerance.
RESET_GAP_FACTOR = 10.0  # a gap > 10x the median interval implies power/comms loss
WRAP_MODULI = (2**16, 2**32)  # common integer-register widths
WRAP_TOLERANCE = 0.01  # drop within 1% of a modulus counts as a wrap
WRAP_NEAR_ZERO = 0.05  # post-wrap value below this fraction of the modulus


def classify_counter(values, timestamps=None) -> tuple[CounterKind, float, dict]:
    """Classify a numeric column. Returns (kind, confidence, evidence).

    `timestamps` is accepted for the signature the design specifies (gap-aware
    reset cause arrives in M4b); it does not affect classification yet.
    """
    series, gap_count = _clean_series(values)
    base = {
        "sample_count": len(series),
        "gap_count": gap_count,
        "max_value": max(series) if series else None,
    }
    if len(series) < MIN_SAMPLES:
        return CounterKind.UNKNOWN, 0.0, {**base, "reason": "too_few_samples"}

    ascending_evidence: dict = {}
    for sign, direction in ((1, "ascending"), (-1, "descending")):
        kind, confidence, evidence = _test_cumulative([sign * v for v in series])
        if sign == 1:
            ascending_evidence = evidence
        if kind is CounterKind.CUMULATIVE:
            return kind, confidence, {**base, **evidence, "direction": direction}
    reason = ascending_evidence.get("reason", "not_cumulative")
    return CounterKind.UNKNOWN, 0.0, {**base, **ascending_evidence, "reason": reason}


def correct_total(values, timestamps=None, kind: CounterKind | None = None):
    """Return (total, evidence) for a column, or (None, evidence) if not summable.

    For CUMULATIVE the total is `(last - first) + sum(reset drops)` after spike
    removal -- reset-robust and jitter-proof by construction. INCREMENTAL sums the
    values. INSTANTANEOUS / UNKNOWN are not summable.
    """
    series, _gap = _clean_series(values)
    if not series:
        return None, {"method": "no_data"}
    if kind is None:
        kind, _conf, _ev = classify_counter(values, timestamps)

    if kind is CounterKind.INCREMENTAL:
        return float(sum(series)), {"method": "incremental_sum"}

    if kind is not CounterKind.CUMULATIVE:
        return None, {"method": "not_summable", "kind": kind.value}

    series, outliers = _remove_value_outliers(series)
    sign = -1 if series[0] > series[-1] else 1
    view = [sign * v for v in series]  # ascending view
    _diffs, resets = _endorsed_resets(view)
    total = (view[-1] - view[0]) + sum(magnitude for _i, magnitude in resets)
    return float(total), {
        "method": "cumulative_difference",
        "reset_count": len(resets),
        "outliers_removed": outliers,
        "possible_precision_loss": bool(series and max(series) > REAL_PRECISION_WALL),
    }


def detect_resets(values, timestamps=None) -> list[tuple[int, float, str]]:
    """Locate endorsed resets and classify each cause.

    Returns [(source_row_1based, drop_magnitude, cause), ...] for the down-steps
    that persist (a comms glitch recovers immediately) and are large. A
    descending totalizer (fuel remaining) is flipped to ascending first, so its
    up-steps are the resets. Cause is a RESET_CAUSE_* string; without timestamps
    the gap-based cause is skipped. Spike removal mirrors correct_total so a lone
    bad read is never miscounted as a reset.
    """
    series, ts, positions = _clean_aligned(values, timestamps)
    if len(series) < 2:
        return []
    keep = _outlier_mask(series)
    series = [v for v, k in zip(series, keep) if k]
    ts = [t for t, k in zip(ts, keep) if k] if ts is not None else None
    positions = [p for p, k in zip(positions, keep) if k]
    if len(series) < 2:
        return []

    sign = -1 if series[0] > series[-1] else 1
    view = [sign * v for v in series]  # ascending view
    _diffs, resets = _endorsed_resets(view)
    median_dt = _median_interval(ts)
    findings: list[tuple[int, float, str]] = []
    for diff_index, magnitude in resets:
        post = view[diff_index + 1]
        prev_t = ts[diff_index] if ts else None
        post_t = ts[diff_index + 1] if ts else None
        cause = _classify_reset_cause(magnitude, post, prev_t, post_t, median_dt)
        source_row = positions[diff_index + 1] + 2  # 1-based; header is row 1
        findings.append((source_row, magnitude, cause))
    return findings


# --- internals ------------------------------------------------------------

def _clean_series(values) -> tuple[list[float], int]:
    s = pd.to_numeric(pd.Series(values), errors="coerce")
    gap_count = int(s.isna().sum())
    return [float(v) for v in s.dropna().tolist()], gap_count


def _test_cumulative(series: list[float]) -> tuple[CounterKind, float, dict]:
    """Test one direction (caller flips the sign for descending)."""
    diffs, resets = _endorsed_resets(series)
    if not any(d != 0 for d in diffs):
        return CounterKind.UNKNOWN, 0.0, {"reason": "constant"}
    reset_idx = {i for i, _ in resets}
    non_reset = [diffs[i] for i in range(len(diffs)) if i not in reset_idx]
    if not non_reset:
        return CounterKind.UNKNOWN, 0.0, {"reason": "only_resets"}
    monotonic = sum(1 for d in non_reset if d >= 0) / len(non_reset)
    total_increase = series[-1] - series[0]
    nonzero = [d for d in diffs if d != 0]
    # diff_cv: coefficient of variation of step sizes. ~0 = a counter climbing in
    # one batch size, or a perfectly smooth (interpolated) ramp; high = noisy real
    # signal. Used downstream to tell interpolation apart from a noisy sensor.
    diff_cv = statistics.pstdev(nonzero) / (statistics.mean(nonzero) or 1) if nonzero else 0.0
    evidence = {
        "monotonic_ratio_excl_resets": round(monotonic, 4),
        "reset_count": len(resets),
        "negative_diff_count": sum(1 for d in diffs if d < 0),
        "total_increase": total_increase,
        "no_reset_observed": len(resets) == 0,
        "stair_step_export": _has_stair_step(series),
        "diff_cv": round(diff_cv, 4),
    }
    if series and max(series) > REAL_PRECISION_WALL:
        evidence["possible_precision_loss"] = True

    if monotonic >= MONOTONIC_THRESHOLD and total_increase > 0:
        confidence = _wilson_lower(monotonic, len(non_reset))
        if len(resets) == 0:
            confidence *= NO_RESET_CONFIDENCE_FACTOR
        return CounterKind.CUMULATIVE, round(min(confidence, 0.95), 4), evidence
    return CounterKind.UNKNOWN, 0.0, evidence


def _endorsed_resets(series: list[float]) -> tuple[list[float], list[tuple[int, float]]]:
    """Detect endorsed resets: a down-step that persists AND is large.

    Returns (diffs, [(diff_index, drop_magnitude), ...]). Persistence: the next
    sample does not recover above the pre-drop value (a glitch recovers). Large:
    the drop exceeds RESET_FRACTION * running max (excludes rate-noise dribble).
    """
    n = len(series)
    diffs = [series[i + 1] - series[i] for i in range(n - 1)]
    running_max = series[0]
    resets: list[tuple[int, float]] = []
    for i, diff in enumerate(diffs):
        if diff < 0:
            persists = not (i + 2 < n and series[i + 2] >= series[i])
            large = abs(diff) > RESET_FRACTION * running_max
            if persists and large:
                resets.append((i, abs(diff)))
        if series[i + 1] > running_max:
            running_max = series[i + 1]
    return diffs, resets


def _has_stair_step(series: list[float]) -> bool:
    """True if any value repeats >= 3 times consecutively (counter-friendly export)."""
    run = 1
    for i in range(1, len(series)):
        if series[i] == series[i - 1]:
            run += 1
            if run >= 3:
                return True
        else:
            run = 1
    return False


def _outlier_mask(series: list[float]) -> list[bool]:
    """Boolean keep-list: False on interior spike values far from neighbor midpoint."""
    if len(series) < 3:
        return [True] * len(series)
    typical = statistics.median(abs(series[i + 1] - series[i]) for i in range(len(series) - 1))
    if typical <= 0:
        return [True] * len(series)
    keep = [True] * len(series)
    for i in range(1, len(series) - 1):
        midpoint = (series[i - 1] + series[i + 1]) / 2
        if abs(series[i] - midpoint) > OUTLIER_FACTOR * typical:
            keep[i] = False
    return keep


def _remove_value_outliers(series: list[float]) -> tuple[list[float], int]:
    """Drop interior spike values far from the midpoint of their neighbors."""
    keep = _outlier_mask(series)
    return [v for v, k in zip(series, keep) if k], int(sum(1 for k in keep if not k))


def _wilson_lower(p: float, n: int, z: float = 1.96) -> float:
    """Lower bound of the Wilson score interval -- a sample-size-aware confidence."""
    if n <= 0:
        return 0.0
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    spread = (z * ((p * (1 - p) / n) + z2 / (4 * n * n)) ** 0.5) / denom
    return max(0.0, center - spread)


def _clean_aligned(values, timestamps=None) -> tuple[list[float], list | None, list[int]]:
    """Numeric-clean a series, dropping NaN values, keeping input positions.

    Returns parallel (values, timestamps|None, positions) where positions are
    0-based indices into the input. A NaT timestamp is kept as None so a gap
    adjacent to it simply yields no gap signal.
    """
    s = pd.to_numeric(pd.Series(values), errors="coerce")
    has_ts = timestamps is not None
    ts = pd.to_datetime(pd.Series(timestamps), errors="coerce") if has_ts else None
    out_v: list[float] = []
    out_t: list = []
    out_p: list[int] = []
    for i in range(len(s)):
        if pd.isna(s.iloc[i]):
            continue
        out_v.append(float(s.iloc[i]))
        out_p.append(i)
        out_t.append(ts.iloc[i].to_pydatetime() if has_ts and pd.notna(ts.iloc[i]) else None)
    return out_v, (out_t if has_ts else None), out_p


def _median_interval(timestamps: list | None) -> float | None:
    """Median positive inter-record interval in seconds, or None if unknown."""
    if not timestamps:
        return None
    present = [t for t in timestamps if t is not None]
    if len(present) < 2:
        return None
    diffs = [
        (present[k] - present[k - 1]).total_seconds()
        for k in range(1, len(present))
    ]
    positive = [d for d in diffs if d > 0]
    return statistics.median(positive) if positive else None


def _classify_reset_cause(
    magnitude: float, post_value: float, prev_t, post_t, median_dt
) -> str:
    """Cause for an endorsed reset, from magnitude + time gap. Never guesses."""
    if median_dt and prev_t is not None and post_t is not None:
        gap = (post_t - prev_t).total_seconds()
        if gap > RESET_GAP_FACTOR * median_dt:
            return RESET_CAUSE_POWER_COMMS
    for modulus in WRAP_MODULI:
        if (
            abs(magnitude - modulus) <= WRAP_TOLERANCE * modulus
            and post_value < WRAP_NEAR_ZERO * modulus
        ):
            return RESET_CAUSE_WRAP
    return RESET_CAUSE_ANOMALOUS
