"""Learned forecast (M8): gradient-boosted median + a conformal-calibrated band.

The successor to ``forecast.py``'s deterministic least-squares projection
(ADR-0007): where that file extrapolates a straight line with a model-assumed
+/-1sd ribbon, this file trains a gradient-boosting quantile model on the dated
daily series and calibrates a band whose coverage is *measured* on held-out data
(split conformal), not assumed Gaussian.

Pure: a function of a dated daily series -- no context, no UI, no randomness
beyond a fixed seed. ``scikit-learn`` lives behind the ``forecast`` extra; this
module raises ImportError without it, and the test suite import-skips (mirroring
the ``ui``/``browser`` extras). Returns ``None`` when there is too little history
(``len(dates) < min_points``) -- the app then falls back to the deterministic
``forecast.forecast`` (ADR-0007's thin-data path).

Multi-step honesty. Horizon days are predicted **recursively** (each future day's
``lag1`` is the prior day's prediction; ``lag7`` stays the actual same-weekday
value, which is always in reach for a 7-day horizon). The conformal one-step
half-width is then **widened by sqrt(step)** into the future, so the band honestly
grows with the horizon instead of claiming one-step precision seven days out --
the same "the band, not the line, is the forecast" discipline as ADR-0006, now
calibrated rather than assumed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd  # noqa: F401  (kept for parity with forecast.py's series dtype handling)

from sklearn.ensemble import GradientBoostingRegressor

# Fixed seed -> same inputs give identical output (ADR-0002's determinism clause,
# retained by ADR-0007 for the learned model: no run-to-run randomness).
_SEED = 20260623

# lag7 needs 7 days of history before the first usable row; leave room to split
# a train_proper / calibration set. Below min_points (~3 months) the app uses the
# deterministic projection instead of inventing a learned model on too little data.
_MIN_LAG = 7
_DEFAULT_MIN_POINTS = 90
_DEFAULT_HORIZON = 7
_DEFAULT_COVERAGE = 0.8
_CAL_FRACTION = 0.20  # last 20% of training rows hold out for conformal calibration


@dataclass(frozen=True)
class MLForecastResult:
    """A learned, conformal-banded forecast of a dated daily series.

    ``line_dates`` / ``median`` carry the central estimate over the observed days
    (the model's in-fit) continued into the horizon (recursive prediction) -- one
    continuous line. ``band_dates`` / ``lower`` / ``upper`` carry the conformal
    band over the *future* only, anchored at the last observed day and widening
    with the horizon. ``slope`` / ``r_squared`` are the OLS diagnostics of the
    series (the visible trend baseline); ``cal_half`` is the one-step conformal
    half-width before sqrt(step) widening. The band is the forecast; the median is
    a central tendency, never a confident future point (ADR-0007).
    """

    slope: float                       # OLS bottles/day -- the trend baseline diagnostic
    r_squared: float                   # 0..1 fraction of variance the OLS line explains
    cal_half: float                    # conformal one-step half-width q, pre-widening
    coverage: float                    # target coverage the band is calibrated to
    line_dates: tuple[date, ...]       # observed days then horizon days
    median: tuple[float, ...]          # GBR median: in-fit on observed, recursive on horizon
    band_dates: tuple[date, ...]       # last observed day then horizon days
    lower: tuple[float, ...]           # lower conformal edge, widening with sqrt(step)
    upper: tuple[float, ...]           # upper conformal edge, widening with sqrt(step)


def _feature_row(day_idx: int, hist: list[float], d: date) -> list[float]:
    """One supervised feature row for ``day_idx``, reading lags from ``hist``
    (the running series: actuals, then appended predictions for future days).

    lag1/2/7 and roll7 come from ``hist``; ``dow`` from the date; ``t`` is the day
    index (a gentle trend counter the trees can split on). For horizon days the
    recursive caller appends each prediction to ``hist`` before the next step, so
    lag1 becomes the prior prediction -- the standard recursive multi-step scheme.
    """
    return [
        hist[-1],                # lag1
        hist[-2],                # lag2
        hist[-7],                # lag7 (same weekday last week -- always actual within 7d)
        float(np.mean(hist[-7:])),  # roll7: trailing 7-day level
        float(d.weekday()),      # dow
        float(day_idx),          # t
    ]


def forecast_ml(
    dates,
    values,
    horizon: int = _DEFAULT_HORIZON,
    min_points: int = _DEFAULT_MIN_POINTS,
    coverage: float = _DEFAULT_COVERAGE,
) -> MLForecastResult | None:
    """Fit a gradient-boosted median to a dated daily series and forecast the
    next ``horizon`` days inside a conformal-calibrated, horizon-widening band.

    Fits ``GradientBoostingRegressor(loss='quantile', alpha=0.5)`` on
    lag/calendar features, time-aware split (train_proper then a trailing
    calibration slice -- never shuffled, no lookahead), and calibrates a split-
    conformal half-width ``q`` at the requested ``coverage``. Horizon days are
    predicted recursively; the band is ``q * sqrt(step)`` so it widens honestly.

    Returns ``None`` when ``len(dates) < min_points`` (too little history to
    learn -- fall back to the deterministic projection). Deterministic: fixed
    seed, same inputs -> identical output. See ADR-0007 for the decision.
    """
    obs = list(dates)
    y = [float(v) for v in values]
    n = len(obs)
    # need lag7 history, room to split train/cal, and the min-points threshold.
    if n != len(y) or n < max(min_points, _MIN_LAG + 1):
        return None

    # --- training matrix: one row per day t >= 7, features from actual history ---
    feats, target = [], []
    for t in range(_MIN_LAG, n):
        feats.append(_feature_row(t, y[:t], obs[t]))
        target.append(y[t])
    X = np.asarray(feats, dtype=float)
    yt = np.asarray(target, dtype=float)

    # --- time-aware split: trailing slice is the conformal calibration set ---
    n_cal = max(10, int(_CAL_FRACTION * len(X)))
    X_train, y_train = X[:-n_cal], yt[:-n_cal]
    X_cal, y_cal = X[-n_cal:], yt[-n_cal:]
    median_model = GradientBoostingRegressor(
        loss="quantile", alpha=0.5, n_estimators=200, max_depth=2,
        random_state=_SEED).fit(X_train, y_train)

    # --- split-conformal one-step half-width at the requested coverage ---
    cal_abs = np.sort(np.abs(y_cal - median_model.predict(X_cal)))
    rank = int(np.ceil(coverage * (len(cal_abs) + 1)))
    rank = min(max(rank, 1), len(cal_abs))
    cal_half = float(cal_abs[rank - 1])

    # --- recursive horizon prediction (lag1 = prior prediction; lag7 = actual) ---
    hist = list(y)  # running history: actuals, then appended predictions
    horizon_dates = [obs[-1] + timedelta(days=k) for k in range(1, horizon + 1)]
    horizon_pred: list[float] = []
    for k in range(1, horizon + 1):
        day_idx = (n - 1) + k
        pred = float(median_model.predict([_feature_row(day_idx, hist, horizon_dates[k - 1])])[0])
        horizon_pred.append(pred)
        hist.append(pred)

    # --- central line: actuals for the pre-feature days, in-fit on observed, horizon preds ---
    fit_observed = [float(v) for v in median_model.predict(X)]  # in-fit for days 7..n-1
    median = tuple(y[:_MIN_LAG]) + tuple(fit_observed) + tuple(horizon_pred)
    line_dates = tuple(obs) + tuple(horizon_dates)

    # --- band: last observed + horizon, central = median there, widening sqrt(step) ---
    band_dates = (obs[-1],) + tuple(horizon_dates)
    band_central = [median[len(median) - 1 - horizon]] + horizon_pred  # last observed + horizon
    widths = [cal_half * math.sqrt(1)] + [cal_half * math.sqrt(k) for k in range(1, horizon + 1)]
    lower = tuple(c - w for c, w in zip(band_central, widths))
    upper = tuple(c + w for c, w in zip(band_central, widths))

    # --- OLS diagnostics for the visible trend baseline (the thing ML is measured against) ---
    x = np.arange(n, dtype=float)
    xm, ym = x.mean(), np.mean(y)
    sxx = float(((x - xm) ** 2).sum())
    slope = float(((x - xm) * (np.asarray(y) - ym)).sum() / sxx) if sxx else 0.0
    fitted = slope * x + (ym - slope * xm)
    ss_res = float(((np.asarray(y) - fitted) ** 2).sum())
    ss_tot = float(((np.asarray(y) - ym) ** 2).sum())
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    return MLForecastResult(
        slope=slope, r_squared=r_squared, cal_half=cal_half, coverage=coverage,
        line_dates=line_dates, median=median,
        band_dates=band_dates, lower=lower, upper=upper,
    )
