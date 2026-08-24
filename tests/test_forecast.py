"""M7 banded-trend-forecast tests — hand-computed oracles (ADR-0006).

The forecast (``linelens.forecast``) fits a degree-1 least-squares line to a
dated daily series and extrapolates it inside a widening ±1σ prediction band.
ADR-0006 pins the fit (OLS via normal equations), the band
(``half = s · √(1 + 1/n + (x*−x̄)²/S_xx)``), the horizon (7), and the minimum
data (7). These tests are the hand-computed oracle for that arithmetic — every
expected value is derived independently of ``forecast``'s implementation: a
perfectly linear series has an exact fit and a zero band; a centered noisy
series has hand-chosen residuals so slope, residual std, and the widening band
are all closed-form.

The suite stays free of the ``ui`` extra (pyproject): ``forecast`` is a pure
function of a dated series, like ``compute_oee`` / ``whatif.perturb``.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path

import pytest

from linelens import forecast, ingestion, schema, summaries, validation

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FICTIONAL_MONTH = _REPO_ROOT / "sample_data" / "fictional_month.csv"

_HORIZON = 7
_MIN = 7


def _day(n: int) -> date:
    return date(2026, 1, 1) + timedelta(days=n)


# --- Oracle 1: a perfectly linear series -> exact fit, zero band, r² = 1 -----


def test_perfectly_linear_series_is_fit_exactly_with_zero_band():
    days = [_day(i) for i in range(10)]
    y = [2000 + 100 * i for i in range(10)]  # exactly +100/day
    fc = forecast.forecast(days, y, horizon=_HORIZON, min_points=_MIN)
    assert fc is not None

    assert fc.slope == pytest.approx(100.0)            # 100 bottles/calendar-day
    assert fc.residual_std == pytest.approx(0.0, abs=1e-12)
    assert fc.r_squared == pytest.approx(1.0)
    # The trend line reproduces the data over observed days...
    assert list(fc.line[:10]) == pytest.approx(y)
    # ...and continues the line into the horizon (3000..3600 over days 10..16).
    assert list(fc.line[10:]) == pytest.approx([2000 + 100 * i for i in range(10, 17)])
    # Zero scatter -> the band collapses onto the line (honest: nothing to be
    # uncertain about). lower == upper == central at every horizon point.
    band_central = fc.line[9:]  # last observed day + 7 horizon days
    assert fc.lower == pytest.approx(band_central)
    assert fc.upper == pytest.approx(band_central)


# --- Oracle 2: a centered noisy series -> slope, residual std, widening band --
# 5 consecutive days, deviations from the mean day are [-2,-1,0,1,2]. Adding
# residuals e = [1,-1,-1,1,0] with Σe = 0 and Σ(dev·e) = 0 makes OLS recover the
# line exactly, so the fit residuals ARE e: slope = 5, s = √(Σe²/(n−2)) = √(4/3),
# and the band half-width s·√(1 + 1/n + (x*−x̄)²/S_xx) widens with the horizon.


def test_centered_noisy_series_recovers_slope_residual_std_and_widening_band():
    dev = [-2, -1, 0, 1, 2]
    e = [1, -1, -1, 1, 0]  # Σe = 0, Σ(dev·e) = 0 -> residuals stay e under OLS
    days = [_day(i) for i in range(5)]
    y = [100 + 5 * dev[i] + e[i] for i in range(5)]
    fc = forecast.forecast(days, y, horizon=_HORIZON, min_points=3)
    assert fc is not None

    assert fc.slope == pytest.approx(5.0)
    assert fc.residual_std == pytest.approx(math.sqrt(4 / 3))
    # The trend line over observed days is 100 + 5·dev (the line through the
    # center); data minus line == the chosen residuals e.
    assert list(fc.line[:5]) == pytest.approx([90, 95, 100, 105, 110])
    assert [y[i] - fc.line[i] for i in range(5)] == pytest.approx(e)

    # The band brackets the central line symmetrically at every horizon point...
    band_central = fc.line[4:]  # anchor (last observed) + 7 horizon days
    for i in range(len(fc.band_dates)):
        assert fc.lower[i] < band_central[i] < fc.upper[i]
        assert (fc.upper[i] + fc.lower[i]) / 2 == pytest.approx(band_central[i])
    half = [(fc.upper[i] - fc.lower[i]) / 2 for i in range(len(fc.band_dates))]
    # ...and the half-width is pinned to its closed-form ±1σ prediction interval,
    # not just its shape: half = s·√(1 + 1/n + (x*−x̄)²/S_xx) with s = √(4/3),
    # n = 5, S_xx = 10. The anchor (deviation 2) and day+7 (deviation 9) are
    # hand-computed, so a formula regression (e.g. dropping the leading 1, which
    # would make it a confidence interval for the mean) fails here.
    s = math.sqrt(4 / 3)
    assert half[0] == pytest.approx(s * math.sqrt(1 + 1 / 5 + 4 / 10))     # dev 2
    assert half[-1] == pytest.approx(s * math.sqrt(1 + 1 / 5 + 81 / 10))   # dev 9
    # ...and widens monotonically into the horizon (uncertainty rises the
    # further ahead) — the honesty shape ADR-0006 requires, not a flat band.
    assert half == sorted(half)
    assert half[-1] > half[0]


# --- Oracle 3: too few points -> None; the threshold itself fits ------------


def test_too_few_daily_points_returns_none():
    days = [_day(i) for i in range(_MIN - 1)]
    y = list(range(_MIN - 1))
    assert forecast.forecast(days, y, horizon=_HORIZON, min_points=_MIN) is None


def test_minimum_points_fits():
    days = [_day(i) for i in range(_MIN)]
    y = [1000.0] * _MIN
    fc = forecast.forecast(days, y, horizon=_HORIZON, min_points=_MIN)
    assert fc is not None
    assert fc.slope == pytest.approx(0.0)        # flat series -> no trend
    assert fc.r_squared == pytest.approx(0.0)    # no variance to explain (guard)


# --- Oracle 4: horizon dates are last-day + 1..7; axes sized accordingly ----


def test_horizon_dates_and_axis_shapes():
    n = 9
    days = [_day(i) for i in range(n)]
    y = [float(i) for i in range(n)]
    fc = forecast.forecast(days, y, horizon=_HORIZON, min_points=_MIN)
    assert fc is not None
    # line covers observed + horizon; band is anchored at the last observed day.
    assert len(fc.line_dates) == n + _HORIZON
    assert len(fc.line) == n + _HORIZON
    assert len(fc.band_dates) == _HORIZON + 1
    # horizon is exactly last day + 1..7 calendar days (ordinal, so gaps honored).
    assert list(fc.line_dates[-_HORIZON:]) == [days[-1] + timedelta(days=k)
                                               for k in range(1, _HORIZON + 1)]
    assert fc.band_dates[0] == days[-1]            # anchored on the last real day
    assert list(fc.band_dates[1:]) == list(fc.line_dates[-_HORIZON:])


# --- Oracle 5: deterministic — same inputs yield identical output ------------


def test_forecast_is_deterministic():
    days = [_day(i) for i in range(8)]
    y = [10.0 + 2.0 * i + (1 if i % 2 else -1) for i in range(8)]
    a = forecast.forecast(days, y, horizon=_HORIZON, min_points=_MIN)
    b = forecast.forecast(days, y, horizon=_HORIZON, min_points=_MIN)
    assert a == b


# --- Oracle 6: the real dataset -> a real downward drift, a widening band ----


def _daily_good_series_for(csv_path: Path):
    raw, profile = ingestion.load_csv(csv_path)
    sug = schema.suggest_roles(profile.columns)
    role_to_col = {role: col for col, (role, _conf) in sug.items()}
    ctx = validation.make_context(raw, profile, schema.build_mapping(role_to_col))
    rep = summaries.summarize(ctx)
    d = rep.production_totals
    d = d[(d.scope == "day") & (d.metric == "good")].sort_values("scope_value")
    return list(d["scope_value"]), list(d["value"].astype(float))


def test_fictional_month_forecasts_a_downward_widening_band():
    days, y = _daily_good_series_for(_FICTIONAL_MONTH)
    assert len(days) >= _MIN                         # a full month -> plenty of history
    fc = forecast.forecast(days, y, horizon=_HORIZON, min_points=_MIN)
    assert fc is not None
    # The generator built a gentle downward drift into the month -> negative slope.
    assert fc.slope < 0
    # Real daily scatter -> a meaningful but imperfect fit, and nonzero band.
    assert 0.3 < fc.r_squared < 1.0
    assert fc.residual_std > 1000.0
    # The band widens into the horizon (the honesty shape), never collapses.
    half = [(fc.upper[i] - fc.lower[i]) / 2 for i in range(len(fc.band_dates))]
    assert half[-1] > half[0]
