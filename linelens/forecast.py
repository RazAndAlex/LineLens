"""Banded trend forecast (M7): deterministic least-squares extrapolation.

The forecast half of ADR-0002 (the what-if was M6). It takes a dated daily
series, fits an ordinary least-squares line, and extrapolates it a fixed number
of days ahead inside a widening ±1σ prediction band -- "where is this heading,"
never a single confident future number. Pure arithmetic: no ML, no randomness,
no sampling. The band is computed from the fit residuals.

One entry point:

* ``forecast(dates, values, horizon, min_points)`` -- the **pure** forecast
  core: a function of a dated series. Returns a ``ForecastResult`` (central
  trend line + lower/upper band + caption diagnostics), or ``None`` when there
  is too little history to fit (``len(dates) < min_points``). No context, no
  UI -- unit-testable without the ``ui`` extra, like ``compute_oee``.

The fit and the widening band are pinned in ``docs/adr/0006-*.md``; read that
for the reasoning (linear degree-1, widening prediction interval, horizon 7,
min 7 days).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd


@dataclass(frozen=True)
class ForecastResult:
    """A deterministic trend forecast of a dated daily series.

    ``line_dates`` / ``line`` carry the central trend line over the observed
    days continued into the horizon (one continuous line). ``band_dates`` /
    ``lower`` / ``upper`` carry the ±1σ prediction band over the *future* only,
    anchored at the last observed day (``band_dates[0]`` is that day) and
    widening with the horizon. ``slope`` / ``residual_std`` / ``r_squared`` are
    the caption diagnostics (trend direction, scatter size, fit quality). The
    band is the forecast; the line is a trend, never a single confident number
    (ADR-0002 / 0006).
    """

    slope: float                     # series units per calendar day (e.g. good bottles/day)
    residual_std: float              # regression standard error s — the band's scale
    r_squared: float                 # 0..1 fraction of variance the line explains
    line_dates: tuple[date, ...]     # observed days then horizon days
    line: tuple[float, ...]          # central trend over ``line_dates``
    band_dates: tuple[date, ...]     # last observed day then horizon days
    lower: tuple[float, ...]         # lower ±1σ edge over ``band_dates``
    upper: tuple[float, ...]         # upper ±1σ edge over ``band_dates``


def forecast(
    dates,
    values,
    horizon: int = 7,
    min_points: int = 7,
) -> ForecastResult | None:
    """Fit a least-squares trend to a dated daily series and extrapolate it.

    Fits ``y = intercept + slope · day_ordinal`` (degree-1 OLS via the 2×2
    normal equations), then projects ``horizon`` calendar days past the last
    observed day. The ±1σ band is a widening prediction interval
    (``half = s · √(1 + 1/n + (x*−x̄)²/S_xx)``), anchored at the last observed
    day and widening into the horizon (ADR-0006).

    Returns ``None`` when ``len(dates) < min_points`` (too little history to
    support a trend). Pure and deterministic: same inputs → identical output, no
    randomness. ``dates`` are ``datetime.date`` (or datetimes, which subclass
    it); ``values`` numeric. See ADR-0006 for the fit/band decisions.
    """
    obs = list(dates)
    y = pd.Series(values, dtype="float64")
    n = int(len(obs))
    # Residual scatter needs >= 3 points (>= 1 residual degree of freedom); a
    # 2-point fit is exact and would claim zero scatter — not an honest band.
    # Floor the minimum at 3 so the dof below is always >= 1.
    if n != len(y) or n < max(min_points, 3):
        return None

    x = pd.Series([d.toordinal() for d in obs], dtype="float64")
    xm = float(x.mean())
    ym = float(y.mean())
    dev_x = x - xm
    sxx = float((dev_x ** 2).sum())
    if sxx == 0.0:
        # All days identical -> no time axis, no slope. Unreachable for real
        # daily data (distinct dates); guard so a degenerate input returns no
        # trend rather than dividing by zero.
        return None
    slope = float((dev_x * (y - ym)).sum() / sxx)
    intercept = ym - slope * xm
    fitted = slope * x + intercept
    resid = y - fitted
    ss_res = float((resid ** 2).sum())
    ss_tot = float(((y - ym) ** 2).sum())
    # n >= 3 is guaranteed by the max(min_points, 3) floor above, so dof >= 1
    # and the regression standard error never divides by zero.
    dof = n - 2
    residual_std = math.sqrt(ss_res / dof)
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    last_ord = float(x.iloc[-1])
    last_date = obs[-1]
    horizon_ord = pd.Series(
        [last_ord + k for k in range(1, horizon + 1)], dtype="float64"
    )
    horizon_dates = [last_date + timedelta(days=k) for k in range(1, horizon + 1)]

    # Central trend line over observed days + horizon (one continuous line).
    line_x = pd.concat([x, horizon_ord], ignore_index=True)
    line = tuple(float(v) for v in (slope * line_x + intercept))

    # ±1σ prediction band, anchored at the last observed day then widening over
    # the horizon. half = s · √(1 + 1/n + (x*−x̄)²/S_xx) (ADR-0006).
    band_x = pd.concat([pd.Series([last_ord]), horizon_ord], ignore_index=True)
    half = residual_std * (1.0 + 1.0 / n + (band_x - xm) ** 2 / sxx).pow(0.5)
    band_central = slope * band_x + intercept
    lower = tuple(float(v) for v in (band_central - half))
    upper = tuple(float(v) for v in (band_central + half))

    return ForecastResult(
        slope=slope,
        residual_std=residual_std,
        r_squared=r_squared,
        line_dates=tuple(obs) + tuple(horizon_dates),
        line=line,
        band_dates=(last_date,) + tuple(horizon_dates),
        lower=lower,
        upper=upper,
    )
