"""Tests for the OEE module (M4).

The M4 narrowest check is "KPI values match a hand-computed sample." The two
fixtures below are hand-computed (see ``.scratch/m4/spec.md`` for the worked
arithmetic) and assert the module reproduces those exact numbers. Fixture A
pins the core A/P/Q/OEE + bottles-lost independent of the Idle decision; the
synthetic Fixture B exercises that decision (Idle in the Availability
denominator under strict OEE) plus the ``planned`` exclusion and a
duration-weighted multi-target bottles-lost.

This is the repo's first real test file — adding it makes ``pytest`` collect
>0 (the plan's known test-suite gap). Run: ``.venv\\Scripts\\python.exe -m pytest``.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from linelens import ingestion, schema, validation
from linelens.models import CanonicalRole
from linelens.oee import OEEResult, compute_oee, oee_from_context

# Tolerance for the hand-computed oracles: the values are exact rationals, so
# 1e-12 is generous while still catching a wrong formula (which would miss by
# far more). Float repr noise stays well under this.
ORACLE_TOL = 1e-12

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FICTIONAL_MONTH = _REPO_ROOT / "sample_data" / "fictional_month.csv"


def _fixture_a() -> pd.DataFrame:
    """First 6 rows of fictional_month.csv — all unplanned, no Idle, one recipe."""
    return pd.DataFrame(
        [
            ("Stopped", "Starvation", 2200, 0, 517, 0, 0, False),
            ("Running", None, 2200, 2017, 3241, 1816, 7, False),
            ("Running", None, 2200, 2043, 2043, 1159, 4, False),
            ("Running", None, 2200, 2086, 1321, 765, 3, False),
            ("Stopped", "Fault", 2200, 0, 368, 0, 0, False),
            ("Stopped", "Supplies", 2200, 0, 162, 0, 0, False),
        ],
        columns=[
            "state", "stop_cause", "speed_target", "speed_actual",
            "duration_seconds", "good_count", "reject_count", "planned",
        ],
    )


def _fixture_b() -> pd.DataFrame:
    """Synthetic round-number fixture — exercises Idle (strict) + planned exclusion."""
    return pd.DataFrame(
        [
            ("Running", None, 2400, 2400, 3600, 2400, 0, False),
            ("Running", None, 2400, 1800, 3600, 1800, 100, False),
            ("Idle", None, 2400, 0, 600, 0, 0, False),
            ("Stopped", "Changeover", 2400, 0, 1800, 0, 0, True),
            ("Stopped", "Starvation", 2400, 0, 900, 0, 0, False),
        ],
        columns=[
            "state", "stop_cause", "speed_target", "speed_actual",
            "duration_seconds", "good_count", "reject_count", "planned",
        ],
    )


def _oee(df: pd.DataFrame) -> OEEResult:
    return compute_oee(
        state=df["state"],
        stop_cause=df["stop_cause"],
        duration=df["duration_seconds"],
        planned=df["planned"],
        speed_target=df["speed_target"],
        speed_actual=df["speed_actual"],
        good=df["good_count"],
        reject=df["reject_count"],
        duration_source="duration_column",
    )


# --- Fixture A: the core formula oracle -----------------------------------


def test_fixture_a_kpis_match_hand_computation():
    """A/P/Q/OEE reproduce the hand-computed first-6-rows sample exactly."""
    r = _oee(_fixture_a())
    assert r.availability == pytest.approx(6605 / 7652, abs=ORACLE_TOL)
    assert r.performance == pytest.approx(13466552 / 14531000, abs=ORACLE_TOL)
    assert r.quality == pytest.approx(3740 / 3754, abs=ORACLE_TOL)
    assert r.oee == pytest.approx(
        (6605 / 7652) * (13466552 / 14531000) * (3740 / 3754), abs=ORACLE_TOL
    )


def test_fixture_a_time_breakdown():
    r = _oee(_fixture_a())
    assert r.run_time == 6605.0
    assert r.unplanned_stop_time == 1047.0  # 517 + 368 + 162
    assert r.idle_time == 0.0
    assert r.planned_stop_time == 0.0
    assert r.good == 3740.0
    assert r.reject == 14.0


def test_fixture_a_bottles_lost_per_cause():
    """Bottles lost = cause_secs * target / 3600, ranked descending."""
    r = _oee(_fixture_a())
    by_cause = {b.cause: b for b in r.bottles_lost}
    assert set(by_cause) == {"Starvation", "Fault", "Supplies"}
    # single recipe -> weighted target collapses to 2200 for each cause
    assert by_cause["Starvation"].bottles == pytest.approx(517 * 2200 / 3600, abs=1e-9)
    assert by_cause["Fault"].bottles == pytest.approx(368 * 2200 / 3600, abs=1e-9)
    assert by_cause["Supplies"].bottles == pytest.approx(162 * 2200 / 3600, abs=1e-9)
    # descending by bottles; Starvation > Fault > Supplies here
    bottles = [b.bottles for b in r.bottles_lost]
    assert bottles == sorted(bottles, reverse=True)


# --- Fixture B: the Idle + planned decision oracle -------------------------


def test_fixture_b_kpis_match_hand_computation():
    """Strict OEE: Idle is in the Availability denominator."""
    r = _oee(_fixture_b())
    # A = 7200 / (7200 + 900 + 600) = 7200/8700
    assert r.availability == pytest.approx(7200 / 8700, abs=ORACLE_TOL)
    assert r.performance == pytest.approx(15120000 / 17280000, abs=ORACLE_TOL)
    assert r.quality == pytest.approx(4200 / 4300, abs=ORACLE_TOL)
    assert r.oee == pytest.approx(
        (7200 / 8700) * (15120000 / 17280000) * (4200 / 4300), abs=ORACLE_TOL
    )


def test_fixture_b_idle_in_availability_denominator():
    """The Idle decision is actually wired: excluding Idle must change A."""
    r = _oee(_fixture_b())
    a_strict = r.availability
    a_idle_excluded = r.run_time / (r.run_time + r.unplanned_stop_time)
    assert a_strict < a_idle_excluded
    assert a_idle_excluded == pytest.approx(7200 / 8100, abs=ORACLE_TOL)


def test_fixture_b_planned_stop_excluded():
    """A planned Changeover is dropped from the unplanned downtime + bottles."""
    r = _oee(_fixture_b())
    assert r.planned_stop_time == 1800.0  # Changeover, counted for transparency
    assert r.unplanned_stop_time == 900.0  # Starvation only
    # bottles_lost prices unplanned causes only -> Changeover absent
    causes = [b.cause for b in r.bottles_lost]
    assert "Changeover" not in causes
    assert causes == ["Starvation"]
    assert r.bottles_lost[0].bottles == pytest.approx(900 * 2400 / 3600, abs=1e-9)


# --- degenerate / guard cases ---------------------------------------------


def test_no_running_time_yields_zero_performance_with_note():
    """Empty Running -> Performance 0.0 (not NaN), and a note explains it."""
    df = pd.DataFrame(
        [("Idle", None, 2400, 0, 600, 0, 0, False)],
        columns=[
            "state", "stop_cause", "speed_target", "speed_actual",
            "duration_seconds", "good_count", "reject_count", "planned",
        ],
    )
    r = _oee(df)
    assert r.performance == 0.0
    assert r.availability == 0.0  # no run time at all
    assert r.oee == 0.0
    assert any("Performance" in note for note in r.notes)


def test_no_parts_yields_zero_quality_with_note():
    df = pd.DataFrame(
        [("Running", None, 2400, 2400, 3600, 0, 0, False)],
        columns=[
            "state", "stop_cause", "speed_target", "speed_actual",
            "duration_seconds", "good_count", "reject_count", "planned",
        ],
    )
    r = _oee(df)
    assert r.quality == 0.0
    assert r.performance == 1.0  # actual == target
    assert any("Quality" in note for note in r.notes)


def test_planned_none_treated_as_all_unplanned():
    """`planned` role unmapped -> every stop is unplanned (no scheduled pass)."""
    df = _fixture_b().drop(columns=["planned"])
    r = compute_oee(
        state=df["state"],
        stop_cause=df["stop_cause"],
        duration=df["duration_seconds"],
        planned=None,
        speed_target=df["speed_target"],
        speed_actual=df["speed_actual"],
        good=df["good_count"],
        reject=df["reject_count"],
    )
    # Changeover now counts as unplanned downtime: A drops, bottles includes it.
    assert r.unplanned_stop_time == 900.0 + 1800.0
    assert r.planned_stop_time == 0.0
    causes = {b.cause for b in r.bottles_lost}
    assert "Changeover" in causes


def test_planned_na_treated_as_unplanned():
    """A blank (NA) planned flag is a loss, not a free pass (ADR-0003).

    The ADR names this as the one place NA semantics matter; the real dataset
    has no blanks today, so this guards the latent path.
    """
    df = pd.DataFrame(
        [("Stopped", "Starvation", 2400, 0, 900, 0, 0, pd.NA)],
        columns=[
            "state", "stop_cause", "speed_target", "speed_actual",
            "duration_seconds", "good_count", "reject_count", "planned",
        ],
    )
    r = _oee(df)
    assert r.unplanned_stop_time == 900.0  # NA -> not planned -> unplanned
    assert r.planned_stop_time == 0.0
    assert {b.cause for b in r.bottles_lost} == {"Starvation"}


# --- end-to-end: oee_from_context on the real dataset ----------------------
# Truth for exact numbers is the hand-computed fixtures above. This test guards
# the ctx wiring + the dataset's sanity (order-of-magnitude + Pareto rank), so
# a regression in oee_from_context or a data regeneration that broke the plan's
# intended ranking is caught.


def _ctx_for(csv_path: Path):
    raw, profile = ingestion.load_csv(csv_path)
    sug = schema.suggest_roles(profile.columns)
    role_to_col = {role: col for col, (role, _conf) in sug.items()}
    mapping = schema.build_mapping(role_to_col)
    return validation.make_context(raw, profile, mapping)


def test_oee_from_context_runs_on_fictional_month():
    r = oee_from_context(_ctx_for(_FICTIONAL_MONTH))
    assert r is not None
    assert r.duration_source == "duration_column"
    # Performance and Quality are Idle-decision-independent, so they should
    # land near the generator's ballpark (P ~0.906, Q ~0.996).
    assert 0.85 < r.performance < 0.95
    assert 0.99 < r.quality < 0.999
    # Strict Availability sits a few points below the generator's idle-excluded
    # 0.915 (Idle added to the denominator); keep a wide-enough band to catch a
    # wrong formula, not float jitter.
    assert 0.80 < r.availability < 0.92
    assert r.oee == pytest.approx(r.availability * r.performance * r.quality, abs=1e-9)


def test_fictional_month_bottles_lost_pareto_ranks_starvation_first():
    """The plan's intended Pareto: Starvation >> External > Buildup > Fault ..."""
    r = oee_from_context(_ctx_for(_FICTIONAL_MONTH))
    assert r is not None
    causes = [b.cause for b in r.bottles_lost]
    # Changeover is planned -> excluded from bottles lost entirely.
    assert "Changeover" not in causes
    # Seed-deterministic dataset: pin the full ranking the spec claims, not just
    # rank 0, so a re-ranking (e.g. Buildup overtaking External) is caught.
    assert causes == ["Starvation", "External", "Buildup", "Fault", "Operator", "Supplies"]
    # bottles descending
    bottles = [b.bottles for b in r.bottles_lost]
    assert bottles == sorted(bottles, reverse=True)
    # every bottle count is positive and finite
    assert all(b > 0 for b in bottles)


# --- oee_from_context None paths (the wrapper's only documented failure mode) --


def test_oee_from_context_returns_none_without_duration(tmp_path):
    """No DURATION column and no start/end timestamps -> None.

    The KPIs are time-based; without a duration axis they're meaningless, so
    the wrapper declines (returns None) rather than computing on a zero axis.
    """
    csv = tmp_path / "no_duration.csv"
    csv.write_text("good_count,reject_count\n10,1\n", encoding="utf-8")
    assert oee_from_context(_ctx_for(csv)) is None


def test_oee_from_context_returns_none_without_state(tmp_path):
    """Duration derivable but no STATE column mapped -> None.

    Without state the Availability split is impossible; M5 must render a
    "not enough data" state on a None result rather than crash.
    """
    csv = tmp_path / "no_state.csv"
    csv.write_text(
        "duration_seconds,good_count,reject_count\n100,10,1\n", encoding="utf-8"
    )
    assert oee_from_context(_ctx_for(csv)) is None


# --- performance_by_day: the dated Performance series (M8 Act-4 input) --------
# The per-day duration-weighted Performance ratio — ADR-0003's identity grouped
# by day. M8's degradation forecast consumes it; it must be the SAME Performance
# as the Now-section KPI, so the oracle pins exact rationals + a single-day
# cross-check against oee_from_context (no drift between the two paths).

from linelens.oee import performance_by_day  # noqa: E402

_PERF_COLS = ",".join([
    "machine_id", "timestamp_start", "timestamp_end", "state", "stop_cause",
    "shift", "recipe", "speed_target", "speed_actual", "duration_seconds",
    "good_count", "reject_count", "planned",
])


def _perf_csv(tmp_path, rows):
    """A ctx from canonical-named rows (auto-mapped via suggest_roles)."""
    csv = tmp_path / "perf.csv"
    csv.write_text(_PERF_COLS + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return _ctx_for(csv)


# Day 1: two Running rows (actual 2090/1980 at target 2200) + a Fault (excluded).
#   perf = (2090*3600 + 1980*1800) / (2200*3600 + 2200*1800) = 11088000/11880000 = 14/15.
# Day 2: one Running row at target -> perf = 1.0.
_PERF_ROWS = [
    "M01,2026-06-23 06:00:00,2026-06-23 07:00:00,Running,,A,Rec,2200,2090,3600,2090,9,False",
    "M01,2026-06-23 07:00:00,2026-06-23 07:30:00,Running,,A,Rec,2200,1980,1800,990,4,False",
    "M01,2026-06-23 07:30:00,2026-06-23 07:40:00,Stopped,Fault,A,Rec,2200,0,600,0,0,False",
    "M01,2026-06-24 06:00:00,2026-06-24 07:00:00,Running,,A,Rec,2200,2200,3600,2200,11,False",
]


def test_performance_by_day_matches_hand_computed_rationals(tmp_path):
    frame = performance_by_day(_perf_csv(tmp_path, _PERF_ROWS))
    assert frame is not None
    assert len(frame) == 2                                  # one row per day
    assert list(frame["date"]) == sorted(frame["date"])     # sorted chronologically
    by_day = {d.date().isoformat(): p for d, p in zip(frame["date"], frame["performance"])}
    assert by_day["2026-06-23"] == pytest.approx(14 / 15, abs=ORACLE_TOL)
    assert by_day["2026-06-24"] == pytest.approx(1.0, abs=ORACLE_TOL)
    # the Fault row is excluded from Performance (a stop, not Running) -> day 1's
    # denominator is the two Running rows only, not the Fault's 600s.
    assert 0.0 < by_day["2026-06-23"] < 1.0


def test_performance_by_day_cross_checks_oee_on_a_single_day(tmp_path):
    """The per-day identity is the same as compute_oee's: scoping the ctx to one
    day, performance_by_day must equal oee_from_context's Performance exactly
    (the no-drift guarantee the Act-4 forecast relies on)."""
    ctx = _perf_csv(tmp_path, _PERF_ROWS)
    day1 = [r for r in _PERF_ROWS if r.startswith("M01,2026-06-23")]
    one_day_ctx = _perf_csv(tmp_path, day1)
    frame = performance_by_day(one_day_ctx)
    assert frame is not None and len(frame) == 1
    overall = oee_from_context(one_day_ctx)
    assert overall is not None
    assert float(frame["performance"].iloc[0]) == pytest.approx(overall.performance, abs=1e-12)


def test_performance_by_day_none_without_time_basis(tmp_path):
    # No start timestamp and no duration -> can't group by day nor derive KPIs.
    csv = tmp_path / "no_time.csv"
    csv.write_text("state,speed_target,speed_actual\nRunning,2200,2000\n", encoding="utf-8")
    assert performance_by_day(_ctx_for(csv)) is None


def test_performance_by_day_none_without_start_timestamp(tmp_path):
    # Duration + state mapped but no start timestamp -> KPIs exist, but there is
    # no day axis to group by, so the dated series is None (oee_from_context is not).
    csv = tmp_path / "no_start.csv"
    csv.write_text(
        "duration_seconds,state,speed_target,speed_actual\n3600,Running,2200,2000\n",
        encoding="utf-8",
    )
    assert performance_by_day(_ctx_for(csv)) is None
    assert oee_from_context(_ctx_for(csv)) is not None
