# Banded trend forecast: linear least-squares + a widening ±1σ prediction band

## Status

Accepted (2026-07-23, M7). Implements plan row 7 ("Banded forecast on the
production graph") and the **banded-trend half** of ADR-0002 (the what-if was
ADR-0005 / M6). Supersedes nothing. ADR-0002 (deterministic prediction, no ML)
stands. This one fills in the forecast half, the last of the eight locked
decisions.

## Context

M7 extrapolates the period's daily production ~7 days ahead and draws it as a
line wrapped in an uncertainty band. "where is this heading," never a single
confident future number. Five questions had to be decided *before* code,
because the dataset, the chart, and the test oracle all depend on the answers:

1. **What gets forecast?** Daily good-bottle production, daily OEE, or both?
2. **The fit.** What deterministic model? (Learned models are out. ADR-0002.)
3. **The band.** A constant ±1σ, or one that widens with the horizon? The
   shape is the honesty mechanism, so this is not cosmetic.
4. **Horizon + minimum data.** How far ahead, and how little history is too
   little to fit at all?
5. **Where does it plug in?** A new chart, or overlaid on the existing
   production graph (the plan says "on the production graph")?

The model also had to stay **deterministic** (ADR-0002): no randomness, no
sampling, no learned weights. Pure arithmetic. Uncertainty appears only here,
as a band computed from fit residuals.

## Decision

### 1. Forecast daily good-bottle production

Daily **good** parts, taken straight from `summaries`'
`production_totals[scope == "day" & metric == "good"]`. One dated point per
day (~30 for the sample month). It is ADR-0002's literal example ("daily
production"), requires no extra computation, and pairs naturally with the
existing per-day production bars. Per-day **OEE** is the natural extension (it
would need slicing rows by day and re-running `compute_oee`). Named here, not
built. Production first, OEE when a real ask arrives.

### 2. Fit: ordinary least-squares line, degree 1

`y = intercept + slope · day`, where `day` is the calendar date's proleptic
Gregorian ordinal. Using the ordinal (not a 0..n observation index) means the
slope is "good bottles per **calendar** day" and date gaps are honored rather
than assumed contiguous. Solved by the 2×2 normal equations
(`slope = Σ(x−x̄)(y−ȳ) / Σ(x−x̄)²`, `intercept = ȳ − slope·x̄`). Pandas Series
arithmetic plus `math.sqrt`, **no numpy**, matching the pandas-only dependency
surface of `oee.py` / `whatif.py`.

We reject ARIMA / any learned model (ADR-0002), and degree > 1 polynomials
(they would overfit ~30 points and imply false confidence in curvature the data
does not assert). Linear is the honest first-order model, and the generator
built a gentle drift into the sample month (measured: slope ≈ −211 good
bottles/day, r² ≈ 0.55) so a line is the right summary of where production is
heading.

### 3. Band: a widening ±1σ prediction interval, not a constant ±1σ

At a future day `x*`, the band's half-width is

```
half(x*) = s · √( 1 + 1/n + (x* − x̄)² / S_xx )
```

where `s = √(Σ residuals² / (n − 2))` is the regression standard error, `n` the
number of days fit, `x̄` their mean ordinal, and `S_xx = Σ(xᵢ − x̄)²`. This is
the textbook **prediction interval for a new daily observation**: the leading
`1` is that day's own scatter, and `1/n + (x* − x̄)²/S_xx` is the uncertainty in
the fitted mean, which grows as `x*` leaves the data's center. So the band is
narrowest over the observed days and **widens into the horizon.** Uncertainty
rises the further ahead you look, which is the honest shape.

We reject a **constant** ±1σ (`half = s` everywhere): it understates far-out
uncertainty and would show a band just as tight on day +7 as on the last real
day, implying more confidence than the data supports. The widening *is* the
point of the band.

This is a ±1σ (≈68%) band, not 95% (±2σ). The plan says "±1σ" and we hold to
that. The widening, not the coverage level, is what keeps it honest.

### 4. Horizon 7 days. Minimum 7 real days

Extrapolate exactly **7** calendar days past the last observed day. Require
**≥ 7** observed daily points to fit at all. With fewer, the chart shows "Not
enough daily history to project a trend (need ≥ 7 days)" and draws nothing.
Never a line off two points. 7 matches the plan's "~7 days" and gives the fit
real degrees of freedom (`n − 2 = 5` at the threshold).

### 5. Plug-in: overlay on the production chart's day view

Extend `app._production_chart`'s **day** branch (the stacked good/rejected
bars), not a new section. Over the same date axis: a dashed trend line (observed
days + horizon, one continuous line) and a translucent ±1σ ribbon over the
future, anchored at the last observed day and widening. The overall (pie) and
shift views get no forecast. A trend is a time-axis view by definition.
Guarded on `group_by == "day"` and on the minimum-points rule.

## Consequences

- **Deterministic and pure.** `forecast.forecast(dates, values, horizon=7,
  min_points=7) -> ForecastResult | None` is a pure function of a dated series.
  No context, no randomness, no learned weights. It lives in `linelens/` so it
  is unit-testable without the `ui` extra, exactly like `compute_oee` and
  `whatif.perturb`. The band is computed from residuals, never sampled.
- **Never a single confident number.** The central line is labeled a *trend*.
  The ribbon, not the line, is the forecast. The caption frames it as a
  projection of the recent trend with growing uncertainty, never "production
  will be X." A future day's value may appear only as a range inside the band
  (on hover), never as a bare point presented as the prediction.
- **Zero-scatter data → no forecast, not a zero band.** When the daily series
  lies on a line, `s ≈ 0` and the prediction interval collapses to zero width.
  Rather than draw a bandless trend line into the future, which would read as a
  single confident number and is exactly what ADR-0002 forbids, the UI **declines to
  forecast**: it states "the series fits a line with no observed scatter, so a
  statistical band can't bound the projection," and draws no line. The math
  (`forecast`) still returns the zero-band result (it is correct). It is the
  *display policy* that refuses to overclaim. (An earlier draft of this ADR read
  a zero band as "honestly, no scatter to be uncertain about". The review of M7
  reversed that. A collapsed band means there is no band, so a lone line is a
  confident prediction.) A noisy month (sample: r² ≈ 0.55, s ≈ 1,650 bottles)
  widens visibly into the horizon.
- **Known ceilings.** A linear trend assumes the recent direction persists. A
  regime change the past does not contain (a new recipe, maintenance, a demand
  shift) will land outside the band. A modeling ceiling, not a code defect, and
  exactly why the band widens instead of claiming certainty. A steep decline can
  also drive the line and band below zero, physically impossible for "good
  bottles". The model does **not** clip at zero, because a line crossing zero is
  itself the honest "this trend is unsustainable" signal (clipping would hide
  it). Residual scatter also cannot be estimated from fewer than 3 points, so
  `forecast` refuses to fit on `n < max(min_points, 3)` rather than fabricate a
  zero-width band off two points.
- **No per-recipe / per-shift forecast, no probabilistic model, no scenario
  controls.** One daily-good trend + band, on the production chart. Per-day OEE
  is the named extension. Add when a real ask arrives.
