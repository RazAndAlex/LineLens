"""Pure ``server.logic`` tests — the UI-free seams extracted from app.py.

Ported from the app render-path suites (tests/test_app_preview.py,
tests/test_app_oee_render.py, tests/test_app_forecast_render.py,
tests/test_app_maintenance_render.py), which keep their streamlit-stub
(``_FakeST``/``_CaptureST``) and plotly-figure tests unchanged against
app.py's re-exports. Everything here imports from ``server.logic`` and needs
neither the ``ui`` extra nor a browser: the silent auto-map, the Pareto prep,
the forecast view/resolve layer, the what-if bridge helpers, the due-window
phrasing, and the readout formatters.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from linelens import ingestion, schema, summaries, validation
from linelens.maintenance import DueWindow
from linelens.models import CanonicalRole
from linelens.oee import compute_oee, oee_from_context
from server import logic

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FICTIONAL_MONTH = _REPO_ROOT / "sample_data" / "fictional_month.csv"
_FICTIONAL_6MONTH = _REPO_ROOT / "sample_data" / "fictional_6month.csv"


def _load():
    return ingestion.load_csv(_FICTIONAL_6MONTH)


def _ctx_for(csv_path: Path):
    raw, profile = ingestion.load_csv(csv_path)
    sug = schema.suggest_roles(profile.columns)
    role_to_col = {role: col for col, (role, _conf) in sug.items()}
    mapping = schema.build_mapping(role_to_col)
    return validation.make_context(raw, profile, mapping)


def _production_totals():
    return summaries.summarize(_ctx_for(_FICTIONAL_MONTH)).production_totals


# --- _auto_roles: conflict-free silent map ------------------------------------


def test_auto_roles_resolves_conflicts_by_confidence():
    suggestions = {
        "good": (CanonicalRole.GOOD_COUNT, 0.7),        # keyword substring
        "good_count": (CanonicalRole.GOOD_COUNT, 1.0),  # exact match wins
        "state": (CanonicalRole.STATE, 1.0),
    }
    roles = logic._auto_roles(suggestions)
    assert roles[CanonicalRole.GOOD_COUNT] == "good_count"
    assert roles[CanonicalRole.STATE] == "state"
    assert len(roles) == 2  # conflict-free: one column per role


def test_auto_roles_skips_none_suggestions():
    assert logic._auto_roles({"mystery": (None, 0.0)}) == {}


# --- _auto_counters: numeric leftovers, not role-mapped measures ----------------


def test_auto_counters_excludes_role_mapped_numerics():
    _raw, profile = _load()
    roles = logic._auto_roles(
        {c: (r, 1.0) for c, r in
         [("good_count", CanonicalRole.GOOD_COUNT),
          ("reject_count", CanonicalRole.REJECT_COUNT),
          ("duration_seconds", CanonicalRole.DURATION),
          ("speed_target", CanonicalRole.SPEED_TARGET),
          ("speed_actual", CanonicalRole.SPEED_ACTUAL)]}
    )
    # the fictional file's numerics are all role-mapped measures -> nothing left
    assert logic._auto_counters(profile, roles) == []
    # drop one mapping -> that numeric column becomes a counter candidate
    del roles[CanonicalRole.SPEED_ACTUAL]
    assert logic._auto_counters(profile, roles) == ["speed_actual"]


# --- _single_machine_col: hide the picker for single-machine files --------------


def test_single_machine_col_detects_one_machine():
    raw, _profile = _load()
    roles = {CanonicalRole.MACHINE_ID: "machine_id"}
    assert logic._single_machine_col(raw, roles) == "machine_id"
    multi = raw.copy()
    multi.loc[multi.index[:10], "machine_id"] = "M02"
    assert logic._single_machine_col(multi, roles) is None
    assert logic._single_machine_col(raw, {}) is None  # no machine role mapped


# --- _preview_summary: plain words, honest about the unrecognized ---------------


def test_preview_summary_states_rows_span_machines_recipes_roles():
    raw, profile = _load()
    roles = logic._auto_roles(schema.suggest_roles(profile.columns))
    text = logic._preview_summary(raw, profile, roles)
    assert f"{profile.row_count:,} rows" in text
    assert "2026-06-23 → 2026-12-19" in text and "(180 days)" in text
    assert "1 machine (M01)" in text
    assert "2 recipes" in text
    assert "Recognized:" in text and "good_count" in text
    # every fictional column is recognized -> no honest "not recognized" tail
    assert "Not recognized" not in text


def test_preview_summary_names_unrecognized_columns():
    raw, profile = _load()
    roles = {CanonicalRole.STATE: "state"}  # nearly nothing recognized
    text = logic._preview_summary(raw, profile, roles)
    assert "Not recognized: machine_id" in text
    assert "ignored" in text


# --- color-by-message helpers (ADR-0010 decision 10) ---------------------------


def test_loss_color_map_tiers_by_cumulative_impact():
    # 3 unplanned causes: 60 / 30 / 10 -> vital few (60) strong, middle (30)
    # base, tail (10) deep. A planned cause is always neutral.
    cmap = logic._loss_color_map(
        ["A", "B", "C", "Planned"], [60.0, 30.0, 10.0, 50.0], {"Planned"})
    assert cmap["A"] == logic._LOSS_STRONG
    assert cmap["B"] == logic._DOWN
    assert cmap["C"] == logic._LOSS_DEEP
    assert cmap["Planned"] == logic._INK_MUTED


def test_loss_color_map_all_small_shares_start_strong():
    # many tiny causes: the first (biggest) still opens the strong tier
    cmap = logic._loss_color_map(["x", "y", "z"], [3.0, 2.0, 1.0], set())
    assert cmap["x"] == logic._LOSS_STRONG
    assert cmap["z"] == logic._LOSS_DEEP  # past the 80% split


def test_planned_causes_reads_the_planned_flag():
    raw, profile = _load()
    sug = schema.suggest_roles(profile.columns)
    ctx = validation.make_context(
        raw, profile, schema.build_mapping({r: c for c, (r, _x) in sug.items()}))
    planned = logic._planned_causes(ctx)
    assert planned == {"Changeover", "Maintenance"}


# --- Pareto prep: ranking + cumulative, no plotly needed ------------------


def _degenerate_result():
    """A single planned Changeover: no run/unplanned/idle time and no parts, so
    Availability, Performance and Quality are all degenerate with notes.
    (Changeover is planned, so it is also absent from bottles_lost.)"""
    df = pd.DataFrame(
        [("Stopped", "Changeover", 2400, 0, 1800, 0, 0, True)],
        columns=[
            "state", "stop_cause", "speed_target", "speed_actual",
            "duration_seconds", "good_count", "reject_count", "planned",
        ],
    )
    return compute_oee(
        state=df["state"], stop_cause=df["stop_cause"], duration=df["duration_seconds"],
        planned=df["planned"], speed_target=df["speed_target"],
        speed_actual=df["speed_actual"], good=df["good_count"], reject=df["reject_count"],
    )


def test_pareto_series_preserves_ranking_and_cumulative():
    r = oee_from_context(_ctx_for(_FICTIONAL_MONTH))
    assert r is not None
    causes, bottles, cum = logic._pareto_series(r)
    # M4's seed-deterministic ranking (Changeover excluded as planned)
    assert causes == ["Starvation", "External", "Buildup", "Fault", "Operator", "Supplies"]
    # bottles stay in the descending order M4 already established
    assert bottles == [b.bottles for b in r.bottles_lost]
    assert bottles == sorted(bottles, reverse=True)
    # cumulative % is monotonic non-decreasing and closes at 100
    assert cum == sorted(cum)
    assert cum[-1] == pytest.approx(100.0, abs=1e-6)
    assert cum[0] > 0


def test_pareto_series_empty_when_nothing_priced():
    r = _degenerate_result()  # planned Changeover only -> no unplanned cause
    assert r.bottles_lost == ()
    assert logic._pareto_series(r) == ([], [], [])


# --- _daily_good_series: dated daily good parts from the totals frame --------


def test_daily_good_series_is_the_dated_good_metric():
    frame = _production_totals()
    series = logic._daily_good_series(frame)
    assert series is not None
    dates, values = series
    assert all(hasattr(d, "isoformat") for d in dates)   # real dates, not strings
    assert dates == sorted(dates)                         # sorted chronologically
    assert len(values) == len(dates) >= 7                 # a full month of days
    assert all(v > 0 for v in values)                     # real production


def test_daily_good_series_none_without_day_scope():
    # overall-only frame -> no day rows -> None.
    frame = _production_totals()
    assert logic._daily_good_series(frame[frame.scope == "overall"]) is None


# --- _to_forecast_view / _resolve_forecast: the technique-agnostic layer ------


def test_to_forecast_view_normalizes_the_deterministic_line():
    from linelens.forecast import forecast

    dates, values = logic._daily_good_series(_production_totals())
    fc = forecast(dates, values)
    assert fc is not None
    view = logic._to_forecast_view(fc, "linear")
    assert view.technique == "linear"
    assert list(view.central) == list(fc.line)          # the deterministic line
    assert len(view.line_dates) == len(dates) + logic._FORECAST_HORIZON_DAYS


def test_resolve_forecast_month_resolves_ok():
    dates, values = logic._daily_good_series(_production_totals())
    view, reason = logic._resolve_forecast(dates, values)
    assert reason == "ok"
    assert view is not None
    assert view.technique in {"linear", "gradient-boosted"}


def test_resolve_forecast_too_few_days():
    dates, values = logic._daily_good_series(_production_totals())
    view, reason = logic._resolve_forecast(dates[:5], values[:5])
    assert view is None
    assert reason == "too_few"


def test_resolve_forecast_declines_zero_scatter():
    """A perfectly linear daily series has zero residual scatter, so the band
    collapses to the line — decline rather than draw a confident single number
    (ADR-0002)."""
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(10)]
    values = [20000.0 + 100.0 * i for i in range(10)]
    view, reason = logic._resolve_forecast(days, values)
    assert view is None
    assert reason == "zero_scatter"


def test_resolve_forecast_horizon_param_extends_the_view():
    """The horizon is a parameter (default _FORECAST_HORIZON_DAYS, which the
    Streamlit app relies on); the API passes a longer display horizon."""
    dates, values = logic._daily_good_series(_production_totals())
    view, reason = logic._resolve_forecast(dates, values, horizon=14)
    assert reason == "ok"
    assert view is not None
    assert len(view.line_dates) == len(dates) + 14
    assert len(view.band_dates) == 15


# --- _recovered / _lever_deltas: the what-if bridge must close ----------------


def test_recovered_equals_the_lever_deltas_sum():
    # Starvation fully cut on the sample month: the one moved lever. The
    # floating Δs must sum exactly to the total recovered (the waterfall's
    # bridge invariant) — pure here, plotly-only in the render suite.
    from linelens.whatif import whatif_from_context

    ctx = _ctx_for(_FICTIONAL_MONTH)
    baseline = oee_from_context(ctx)
    hypo = whatif_from_context(ctx, {"Starvation": 1.0})
    assert baseline is not None and hypo is not None
    deltas = logic._lever_deltas(baseline, hypo, {"Starvation": 1.0})
    assert [cause for cause, _d in deltas] == ["Starvation"]
    base_bl = {b.cause: b.bottles for b in baseline.bottles_lost}
    # a fully-recovered cause drops out of hypo.bottles_lost -> the full cut
    assert deltas[0][1] == pytest.approx(base_bl["Starvation"], abs=1e-6)
    assert sum(d for _c, d in deltas) == pytest.approx(
        logic._recovered(baseline, hypo), abs=1e-6)


def test_lever_deltas_empty_when_no_lever_moved():
    from linelens.whatif import whatif_from_context

    ctx = _ctx_for(_FICTIONAL_MONTH)
    baseline = oee_from_context(ctx)
    hypo = whatif_from_context(ctx, {})  # baseline == hypo
    assert baseline is not None and hypo is not None
    assert logic._lever_deltas(baseline, hypo, {}) == []
    assert logic._recovered(baseline, hypo) == pytest.approx(0.0, abs=1e-9)


# --- the phrasing helper: a window in every shape, never a bare date ----------


def test_phrasing_dated_window():
    due = DueWindow(remaining_early=1000.0, remaining_late=3000.0,
                    date_early=date(2026, 6, 25), date_late=date(2026, 6, 29),
                    adjusted_earlier=False, reasons=())
    head, detail = logic._due_window_phrasing(due)
    assert head == "2026-06-25 → 2026-06-29"
    assert "1,000–3,000 bottles" in detail
    assert "window, not a date" in detail


def test_phrasing_overdue():
    due = DueWindow(remaining_early=0.0, remaining_late=0.0,
                    date_early=date(2026, 6, 23), date_late=date(2026, 6, 23),
                    adjusted_earlier=False, reasons=())
    head, detail = logic._due_window_phrasing(due)
    assert head == "Due now"
    assert "passed" in detail


def test_phrasing_bottles_only_when_no_pace():
    due = DueWindow(remaining_early=1000.0, remaining_late=3000.0,
                    date_early=None, date_late=None,
                    adjusted_earlier=False, reasons=())
    head, detail = logic._due_window_phrasing(due)
    assert head == "1,000–3,000 bottles from now"
    assert "bottles only" in detail


def test_phrasing_single_point_window_is_never_a_bare_date():
    # the equal-dates shape (2 service events -> one learned interval, no
    # spread): the headline names the point AND the missing spread — never a
    # bare date (ADR-0009 decision 4: always a window).
    due = DueWindow(remaining_early=1500.0, remaining_late=1500.0,
                    date_early=date(2026, 6, 30), date_late=date(2026, 6, 30),
                    adjusted_earlier=False, reasons=())
    head, detail = logic._due_window_phrasing(due)
    assert "2026-06-30" in head
    assert "single point" in head
    assert "no spread yet" in detail
    assert head != "2026-06-30"  # not a bare date


# --- readout formatters ---------------------------------------------------------


def test_fmt_span_readout():
    assert logic._fmt_span(None) == ""
    assert logic._fmt_span(45) == "45s"
    assert logic._fmt_span(600) == "10m"
    assert logic._fmt_span(15.8 * 3600) == "15.8h"
    assert logic._fmt_span(3 * 86400) == "3.0d"


def test_fmt_seconds_and_fmt_num_readouts():
    assert logic._fmt_seconds(None) == ""
    assert logic._fmt_seconds(30) == "30s"
    assert logic._fmt_seconds(45 * 60) == "45m"
    assert logic._fmt_seconds(2 * 3600 + 15 * 60) == "2h 15m"
    assert logic._fmt_num(None) == ""
    assert logic._fmt_num(87000) == "87,000"
    assert logic._fmt_num(75) == "75"
    assert logic._fmt_num(96.4) == "96.4"
