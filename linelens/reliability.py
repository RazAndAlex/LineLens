"""Reliability from stop events (M8, Act 4): MTBF from the Fault inter-arrivals.

The reliability half of ADR-0007's "next-fault" question. The CSV carries no
labeled failures and no degradation sensor, so RUL / breakage ML is explicitly
out of scope (ADR-0007 non-goals) — **MTBF from the Fault stop events is the
honest ceiling.** This module turns the dated Fault events into inter-arrival
intervals and a banded MTBF, the input the Act-4 tile renders as a *range*,
never a precise "next fault in N days" countdown (the grilling rejected that:
fault inter-arrival CV ≈ 0.9 on the 6-month CSV, so a single number would be a
confident lie).

Two entry points, both pure over a ``ValidationContext`` (pandas-only — no ``ui``
extra), mirroring ``oee_from_context`` / ``whatif_from_context``:

* ``fault_intervals(ctx)`` — the seconds between consecutive Fault stop-cause
  events, ordered by start time. The testable seam.
* ``mtbf_band(intervals)`` — ``(median, q1, q3)`` via the ``statistics`` stdlib
  (IQR = a deliberately wide, honest band). The MTBF tile's numbers.

"Fault" is one of the seven stop-cause families locked in ``CONTEXT.md``; it is
matched case-insensitively on the mapped ``stop_cause`` column.
"""
from __future__ import annotations

import statistics

import pandas as pd

from .models import CanonicalRole
from .validation import ValidationContext

# The stop-cause family a "failure" maps to (CONTEXT.md: Fault). Matched on the
# coerced stop_cause column, case-insensitively. ponytail: hardcoded to the one
# canonical failure family; accept a cause list if a line tracks >1 fault type.
_FAULT = "fault"

# Below this many inter-arrival intervals the IQR is not meaningful — the tile
# declines with an honest "too few Fault events" caption instead of a band
# built on a handful of points.
_MIN_INTERVALS_FOR_BAND = 4


def fault_intervals(ctx: ValidationContext) -> tuple[float, ...]:
    """Inter-arrival seconds between consecutive Fault stop events (start-ordered).

    A Fault is a row whose mapped ``stop_cause`` is ``Fault``. The intervals are
    ``start[i+1] − start[i]`` over the Fault starts in ascending order — the
    time-between-failures series MTBF summarizes. Returns ``()`` when fewer than
    two Fault events exist (no interval), or no ``stop_cause`` / start timestamp
    is mapped. Pure over ``ctx.data``.

    The start timestamp is the inter-arrival basis (not duration): MTBF is "time
    between failure onsets", and a Fault's own duration is its repair time, not
    the gap to the next failure.
    """
    cause_src = ctx.mapping.source_for(CanonicalRole.STOP_CAUSE)
    start_src = ctx.mapping.source_for(CanonicalRole.TIMESTAMP_START)
    if cause_src is None or start_src is None:
        return ()
    if cause_src not in ctx.data.columns or start_src not in ctx.data.columns:
        return ()
    cause = ctx.data[cause_src].astype("string").str.strip().str.lower()
    starts = pd.to_datetime(ctx.data.loc[cause == _FAULT, start_src], errors="coerce")
    starts = starts.dropna().sort_values()
    if len(starts) < 2:
        return ()
    gaps = starts.diff().dropna().dt.total_seconds()
    return tuple(float(g) for g in gaps if pd.notna(g) and g > 0)


def mtbf_band(intervals) -> tuple[float, float, float] | None:
    """``(median, q1, q3)`` of fault inter-arrival intervals (seconds).

    The IQR (central 50%) is a deliberately wide, honest band: with fault
    inter-arrival CV ≈ 0.9 the spread is large, and a band — not a point — is
    the forecast (ADR-0002/0007's never-a-confident-number ethic, applied to a
    reliability quantity). ``None`` when there are fewer than
    ``_MIN_INTERVALS_FOR_BAND`` intervals (too few to summarize honestly).

    ``statistics`` stdlib only — no bootstrapping, no distributional assumptions.
    ponytail: a formal nonparametric / Kaplan-Meier CI that handles right-
    censoring (the last Fault has no observed successor) is the upgrade path if a
    maintenance program needs calibrated coverage; the IQR is the honest lazy
    default that already conveys "we don't know the next fault to the day."
    """
    vals = [float(v) for v in intervals]
    if len(vals) < _MIN_INTERVALS_FOR_BAND:
        return None
    q1, _median, q3 = statistics.quantiles(vals, n=4, method="inclusive")
    median = statistics.median(vals)
    return median, q1, q3
