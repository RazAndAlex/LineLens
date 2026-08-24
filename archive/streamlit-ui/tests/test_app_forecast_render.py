"""M8 Act-3 (future-line) render-path wiring tests (app.py).

M8 (P3/P4) relocated the forecast out of the Now production chart — which now
shows bars only — into Act 3's future-line chart (``app._future_line_chart``):
observed daily good output as bars, continued as a banded forecast (ML when
≥~3 months of history per ADR-0007, else the deterministic Projection) into the
horizon, with a hypothetical what-if line (proportional spread, node 4) when
sliders have moved. The narrowest check is still "band shown; no single
confident number" — visual, so a browser drive is the real verification (see
``.scratch/m8/p4_drive.py``). These tests guard the *wiring*: the daily-good
series is pulled from the totals frame, the forecast traces are built with the
right shape (a dashed central line + a ``tonexty`` band that widens and shows a
*range* on hover, never a point), the future-line chart overlays it with its
x-axis ordered past the last real day, too few days yields an honest "not
enough history" caption, and perfectly-linear (zero-scatter) data declines to
forecast (ADR-0002's defining edge).

The suite stays free of the ``ui`` extra (pyproject): ``_daily_good_series`` /
``_to_forecast_view`` / ``_resolve_forecast`` are pandas-only; the figure tests
``pytest.importorskip("plotly")`` and drive ``_future_line_chart`` (or the trace
builder) with a lightweight fake ``st`` that captures the figure (the M5/M6
pattern), mirroring ``tests/test_app_oee_render.py``'s ``_CaptureST``.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

import app
from linelens import ingestion, schema, summaries, validation

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FICTIONAL_MONTH = _REPO_ROOT / "sample_data" / "fictional_month.csv"


def _ctx_for(csv_path: Path):
    raw, profile = ingestion.load_csv(csv_path)
    sug = schema.suggest_roles(profile.columns)
    role_to_col = {role: col for col, (role, _conf) in sug.items()}
    return validation.make_context(raw, profile, schema.build_mapping(role_to_col))


def _production_totals():
    return summaries.summarize(_ctx_for(_FICTIONAL_MONTH)).production_totals


class _CaptureST:
    """Captures the plotly figure + caption text + metric/info calls; no-op columns."""

    def __init__(self):
        self.fig = None
        self.captions: list[str] = []
        self.metrics: list[tuple] = []
        self.infos: list[str] = []

    def columns(self, n):
        class _C:
            def __enter__(self_): return self_
            def __exit__(self_, *e): return False
        return [_C() for _ in range(n)]

    def metric(self, label, value=None, **k): self.metrics.append((label, value))
    def info(self, text): self.infos.append(text)
    def plotly_chart(self, fig, **_): self.fig = fig
    def caption(self, text): self.captions.append(text)


# --- _daily_good_series: dated daily good parts from the totals frame --------


def test_daily_good_series_is_the_dated_good_metric():
    frame = _production_totals()
    series = app._daily_good_series(frame)
    assert series is not None
    dates, values = series
    assert all(hasattr(d, "isoformat") for d in dates)   # real dates, not strings
    assert dates == sorted(dates)                         # sorted chronologically
    assert len(values) == len(dates) >= 7                 # a full month of days
    assert all(v > 0 for v in values)                     # real production


def test_daily_good_series_none_without_day_scope():
    # overall-only frame -> no day rows -> None.
    frame = _production_totals()
    assert app._daily_good_series(frame[frame.scope == "overall"]) is None


# --- _forecast_traces: dashed trend + a tonexty band that shows a range ------


def test_forecast_traces_shape():
    pytest.importorskip("plotly")
    import plotly.graph_objects as go
    from linelens.forecast import forecast

    dates = [pd.Timestamp("2026-01-01").date() + pd.Timedelta(days=i) for i in range(10)]
    values = [20000 + 100 * i + (50 if i % 2 else -50) for i in range(10)]
    fc = forecast(dates, values)
    assert fc is not None
    # M8: _forecast_traces takes a technique-agnostic _ForecastView (ML and
    # deterministic share no base class; _to_forecast_view reconciles them).
    view = app._to_forecast_view(fc, "linear")
    assert view.technique == "linear"
    assert list(view.central) == list(fc.line)          # the deterministic line
    traces, cat_order = app._forecast_traces(go, view)
    trend, upper, lower = traces
    # central trend: a dashed muted line spanning real + horizon days.
    assert isinstance(trend, go.Scatter)
    assert trend.mode == "lines"
    assert trend.line.dash == "dash"
    assert trend.line.color == app._INK_MUTED
    assert len(trend.x) == len(dates) + app._FORECAST_HORIZON_DAYS
    # the trend line carries no hover — a visual guide only, so no horizon day
    # ever surfaces a bare future number (ADR-0002/0006). Numbers come from the
    # bars (observed) and the band (range).
    assert trend.hoverinfo == "skip"
    # band: upper (invisible) then lower (tonexty fills the ribbon).
    assert isinstance(upper, go.Scatter) and upper.line.width == 0
    assert isinstance(lower, go.Scatter) and lower.fill == "tonexty"
    assert lower.fillcolor.startswith("rgba(57,135,229")   # palette-loyal, recessive
    # the band hover shows a RANGE (lower–upper), never a single point number.
    assert "customdata" in lower.hovertemplate and "{y" in lower.hovertemplate
    assert len(lower.customdata) == len(lower.x)
    # the category array pins real-then-horizon order on the shared date axis.
    assert cat_order == list(trend.x)
    assert cat_order[-1] > cat_order[len(dates) - 1]       # horizon lands after real days


# --- P3 relocation: Now production chart is bars-only; forecast lives in Act 3 --


def _drive_future_line(frame, baseline=None, hypo=None, reductions=None):
    """Drive ``_future_line_chart`` (Act 3) with a capturing fake ``st``.
    baseline/hypo default to None -> no what-if line, just observed bars + the
    forecast band (the forecast needs only the totals frame, never OEE)."""
    pytest.importorskip("plotly")
    import plotly.graph_objects as go
    st = _CaptureST()
    app._future_line_chart(st, go, frame, baseline, hypo, reductions or {})
    return st, go


def test_production_chart_day_is_bars_only_forecast_relocated():
    """P3 (node 2): the forecast left the Now production chart for Act 3. The
    day view is now two stacked bars (good/rejected) — no trend line, no band,
    no forecast caption. (Shift was already bars-only; this pins the day view
    that previously carried the overlay.) M9 (ADR-0010 decision 10) added the
    one-line message caption every chart carries — the contract here is that
    no caption carries forecast language."""
    pytest.importorskip("plotly")
    import plotly.graph_objects as go
    frame = _production_totals()
    st = _CaptureST()
    app._production_chart(st, None, go, frame, "day")
    assert st.fig is not None
    assert len(st.fig.data) == 2
    assert all(isinstance(t, go.Bar) for t in st.fig.data)
    assert all("forecast" not in c.lower() and "trend" not in c.lower()
               and "band" not in c.lower() for c in st.captions)


def test_future_line_chart_overlays_forecast_past_last_real_day():
    st, go = _drive_future_line(_production_totals())
    fig = st.fig
    assert fig is not None
    # observed Good bar, then the 3 forecast traces (trend, upper, lower). No
    # what-if line: no baseline was passed (recovered == 0).
    assert len(fig.data) == 4
    assert isinstance(fig.data[0], go.Bar)
    trend, upper, lower = fig.data[1], fig.data[2], fig.data[3]
    bar_x = list(fig.data[0].x)                            # the real ISO days
    # the trend line extends 7 horizon days past the last real bar.
    assert len(trend.x) == len(bar_x) + app._FORECAST_HORIZON_DAYS
    assert all(h > bar_x[-1] for h in trend.x[len(bar_x):])
    # the x-axis order is pinned so the horizon lands after the real days.
    assert fig.layout.xaxis.categoryorder == "array"
    assert list(fig.layout.xaxis.categoryarray) == list(trend.x)
    # the band anchors on the last real day and widens into the horizon.
    assert list(lower.x)[0] == bar_x[-1]
    half = [upper.y[i] - lower.y[i] for i in range(len(lower.x))]
    assert half[-1] > half[0]


def test_future_line_chart_caption_is_honest_no_confident_number():
    # the sample month (<90 days) resolves to the deterministic Projection, so
    # the caption is the linear-path text (trend/band/uncertainty/projection).
    st, _ = _drive_future_line(_production_totals())
    cap = st.captions[-1]
    assert "trend" in cap.lower() and "band" in cap.lower() and "uncertainty" in cap.lower()
    # the caption frames it as a projection and explicitly disclaims certainty...
    assert "projection" in cap.lower() or "not a prediction" in cap.lower()
    # ...never a single confident future number ("will be 38,000").
    assert re.search(r"will be\s+[\d,]", cap.lower()) is None


def test_production_shift_chart_has_no_forecast():
    pytest.importorskip("plotly")
    import plotly.graph_objects as go
    frame = _production_totals()
    st = _CaptureST()
    app._production_chart(st, None, go, frame, "shift")
    assert st.fig is not None
    # only the two bars — no forecast traces, no forecast language in any
    # caption (the M9 message caption is allowed; the forecast lives in Act 3).
    assert len(st.fig.data) == 2
    assert all(isinstance(t, go.Bar) for t in st.fig.data)
    assert all("forecast" not in c.lower() and "trend" not in c.lower()
               and "band" not in c.lower() for c in st.captions)


def test_future_line_chart_too_few_days_says_not_enough():
    frame = _production_totals()
    first_days = sorted(frame.loc[frame.scope == "day", "scope_value"].unique())[:5]
    short = frame[(frame.scope == "day") & (frame["scope_value"].isin(first_days))]
    st, _ = _drive_future_line(short)
    # forecast declined -> no figure, just the honest "too little history" caption.
    assert st.fig is None
    assert any("Not enough" in c for c in st.captions)


# --- P4 (node 3): the lever waterfall's recovered-bottle bridge must close -----
# The waterfall decomposes the what-if's RECOVERED bottles per cause, so its
# floating Δs (each moved cause's recovered bottles) must sum exactly to its
# closing anchor — the total recovered. The earlier build mixed units (good-parts
# anchors + recovered-bottle Δs, ~10% apart) so the go.Waterfall running total
# overshot the anchor and snapped back; this pins the closed bridge + the
# recovered-bottles labelling so neither regresses.


def _drive_lever_waterfall(baseline, hypo, reductions):
    """Drive ``_lever_waterfall`` (Act 3) with a capturing fake ``st``."""
    pytest.importorskip("plotly")
    import plotly.graph_objects as go
    st = _CaptureST()
    app._lever_waterfall(st, go, baseline, hypo, reductions)
    return st, go


def test_lever_waterfall_bridge_closes_to_recovered():
    # Starvation fully cut on the sample month: the one moved lever.
    from linelens.oee import oee_from_context
    from linelens.whatif import whatif_from_context

    ctx = _ctx_for(_FICTIONAL_MONTH)
    baseline = oee_from_context(ctx)
    hypo = whatif_from_context(ctx, {"Starvation": 1.0})
    assert baseline is not None and hypo is not None
    st, go = _drive_lever_waterfall(baseline, hypo, {"Starvation": 1.0})

    fig = st.fig
    assert fig is not None and isinstance(fig.data[0], go.Waterfall)
    wf = fig.data[0]
    measures = list(wf.measure)
    ys = [float(v) for v in wf.y]
    rel_sum = sum(y for m, y in zip(measures, ys) if m == "relative")
    closing = [y for m, y in zip(measures, ys) if m == "absolute"][-1]  # the bridge end
    recovered = app._recovered(baseline, hypo)
    # the floating Δs sum to the closing anchor (the bridge closes — it did not
    # before: Δs summed to 52,762 recovered bottles vs a 47,395 good-parts anchor).
    assert rel_sum == pytest.approx(closing, abs=1e-6)
    # ...and that anchor is the recovered-bottle total, not good parts.
    assert closing == pytest.approx(recovered, abs=1e-6)
    # the axis labels the recovered quantity, not "good bottles" (unit consistency).
    assert "recover" in (fig.layout.yaxis.title.text or "").lower()


def test_lever_waterfall_draws_no_figure_when_no_lever_moved():
    # No slider moved -> nothing recovered to decompose, so no waterfall figure
    # (just the caption), mirroring the future-line chart's recovered>0 gate.
    from linelens.oee import oee_from_context
    from linelens.whatif import whatif_from_context

    ctx = _ctx_for(_FICTIONAL_MONTH)
    baseline = oee_from_context(ctx)
    hypo = whatif_from_context(ctx, {})  # baseline == hypo
    assert baseline is not None and hypo is not None
    st, _ = _drive_lever_waterfall(baseline, hypo, {})
    assert st.fig is None
    assert any("slider" in c.lower() for c in st.captions)


def test_zero_scatter_series_draws_no_forecast_not_a_confident_line():
    """A perfectly linear daily series has zero residual scatter, so the band
    collapses to the line. Drawing the line alone would read as a single
    confident future number (ADR-0002) — so the future-line chart declines to
    forecast: no figure, just an honest caption. (The behavior test the caption-
    template check can't catch — finding from the M7 review.)"""
    pytest.importorskip("plotly")
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(10)]
    rows = []
    for d in days:
        good = 20000.0 + 100.0 * (d - date(2026, 1, 1)).days   # exactly on a line
        rows += [("day", d, "good", good), ("day", d, "reject", 100.0)]
    frame = pd.DataFrame(rows, columns=["scope", "scope_value", "metric", "value"])
    st, _ = _drive_future_line(frame)
    # no figure (forecast declined) and an honest zero-scatter caption.
    assert st.fig is None
    cap = st.captions[-1].lower()
    assert "no observed scatter" in cap and "no forecast is drawn" in cap


# --- P5 (Act 4): reliability render wiring -----------------------------------
# _degradation_chart reuses the Act-3 forecast layer on the per-day Performance
# series (oee.performance_by_day); _mtbf_tile is a banded median from the Fault
# inter-arrival intervals, never a precise countdown (node 5). Driven via the
# same _CaptureST fake; the 6-month CSV exercises the ML path + ~200 intervals.

_FICTIONAL_6MONTH = _REPO_ROOT / "sample_data" / "fictional_6month.csv"

# Canonical 13-column header (auto-mapped by suggest_roles) for hand-built CSVs.
_CANON_COLS = ",".join([
    "machine_id", "timestamp_start", "timestamp_end", "state", "stop_cause",
    "shift", "recipe", "speed_target", "speed_actual", "duration_seconds",
    "good_count", "reject_count", "planned",
])


def _drive_degradation(csv_path):
    pytest.importorskip("plotly")
    import plotly.graph_objects as go
    st = _CaptureST()
    app._degradation_chart(st, go, _ctx_for(csv_path))
    return st, go


def test_degradation_chart_overlays_band_past_last_day_with_concern_floor():
    st, go = _drive_degradation(_FICTIONAL_6MONTH)
    fig = st.fig
    assert fig is not None
    # observed Performance bar + the 3 forecast traces (trend, upper, lower).
    assert len(fig.data) == 4
    bar, trend, upper, lower = fig.data
    assert isinstance(bar, go.Bar)
    bar_x = list(bar.x)
    # the trend line extends 7 horizon days past the last observed bar.
    assert len(trend.x) == len(bar_x) + app._FORECAST_HORIZON_DAYS
    assert all(h > bar_x[-1] for h in trend.x[len(bar_x):])
    # the band widens into the horizon.
    half = [upper.y[i] - lower.y[i] for i in range(len(lower.x))]
    assert half[-1] > half[0]
    # the concern floor is drawn as a dotted hline at _PERFORMANCE_CONCERN.
    shapes = list(fig.layout.shapes)
    assert len(shapes) == 1
    assert shapes[0].line.dash == "dot"
    assert shapes[0].line.color == app._DOWN
    assert float(shapes[0].y0) == pytest.approx(app._PERFORMANCE_CONCERN)


def test_degradation_chart_caption_is_honest_and_names_the_concern_floor():
    st, _ = _drive_degradation(_FICTIONAL_6MONTH)
    cap = st.captions[-1].lower()
    assert "band" in cap and ("projection" in cap or "not a prediction" in cap)
    assert "concern" in cap                          # the threshold read-out
    assert re.search(r"will be\s+[\d.]", cap) is None  # never a confident number


def test_degradation_chart_declines_without_a_performance_series(tmp_path):
    # No start timestamp -> no dated Performance series -> honest caption, no figure.
    csv = tmp_path / "no_perf.csv"
    csv.write_text(
        "state,speed_target,speed_actual,duration_seconds\nRunning,2200,2000,3600\n",
        encoding="utf-8",
    )
    pytest.importorskip("plotly")
    import plotly.graph_objects as go
    st = _CaptureST()
    app._degradation_chart(st, go, _ctx_for(csv))
    assert st.fig is None
    assert any("no daily performance" in c.lower() for c in st.captions)


def test_mtbf_tile_is_a_banded_median_never_a_countdown():
    from linelens import reliability
    ctx = _ctx_for(_FICTIONAL_6MONTH)
    st = _CaptureST()
    app._mtbf_tile(st, ctx)
    # exactly one metric (the median), labelled MTBF.
    assert len(st.metrics) == 1
    label, value = st.metrics[0]
    assert "MTBF" in label
    median, q1, q3 = reliability.mtbf_band(reliability.fault_intervals(ctx))
    assert value == app._fmt_span(median)
    cap_full = st.captions[-1]
    cap = cap_full.lower()
    # the IQR band edges appear in the caption, framing it as a range.
    assert app._fmt_span(q1) in cap_full and app._fmt_span(q3) in cap_full
    assert "band, not a countdown" in cap          # node 5's rejected countdown
    assert "cv" in cap and "ceiling" in cap          # the ADR-0007 honesty framing


def test_mtbf_tile_declines_with_too_few_fault_events(tmp_path):
    # Two Faults -> one interval -> mtbf_band None -> an info decline (no metric).
    csv = tmp_path / "two_faults.csv"
    csv.write_text(
        _CANON_COLS + "\n"
        "M01,2026-06-23 06:00:00,2026-06-23 06:10:00,Stopped,Fault,A,R,2200,0,600,0,0,False\n"
        "M01,2026-06-23 18:00:00,2026-06-23 18:10:00,Stopped,Fault,A,R,2200,0,600,0,0,False\n",
        encoding="utf-8",
    )
    st = _CaptureST()
    app._mtbf_tile(st, _ctx_for(csv))
    assert st.metrics == []
    assert any("too few fault" in i.lower() for i in st.infos)

