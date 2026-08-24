"""M8 learned-forecast tests -- the spike's gates ported onto forecast_ml (ADR-0007).

``forecast_ml`` trains a gradient-boosted quantile median on lag/calendar features
and wraps it in a split-conformal band that widens with the horizon. These tests
are NOT hand-computed oracles -- the model is learned, so exactness is the wrong
bar (contrast tests/test_forecast.py's closed-form OLS oracles). They encode the
spike's empirical verdict on the real 6-month dataset (``.scratch/m8/spike.py``):

* the learned median beats the deterministic linear-trend projection
  (``linelens.forecast``) on held-out future days -- the honesty gate that earned
  ML its place (trees see the weekly dip a straight line cannot);
* the conformal band covers a sane fraction of held-out actuals -- the fix for
  the raw-quantile band's measured under-coverage (spike: 69.7% at nominal 80%);
* too little history -> ``None`` (the thin-data fallback to ``forecast.forecast``);
* fixed seed -> bit-identical output (ADR-0002 determinism, retained);
* the axis shapes and the horizon-widening band (ADR-0006's honesty shape, now
  calibrated rather than assumed).

``scikit-learn`` lives behind the ``forecast`` extra; this module import-skips
without it (mirroring the ``ui``/``browser`` extras), so the default suite stays
green. The 6-month file (>=90d, weekly dip) backs the positive tests; the 30-day
month file returns ``None``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("sklearn")  # forecast_ml needs sklearn (the `forecast` extra)

from linelens import forecast, forecast_ml, ingestion, schema, summaries, validation

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FICTIONAL_6MONTH = _REPO_ROOT / "sample_data" / "fictional_6month.csv"
_FICTIONAL_MONTH = _REPO_ROOT / "sample_data" / "fictional_month.csv"

_HORIZON = 7
_HOLDOUT = 14


def _daily_good_series_for(csv_path: Path):
    """Daily good-bottle series through the real ingestion->schema->validation->
    summaries->production_totals (scope=day, metric=good) pipeline -- the same
    series the app forecasts. Mirrors tests/test_forecast.py's helper. Sorted by
    date so the trailing slice is the genuine chronological hold-out."""
    raw, profile = ingestion.load_csv(csv_path)
    sug = schema.suggest_roles(profile.columns)
    role_to_col = {role: col for col, (role, _conf) in sug.items()}
    ctx = validation.make_context(raw, profile, schema.build_mapping(role_to_col))
    rep = summaries.summarize(ctx)
    d = rep.production_totals
    d = d[(d.scope == "day") & (d.metric == "good")].sort_values("scope_value")
    return list(d["scope_value"]), list(d["value"].astype(float))


def _mae(pred, actual) -> float:
    return sum(abs(p - a) for p, a in zip(pred, actual, strict=False)) / len(actual)


# --- Gate 1: the learned median beats the deterministic line on held-out future --
# The honest MULTI-STEP test (not the spike's one-step-with-known-lags eval): hold
# out the last 14 real days, fit each model on the prefix, predict all 14
# recursively / by extrapolation, and compare MAE vs actual.


def test_ml_beats_deterministic_baseline_on_held_out_future():
    days, y = _daily_good_series_for(_FICTIONAL_6MONTH)
    train_days, train_y = days[:-_HOLDOUT], y[:-_HOLDOUT]
    actual = y[-_HOLDOUT:]

    ml = forecast_ml.forecast_ml(train_days, train_y, horizon=_HOLDOUT, min_points=90)
    assert ml is not None
    ml_pred = ml.median[len(train_y):]               # recursive horizon predictions
    det = forecast.forecast(train_days, train_y, horizon=_HOLDOUT, min_points=7)
    assert det is not None
    det_pred = det.line[len(train_y):]               # linear-trend extrapolation

    # The spike's verdict on this dataset: trees capture the planted weekly dip a
    # straight line cannot, so the learned median's held-out MAE is lower.
    assert _mae(ml_pred, actual) < _mae(det_pred, actual)


# --- Gate 2: the conformal band covers a sane fraction of held-out actuals -------


def test_conformal_band_covers_held_out_actuals():
    days, y = _daily_good_series_for(_FICTIONAL_6MONTH)
    train_days, train_y = days[:-_HOLDOUT], y[:-_HOLDOUT]
    actual = y[-_HOLDOUT:]

    ml = forecast_ml.forecast_ml(
        train_days, train_y, horizon=_HOLDOUT, min_points=90, coverage=0.8)
    # band index 0 is the anchor (last observed day); index k is horizon day k.
    covered = sum(1 for k in range(1, _HOLDOUT + 1)
                  if ml.lower[k] <= actual[k - 1] <= ml.upper[k])
    coverage = covered / _HOLDOUT
    # One-sided on purpose. The conformal fix exists to stop the raw-quantile band
    # UNDER-covering (the spike measured 69.7% at a nominal 80%); over-covering on
    # a small held-out window is benign (the band widens with sqrt(step)), so the
    # gate only asserts the band is not systematically too narrow.
    assert coverage >= 0.70


# --- Gate 3: too few points -> None (thin-data fallback to forecast.forecast) ----


def test_too_few_daily_points_returns_none():
    days, y = _daily_good_series_for(_FICTIONAL_MONTH)
    assert len(y) < 90                                 # a single month is thin data
    assert forecast_ml.forecast_ml(days, y, horizon=_HORIZON, min_points=90) is None


# --- Gate 4: fixed seed -> identical output (ADR-0002 determinism, retained) -----


def test_forecast_ml_is_deterministic():
    days, y = _daily_good_series_for(_FICTIONAL_6MONTH)
    a = forecast_ml.forecast_ml(days, y, horizon=_HORIZON, min_points=90)
    b = forecast_ml.forecast_ml(days, y, horizon=_HORIZON, min_points=90)
    assert a == b


# --- Gate 5: axis shapes + the band widens into the horizon ---------------------


def test_shapes_and_widening_band():
    days, y = _daily_good_series_for(_FICTIONAL_6MONTH)
    n = len(y)
    ml = forecast_ml.forecast_ml(days, y, horizon=_HORIZON, min_points=90)
    assert ml is not None
    # One continuous median line (observed + horizon); band anchored at last day.
    assert len(ml.median) == n + _HORIZON
    assert len(ml.line_dates) == n + _HORIZON
    assert len(ml.band_dates) == _HORIZON + 1
    assert len(ml.lower) == _HORIZON + 1
    assert len(ml.upper) == _HORIZON + 1
    # The band widens with the horizon (sqrt step) -- never claims flat precision.
    half = [(ml.upper[i] - ml.lower[i]) / 2 for i in range(len(ml.band_dates))]
    assert half == sorted(half)
    assert half[-1] > half[0]
