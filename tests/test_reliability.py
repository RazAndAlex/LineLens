"""Reliability tests (M8, Act 4): Fault inter-arrival intervals + banded MTBF.

``linelens.reliability`` is the honest ceiling ADR-0007 names — MTBF from the
Fault stop events, since the CSV carries no labeled failures or degradation
sensor (RUL/breakage ML is out of scope). These are the hand-computed oracles
for the two pure helpers, plus the 6-month-CSV sanity the grilling cited
(~200 inter-arrival intervals, CV ≈ 0.9 -> a band, never a precise countdown).

The suite stays free of the ``ui`` extra: both helpers are pandas/stdlib over a
``ValidationContext``, mirroring ``oee_from_context``.
"""
from __future__ import annotations

import statistics
from pathlib import Path

import pytest

from linelens import ingestion, schema, validation
from linelens.reliability import fault_intervals, mtbf_band

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FICTIONAL_6MONTH = _REPO_ROOT / "sample_data" / "fictional_6month.csv"

_COLS = ",".join([
    "machine_id", "timestamp_start", "timestamp_end", "state", "stop_cause",
    "shift", "recipe", "speed_target", "speed_actual", "duration_seconds",
    "good_count", "reject_count", "planned",
])


def _ctx_for(csv_path: Path):
    raw, profile = ingestion.load_csv(csv_path)
    sug = schema.suggest_roles(profile.columns)
    role_to_col = {role: col for col, (role, _conf) in sug.items()}
    return validation.make_context(raw, profile, schema.build_mapping(role_to_col))


def _ctx_from_rows(tmp_path, rows):
    csv = tmp_path / "faults.csv"
    csv.write_text(_COLS + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return _ctx_for(csv)


# --- fault_intervals: inter-arrival gaps between Fault stop events ------------


# Three Faults at 06:00 / 18:00 (day 1) / 06:00 (day 2), interleaved with a
# Starvation that must be excluded. Inserted out of source order so the sort is
# exercised, not just file order.
_FAULT_ROWS = [
    "M01,2026-06-23 12:00:00,2026-06-23 12:10:00,Stopped,Starvation,A,R,2200,0,600,0,0,False",
    "M01,2026-06-24 06:00:00,2026-06-24 06:10:00,Stopped,Fault,A,R,2200,0,600,0,0,False",
    "M01,2026-06-23 06:00:00,2026-06-23 06:10:00,Stopped,Fault,A,R,2200,0,600,0,0,False",
    "M01,2026-06-23 18:00:00,2026-06-23 18:10:00,Stopped,Fault,A,R,2200,0,600,0,0,False",
]


def test_fault_intervals_are_start_ordered_inter_arrivals(tmp_path):
    intervals = fault_intervals(_ctx_from_rows(tmp_path, _FAULT_ROWS))
    # Fault starts sorted: 06:00(d1) -> 18:00(d1) -> 06:00(d2); each gap = 12h.
    assert intervals == (43200.0, 43200.0)
    # Starvation is not a Fault -> excluded (3 Faults -> 2 intervals, not 3+).


def test_fault_intervals_below_two_events_is_empty(tmp_path):
    rows = [
        "M01,2026-06-23 06:00:00,2026-06-23 06:10:00,Stopped,Fault,A,R,2200,0,600,0,0,False",
        "M01,2026-06-23 12:00:00,2026-06-23 12:10:00,Stopped,Starvation,A,R,2200,0,600,0,0,False",
    ]
    assert fault_intervals(_ctx_from_rows(tmp_path, rows)) == ()


def test_fault_intervals_none_without_cause_or_start(tmp_path):
    # No stop_cause mapped -> nothing to identify a Fault.
    csv = tmp_path / "no_cause.csv"
    csv.write_text(
        "timestamp_start,state,duration_seconds\n"
        "2026-06-23 06:00:00,Stopped,600\n",
        encoding="utf-8",
    )
    assert fault_intervals(_ctx_for(csv)) == ()
    # No start timestamp -> no inter-arrival basis.
    csv2 = tmp_path / "no_start.csv"
    csv2.write_text(
        "stop_cause,state,duration_seconds\nFault,Stopped,600\n", encoding="utf-8"
    )
    assert fault_intervals(_ctx_for(csv2)) == ()


# --- mtbf_band: median + IQR via the statistics stdlib -----------------------


def test_mtbf_band_matches_hand_computed_quartiles():
    # 8 points 2..16 step 2: median (8+10)/2 = 9; inclusive quartiles 5.5 / 12.5.
    median, q1, q3 = mtbf_band([2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0])
    assert median == pytest.approx(9.0)
    assert q1 == pytest.approx(5.5)
    assert q3 == pytest.approx(12.5)
    assert q1 <= median <= q3                       # band brackets the median


def test_mtbf_band_median_equals_statistics_median():
    vals = [100.0, 300.0, 500.0, 700.0, 900.0, 1100.0, 1300.0]
    median, _q1, _q3 = mtbf_band(vals)
    assert median == pytest.approx(statistics.median(vals))


def test_mtbf_band_none_when_too_few_intervals():
    # Fewer than the floor -> the tile declines rather than band a handful of pts.
    assert mtbf_band([1.0, 2.0, 3.0]) is None
    assert mtbf_band([]) is None


# --- 6-month-CSV sanity (the grilling's cited numbers) ------------------------
# Not exact oracles (seed-deterministic but not hand-computed) — guards the
# magnitude + the "wide band, CV ~ 0.9" framing node 5 hinges the band-not-
# countdown decision on. A regeneration that broke the Fault load would trip it.


def test_six_month_fault_intervals_count_and_spread():
    intervals = fault_intervals(_ctx_for(_FICTIONAL_6MONTH))
    # ~201 Fault events -> ~200 inter-arrival intervals (handoff's sanity count).
    assert 180 <= len(intervals) <= 220
    # CV ~ 0.9 -> the spread is large; a band, not a point, is the honest read.
    mean = sum(intervals) / len(intervals)
    cv = statistics.pstdev(intervals) / mean
    assert 0.7 < cv < 1.1
    # MTBF lands in a realistic half-day-ish range (median ~16h on this dataset).
    median, q1, q3 = mtbf_band(intervals)
    assert median is not None
    assert 6 * 3600 < median < 30 * 3600          # 6h..30h
    assert q1 < median < q3                        # IQR brackets the median
    assert (q3 - q1) > mean                        # wide: IQR wider than the mean gap
