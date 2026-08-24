"""Predictive-maintenance tests (M9): service counter + learned due window.

``linelens.maintenance`` is the pure core ADR-0009 specifies: Maintenance stops
plus repair-length Faults are the labeled service events; the service counter
is bottles produced since the last one; the service interval is the learned
median + spread of bottles-between-services; the due window counts the counter
down against it and is pulled earlier only by condition signals, always with
the reason stated. These are hand-computed oracles (contrast the learned-model
gates in test_forecast_ml.py), plus 6-month/month-CSV integration sanity.

The suite stays free of the ``ui`` extra: the module is pandas/stdlib over a
``ValidationContext``, mirroring ``oee_from_context`` / ``reliability``.
"""
from __future__ import annotations

import statistics
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from linelens import ingestion, schema, validation
from linelens import maintenance

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FICTIONAL_6MONTH = _REPO_ROOT / "sample_data" / "fictional_6month.csv"
_FICTIONAL_MONTH = _REPO_ROOT / "sample_data" / "fictional_month.csv"

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
    csv = tmp_path / "maint.csv"
    csv.write_text(_COLS + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return _ctx_for(csv)


# --- repair_threshold: the learned routine/repair split (Tukey fence) --------


def test_repair_threshold_is_the_tukey_fence():
    # 9 points 100..800 step 100 + one 4000 repair. Inclusive quartiles of the
    # sorted 9: q1 = 300, q3 = 700 -> IQR 400 -> fence 700 + 1.5*400 = 1300.
    durations = [100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0, 800.0, 4000.0]
    assert maintenance.repair_threshold(durations) == pytest.approx(1300.0)


def test_repair_threshold_none_when_too_few_faults():
    # IQR on a handful of points is noise; no threshold, no repair inference.
    assert maintenance.repair_threshold([100.0, 200.0, 300.0]) is None
    assert maintenance.repair_threshold([]) is None


# --- service_events: Maintenance stops + repair-length Faults -----------------

_EVENTS_ROWS = [
    # two routine Faults (600s < threshold), a repair Fault (4000s > threshold),
    # a long Starvation (long but not a Fault -> never a service event),
    # and a Maintenance stop (always a service event). Out of source order.
    "M01,2026-06-24 09:30:00,2026-06-24 09:40:00,Stopped,Fault,A,R,2200,0,600,0,0,False",
    "M01,2026-06-23 07:00:00,2026-06-23 07:30:00,Stopped,Maintenance,A,R,2200,0,1800,0,0,True",
    "M01,2026-06-23 12:00:00,2026-06-23 12:10:00,Stopped,Fault,A,R,2200,0,600,0,0,False",
    "M01,2026-06-23 14:00:00,2026-06-23 15:10:00,Stopped,Starvation,A,R,2200,0,4200,0,0,False",
    "M01,2026-06-23 18:00:00,2026-06-23 19:06:40,Stopped,Fault,A,R,2200,0,4000,0,0,False",
]


def test_service_events_selects_maintenance_and_repair_faults(tmp_path):
    ctx = _ctx_from_rows(tmp_path, _EVENTS_ROWS)
    events = maintenance.service_events(ctx, threshold=1300.0)
    kinds = [e.kind for e in events]
    assert kinds == ["maintenance", "repair"]  # start-ordered, not file order
    # the repair is the 4000s Fault at 18:00, not the 600s routine one
    assert events[1].start == pd.Timestamp("2026-06-23 18:00:00")
    assert events[1].duration_s == pytest.approx(4000.0)


def test_service_events_none_threshold_means_maintenance_only(tmp_path):
    ctx = _ctx_from_rows(tmp_path, _EVENTS_ROWS)
    events = maintenance.service_events(ctx, threshold=None)
    assert [e.kind for e in events] == ["maintenance"]


# --- service counter + bottles-between-services -------------------------------

# One production day with two service events (a Maintenance stop 07:00-07:30
# and a repair Fault 09:30-10:00) and running intervals around them:
#   06:00-07:00  Running  1000 good          (before any service)
#   07:00-07:30  Stopped   Maintenance        (service 1)
#   07:30-09:30  Running  2000 good           (between services)
#   09:30-10:00  Stopped   Fault 1800s? no -> use 4000s repair (service 2)
#   10:00-12:00  Running  3000 good + 100 rej (after last service)
_COUNTER_ROWS = [
    "M01,2026-06-23 06:00:00,2026-06-23 07:00:00,Running,,A,R,2200,1000,3600,1000,0,False",
    "M01,2026-06-23 07:00:00,2026-06-23 07:30:00,Stopped,Maintenance,A,R,2200,0,1800,0,0,True",
    "M01,2026-06-23 07:30:00,2026-06-23 09:30:00,Running,,A,R,2200,1000,7200,2000,0,False",
    "M01,2026-06-23 09:30:00,2026-06-23 10:10:00,Stopped,Fault,A,R,2200,0,2400,0,0,False",
    "M01,2026-06-23 10:10:00,2026-06-23 12:00:00,Running,,A,R,2200,1000,6600,3000,100,False",
]


def test_bottles_between_services_counts_only_between(tmp_path):
    ctx = _ctx_from_rows(tmp_path, _COUNTER_ROWS)
    events = maintenance.service_events(ctx, threshold=1300.0)
    assert [e.kind for e in events] == ["maintenance", "repair"]
    gaps = maintenance.bottles_between(ctx, events)
    # service 1 ends 07:30, service 2 starts 09:30 -> only the 2000-good run.
    assert gaps == (2000.0,)


def test_service_counter_counts_production_after_last_service_end(tmp_path):
    ctx = _ctx_from_rows(tmp_path, _COUNTER_ROWS)
    events = maintenance.service_events(ctx, threshold=1300.0)
    # last service (the repair) ends 10:10 -> the 3000 good + 100 reject run.
    # Rejects count: wear accrues on every bottle through the machine.
    assert maintenance.service_counter(ctx, events) == pytest.approx(3100.0)


def test_service_counter_without_events_is_whole_file_production(tmp_path):
    rows = [r for r in _COUNTER_ROWS if "Maintenance" not in r and "Fault" not in r]
    ctx = _ctx_from_rows(tmp_path, rows)
    events = maintenance.service_events(ctx, threshold=1300.0)
    assert events == ()
    # no service event in the data -> counter covers the whole file (the report
    # notes the last service predates it).
    assert maintenance.service_counter(ctx, events) == pytest.approx(6100.0)


# --- learn_service_interval: median + spread, thin-data floor ------------------


def test_learn_service_interval_hand_computed_quartiles():
    # 5 gaps 1000..5000: median 3000, inclusive quartiles 2000 / 4000.
    iv = maintenance.learn_service_interval([1000.0, 2000.0, 3000.0, 4000.0, 5000.0])
    assert iv is not None
    assert iv.median == pytest.approx(3000.0)
    assert iv.q1 == pytest.approx(2000.0)
    assert iv.q3 == pytest.approx(4000.0)
    assert iv.n == 5


def test_learn_service_interval_single_gap_has_no_spread():
    # 2 service events -> 1 gap: the rhythm is learned, the spread is unknown
    # (q1 == median == q3; n says it honestly). ADR-0009's thin-data floor.
    iv = maintenance.learn_service_interval([2000.0])
    assert iv is not None
    assert iv.median == iv.q1 == iv.q3 == pytest.approx(2000.0)
    assert iv.n == 1


def test_learn_service_interval_none_below_two_events():
    assert maintenance.learn_service_interval([]) is None


# --- condition_signals: earlier-only triggers, reasons always stated ----------


def test_condition_signals_fire_below_the_floors():
    assert maintenance.condition_signals(-0.001, None) == ("Performance is trending down",)
    assert maintenance.condition_signals(None, 1.30) == ("Fault rate is rising",)
    assert maintenance.condition_signals(-0.001, 1.30) == (
        "Performance is trending down", "Fault rate is rising")


def test_condition_signals_quiet_above_the_floors():
    assert maintenance.condition_signals(-0.0001, 1.10) == ()
    assert maintenance.condition_signals(0.002, None) == ()
    assert maintenance.condition_signals(None, None) == ()


# --- due_window: the interval counted down, earlier-only adjustment ------------

_IV = maintenance.ServiceInterval(median=3000.0, q1=2000.0, q3=4000.0, n=5)
_D0 = date(2026, 6, 23)


def test_due_window_hand_computed_edges_and_dates():
    w = maintenance.due_window(1000.0, _IV, _D0, daily_rate=500.0, signals=())
    # early edge = q1 - counter = 1000 bottles -> 2 days at 500/day.
    # late edge  = q3 - counter = 3000 bottles -> 6 days.
    assert w.remaining_early == pytest.approx(1000.0)
    assert w.remaining_late == pytest.approx(3000.0)
    assert w.date_early == date(2026, 6, 25)
    assert w.date_late == date(2026, 6, 29)
    assert w.adjusted_earlier is False
    assert w.reasons == ()


def test_due_window_pulls_earlier_only_with_reasons():
    base = maintenance.due_window(1000.0, _IV, _D0, daily_rate=500.0, signals=())
    one = maintenance.due_window(1000.0, _IV, _D0, daily_rate=500.0,
                                 signals=("Performance is trending down",))
    # one signal pulls both edges earlier by half the IQR (1000 bottles).
    assert one.remaining_early == pytest.approx(0.0)
    assert one.remaining_late == pytest.approx(2000.0)
    assert one.date_early == _D0
    assert one.date_late == date(2026, 6, 27)
    assert one.adjusted_earlier is True
    assert one.reasons == ("Performance is trending down",)
    # earlier only: never later than the unadjusted window, on either edge.
    assert one.date_early <= base.date_early
    assert one.date_late <= base.date_late
    two = maintenance.due_window(1000.0, _IV, _D0, daily_rate=500.0,
                                 signals=("Performance is trending down",
                                          "Fault rate is rising"))
    assert two.remaining_late == pytest.approx(1000.0)
    assert two.date_late <= one.date_late


def test_due_window_overdue_when_counter_past_the_interval():
    w = maintenance.due_window(5000.0, _IV, _D0, daily_rate=500.0, signals=())
    assert w.remaining_early == w.remaining_late == 0.0
    assert w.date_early == w.date_late == _D0  # due now, not a negative date


def test_due_window_without_production_rate_has_no_dates():
    # a stopped line accrues no bottles, so no honest bottle->date conversion;
    # the bottle window still renders (ADR-0002: decline, don't invent).
    w = maintenance.due_window(1000.0, _IV, _D0, daily_rate=0.0, signals=())
    assert w.remaining_early == pytest.approx(1000.0)
    assert w.date_early is None and w.date_late is None


# --- maintenance_from_context: the thin wrapper over the pure pieces ----------


def test_month_csv_is_counter_only_thin_data():
    # The month file has no service events at all: the counter still renders
    # (whole-file production), the interval/due window honestly decline.
    report = maintenance.maintenance_from_context(_ctx_for(_FICTIONAL_MONTH))
    assert report is not None
    assert report.n_service_events == 0
    assert report.last_service_end is None
    # whole-file production: 1,294,164 good + 5,121 reject (generator's summary).
    assert report.bottles_since_service == pytest.approx(1_299_285.0)
    assert report.interval is None
    assert report.due is None
    assert any("service" in n.lower() for n in report.notes)


def test_six_month_csv_learns_the_rhythm_and_window():
    report = maintenance.maintenance_from_context(_ctx_for(_FICTIONAL_6MONTH))
    assert report is not None
    # 25 weekly Maintenance stops + 8 repair-length Faults (generator, P1).
    assert report.n_service_events == 33
    # the learned fence splits routine faults (<=1080s drifted) from repairs
    # (>=2700s) — anywhere in the dead zone proves the bimodal split was found.
    assert 1080.0 < report.repair_threshold_s < 2700.0
    iv = report.interval
    assert iv is not None and iv.n == 32
    # weekly-ish service cadence at ~37k bottles/day -> the median gap lands in
    # the low hundred-thousands (not exact: repairs interleave the rhythm).
    assert 100_000.0 < iv.median < 400_000.0
    assert iv.q1 <= iv.median <= iv.q3
    # the counter: production since the last service (the final weekly stop),
    # so a few days' worth — well under the interval's late edge.
    assert 0.0 < report.bottles_since_service < iv.q3
    due = report.due
    assert due is not None
    assert due.date_early is not None and due.date_late is not None
    assert due.date_early <= due.date_late
    # The fictional line's Performance genuinely degrades over the 180 days
    # (0.93 -> 0.80, slope ~= -0.0006/day, past the -0.0005 floor), so the
    # condition adjustment fires and pulls the window earlier, reason stated —
    # the earlier-only path exercised end-to-end on the real fixture.
    assert due.adjusted_earlier is True
    assert due.reasons == ("Performance is trending down",)


def test_report_none_without_bottle_axis(tmp_path):
    # no start timestamp mapped -> no counter, no report (mirrors oee's None).
    csv = tmp_path / "no_start.csv"
    csv.write_text("stop_cause,good_count\nMaintenance,100\n", encoding="utf-8")
    assert maintenance.maintenance_from_context(_ctx_for(csv)) is None
