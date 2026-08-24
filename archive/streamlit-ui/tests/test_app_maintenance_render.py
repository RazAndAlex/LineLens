"""M9 render-path wiring tests (app.py maintenance view).

The maintenance view consumes the ``MaintenanceReport`` computed at Analyze
time — the pure core is oracle-tested in tests/test_maintenance.py; here we
guard the *wiring*: the view renders the counter + thin-data message on the
month CSV and the learned window on the 6-month CSV without throwing, and the
plain-words phrasing helper produces a window (never a bare date) in each of
its three shapes. Same fake-st approach as test_app_oee_render.py — no ``ui``
extra needed.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import app
from linelens import ingestion, schema, validation
from linelens.maintenance import DueWindow, maintenance_from_context

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FICTIONAL_6MONTH = _REPO_ROOT / "sample_data" / "fictional_6month.csv"
_FICTIONAL_MONTH = _REPO_ROOT / "sample_data" / "fictional_month.csv"


def _ctx_for(csv_path: Path):
    raw, profile = ingestion.load_csv(csv_path)
    sug = schema.suggest_roles(profile.columns)
    role_to_col = {role: col for col, (role, _conf) in sug.items()}
    mapping = schema.build_mapping(role_to_col)
    return validation.make_context(raw, profile, mapping)


class _FakeST:
    """Records the calls the maintenance view makes."""

    def __init__(self):
        self.metrics: list[tuple[str, object]] = []
        self.captions: list[str] = []
        self.infos: list[str] = []
        self.warnings: list[str] = []

    class _Col:
        def __enter__(self): return self
        def __exit__(self, *exc): return False

    def columns(self, n):
        return [self._Col() for _ in range(n)]

    def subheader(self, _): pass
    def metric(self, label, value, **_): self.metrics.append((label, value))
    def caption(self, text): self.captions.append(text)
    def info(self, text): self.infos.append(text)
    def warning(self, text): self.warnings.append(text)


def _result_for(csv_path: Path) -> dict:
    ctx = _ctx_for(csv_path)
    return {"ctx": ctx, "maintenance": maintenance_from_context(ctx)}


# --- the phrasing helper: a window in every shape, never a bare date ----------


def test_phrasing_dated_window():
    due = DueWindow(remaining_early=1000.0, remaining_late=3000.0,
                    date_early=date(2026, 6, 25), date_late=date(2026, 6, 29),
                    adjusted_earlier=False, reasons=())
    head, detail = app._due_window_phrasing(due)
    assert head == "2026-06-25 → 2026-06-29"
    assert "1,000–3,000 bottles" in detail
    assert "window, not a date" in detail


def test_phrasing_overdue():
    due = DueWindow(remaining_early=0.0, remaining_late=0.0,
                    date_early=date(2026, 6, 23), date_late=date(2026, 6, 23),
                    adjusted_earlier=False, reasons=())
    head, detail = app._due_window_phrasing(due)
    assert head == "Due now"
    assert "passed" in detail


def test_phrasing_bottles_only_when_no_pace():
    due = DueWindow(remaining_early=1000.0, remaining_late=3000.0,
                    date_early=None, date_late=None,
                    adjusted_earlier=False, reasons=())
    head, detail = app._due_window_phrasing(due)
    assert head == "1,000–3,000 bottles from now"
    assert "bottles only" in detail


# --- the view: counter always, window when learned, thin-data message ---------


def test_view_renders_window_on_six_month():
    st = _FakeST()
    app._maintenance_view(st, _result_for(_FICTIONAL_6MONTH))
    labels = [label for label, _v in st.metrics]
    assert "Bottles since last service" in labels
    assert "Service events" in labels
    assert "Service interval (median)" in labels
    assert "Next service due" in labels
    # the 6-month line's Performance degrades -> the adjustment warning shows
    assert any("Pulled earlier" in w for w in st.warnings)


def test_view_is_counter_only_on_month():
    st = _FakeST()
    app._maintenance_view(st, _result_for(_FICTIONAL_MONTH))
    labels = [label for label, _v in st.metrics]
    assert "Bottles since last service" in labels
    assert "Service interval (median)" not in labels
    assert "Next service due" not in labels
    # the honest thin-data message (ADR-0009 decision 5)
    assert any("service" in i.lower() for i in st.infos)


def test_view_declines_without_bottle_axis(tmp_path):
    csv = tmp_path / "no_start.csv"
    csv.write_text("stop_cause,good_count\nMaintenance,100\n", encoding="utf-8")
    st = _FakeST()
    app._maintenance_view(st, _result_for(csv))
    assert not st.metrics
    assert any("start timestamp" in i for i in st.infos)


def test_phrasing_single_point_window_is_never_a_bare_date():
    # the equal-dates shape (2 service events -> one learned interval, no
    # spread): the headline names the point AND the missing spread — never a
    # bare date (ADR-0009 decision 4: always a window).
    due = DueWindow(remaining_early=1500.0, remaining_late=1500.0,
                    date_early=date(2026, 6, 30), date_late=date(2026, 6, 30),
                    adjusted_earlier=False, reasons=())
    head, detail = app._due_window_phrasing(due)
    assert "2026-06-30" in head
    assert "single point" in head
    assert "no spread yet" in detail
    assert head != "2026-06-30"  # not a bare date


def test_view_states_fired_reason_even_without_adjustment():
    # a condition signal fired but couldn't move the window (single learned
    # interval, no spread -> adjusted_earlier False): the reason is still
    # stated (ADR-0009 decision 4), as an info, not the "pulled earlier" warning.
    from linelens.maintenance import DueWindow, MaintenanceReport, ServiceInterval
    report = MaintenanceReport(
        bottles_since_service=1000.0, last_service_end=None, n_service_events=2,
        repair_threshold_s=None,
        interval=ServiceInterval(median=2000.0, q1=2000.0, q3=2000.0, n=1),
        due=DueWindow(remaining_early=1000.0, remaining_late=1000.0,
                      date_early=date(2026, 6, 25), date_late=date(2026, 6, 25),
                      adjusted_earlier=False,
                      reasons=("Performance is trending down",)),
        notes=(),
    )
    st = _FakeST()
    app._maintenance_view(st, {"ctx": None, "maintenance": report})
    assert any("Performance is trending down" in i for i in st.infos)
    assert not st.warnings
