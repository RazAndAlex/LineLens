"""M5 render-path wiring tests (app.py KPI cards + Pareto prep).

M5 is rendering: KPI card tiles + a Pareto chart replace the raw tables. Its
narrowest check is "cards render; Pareto ranks by bottles lost" -- visual, so
running the app is the real verification. These tests guard the *wiring*: the
render helpers consume an ``OEEResult`` without throwing, the four card tiles
format the KPIs (and surface a degenerate note instead of a bare 0%), and the
Pareto prep preserves M4's descending ranking and derives a correct cumulative
curve.

The suite stays free of the ``ui`` extra (pyproject): streamlit/plotly are
lazy-imported inside ``app.main``, so ``import app`` works without them, and the
helpers take ``st``/``px``/``go`` as parameters -- a lightweight fake ``st``
exercises ``_render_kpi_cards`` with no streamlit installed. The Pareto figure
itself is built with plotly and verified by running the app; the pure
``_pareto_series`` prep is tested here.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import app
from linelens import ingestion, schema, validation
from linelens.oee import BottlesLost, OEEResult, compute_oee, oee_from_context

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FICTIONAL_MONTH = _REPO_ROOT / "sample_data" / "fictional_month.csv"


def _ctx_for(csv_path: Path):
    raw, profile = ingestion.load_csv(csv_path)
    sug = schema.suggest_roles(profile.columns)
    role_to_col = {role: col for col, (role, _conf) in sug.items()}
    mapping = schema.build_mapping(role_to_col)
    return validation.make_context(raw, profile, mapping)


class _FakeColumn:
    def __init__(self, st): self._st = st
    def __enter__(self): return self
    def __exit__(self, *exc): return False


class _FakeST:
    """Records metric/caption/warning calls; columns() yields no-op context mgrs."""

    def __init__(self):
        self.metrics: list[tuple[str, object]] = []
        self.captions: list[str] = []
        self.warnings: list[str] = []

    def columns(self, n):
        return [_FakeColumn(self) for _ in range(n)]

    def metric(self, label, value, help=None, **_):
        self.metrics.append((label, value))

    def caption(self, text):
        self.captions.append(text)

    def warning(self, text):
        self.warnings.append(text)


def _degenerate_result() -> OEEResult:
    """A single planned Changeover: no run/unplanned/idle time and no parts, so
    Availability, Performance and Quality are all degenerate with notes -- the
    path the cards must surface instead of a bare 0%. (Changeover is planned, so
    it is also absent from bottles_lost.)"""
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


def _perf_undefined_result() -> OEEResult:
    """Running rows but zero target throughput -> Performance undefined (note),
    while Availability and Quality are well-defined. Proves the OEE tile must
    blank when *one* factor is degenerate, and that the OEE caption echoes the
    blank factor instead of a contradictory 0.0%."""
    df = pd.DataFrame(
        [("Running", None, 0, 0, 3600, 100, 5, False)],
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


# --- KPI cards: the four tiles render from a real result ------------------


def test_kpi_cards_render_four_tiles_for_fictional_month():
    r = oee_from_context(_ctx_for(_FICTIONAL_MONTH))
    assert r is not None
    fake = _FakeST()
    app._render_kpi_cards(fake, r)  # must not throw
    labels = [label for label, _ in fake.metrics]
    assert labels == ["Availability", "Performance", "Quality", "OEE"]
    values = {label: value for label, value in fake.metrics}
    # well-formed month -> no degenerate notes -> each tile is a percent string
    assert all(isinstance(v, str) and v.endswith("%") for v in values.values())
    # the value is the KPI ratio formatted by the helper (eyeball: A 88.7 / OEE 80.0)
    assert values["Availability"] == f"{r.availability * 100:.1f}%"
    assert values["OEE"] == f"{r.oee * 100:.1f}%"
    # one derivation caption per tile, no leftover warning
    assert len(fake.captions) == 4
    assert fake.warnings == []


def test_kpi_cards_surface_degenerate_note_instead_of_bare_zero():
    r = _degenerate_result()
    fake = _FakeST()
    app._render_kpi_cards(fake, r)
    by_label = {label: value for label, value in fake.metrics}
    # all three KPIs degenerate -> their tiles show an em dash, never a bare 0.0%
    assert by_label["Availability"] == "—"
    assert by_label["Performance"] == "—"
    assert by_label["Quality"] == "—"
    # OEE is a product of the three -> undefined when any factor is, not 0.0%
    assert by_label["OEE"] == "—"
    # the degenerate reason lands as the tile's caption
    joined = " | ".join(fake.captions)
    assert "Availability" in joined
    assert "Performance" in joined
    assert "Quality" in joined


def test_kpi_cards_oee_blanks_when_one_factor_is_undefined():
    """Only Performance degenerate: A/Q show real percents, OEE still blanks."""
    r = _perf_undefined_result()
    fake = _FakeST()
    app._render_kpi_cards(fake, r)
    by_label = {label: value for label, value in fake.metrics}
    assert by_label["Availability"] == "100.0%"           # run-only, no losses
    assert by_label["Performance"] == "—"                 # zero target throughput
    assert by_label["Quality"] == f"{r.quality * 100:.1f}%"
    assert by_label["OEE"] == "—"                         # a factor undefined
    # the OEE caption echoes the blank factor (× — ×), not a 0.0% for it
    assert "× — ×" in fake.captions[3]


# --- Pareto prep: ranking + cumulative, no plotly needed ------------------


def test_pareto_series_preserves_ranking_and_cumulative():
    r = oee_from_context(_ctx_for(_FICTIONAL_MONTH))
    assert r is not None
    causes, bottles, cum = app._pareto_series(r)
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
    assert app._pareto_series(r) == ([], [], [])


# --- The Pareto figure itself (needs plotly; skipped without the ui extra) --


def test_pareto_figure_has_distinct_dual_axis_titles():
    """Regression guard: left (bottles) and right (cumulative %) axis titles
    must both survive. The shared _axis_title helper uses update_yaxes with no
    selector, which would overwrite the secondary yaxis2 title -- this test
    would have caught that ship-blocker. Needs plotly (ui extra); importorskip
    keeps the default suite green when it's absent."""
    pytest.importorskip("plotly")
    import plotly.express as px
    import plotly.graph_objects as go

    r = oee_from_context(_ctx_for(_FICTIONAL_MONTH))
    assert r is not None

    class _CaptureST(_FakeST):
        def __init__(self):
            super().__init__()
            self.fig = None

        def plotly_chart(self, fig, **_):
            self.fig = fig

    fake = _CaptureST()
    app._render_pareto(fake, px, go, r)
    fig = fake.fig
    assert fig is not None
    # bar + cumulative line, on separate axes
    assert len(fig.data) == 2
    assert isinstance(fig.data[0], go.Bar)
    assert isinstance(fig.data[1], go.Scatter)
    assert fig.data[1].yaxis == "y2"
    # the bug this guards: the two axis titles must differ
    assert fig.layout.yaxis.title.text == "bottles lost"
    assert fig.layout.yaxis2.title.text == "cumulative %"
    # bar order follows the pre-ranked bottles_lost (Starvation first)
    assert list(fig.data[0].x) == [b.cause for b in r.bottles_lost]


def test_pareto_skips_figure_when_all_bottles_zero():
    """All causes priced at 0 (e.g. speed_target unmapped -> target 0) -> no
    meaningful Pareto; the 'nothing priced' caption renders and no figure is
    built. The early return precedes any px/go use, so this runs ui-free
    (_FakeST has no plotly_chart, so a stray figure call would raise)."""
    zero_oee = OEEResult(
        availability=0.5, performance=0.5, quality=1.0, oee=0.25,
        run_time=1.0, unplanned_stop_time=1.0, planned_stop_time=0.0, idle_time=0.0,
        good=10.0, reject=0.0,
        bottles_lost=(BottlesLost("Starvation", 900.0, 0.0, 0.0),),
    )
    fake = _FakeST()
    app._render_pareto(fake, None, None, zero_oee)
    assert any("No bottles lost to price" in c for c in fake.captions)
