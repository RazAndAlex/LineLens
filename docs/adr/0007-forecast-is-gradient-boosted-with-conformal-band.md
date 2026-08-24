# Forecast is a gradient-boosted model with a conformal band (succeeding the deterministic trend)

## Status

Accepted (2026-07-23, M8). Reverses ADR-0002's "no ML" stance and supersedes
the degree-1-OLS technique pinned in ADR-0006. **Retained** from both: the
always-band, never-a-confident-future-number ethic. Now *enforced and measured*
through conformal calibration rather than a model-assumed ±1σ ribbon.
ADR-0005 (the what-if's deterministic freed-time arithmetic) is untouched.

This is the outcome of the M8 de-risking spike (`.scratch/m8/spike.py`, run on
the generated 180-day `fictional_6month.csv`). The numbers below are that run.

## Context

The user wanted a "predictive model": a *future line* on the production chart
and, later, a maintenance/breakage signal. Grilling surfaced that "prediction"
collided with two prior decisions. ADR-0002's rejection of ML, and the
glossary's ban on the word. Resolving that split the question into two
independent axes the spike was built to settle:

1. **Technique.** Is the linear least-squares trend (ADR-0006) the right
   forecaster, or does a feature-based ML model earn its place? On *clean
   synthetic* weekly data the spike found the opposite of what we expected. A
   plain linear regression on features beat gradient boosting. That made
   "use ML" an open question only real-noise data could close.
2. **Band honesty.** ADR-0002/0006's defining rule is "the band, never a
   confident point." Quantile gradient boosting emits a band natively. But is
   that band *calibrated* on real residuals, or just shaped like one?

Three constraints going in: (a) the ML ≠ LLM distinction. The removed "AI
section" was an LLM presenter, irrelevant to statistical forecasting, so ML was
never forbidden on identity grounds, only on ADR-0002's overclaiming/scope
grounds. (b) the always-band rule stays a hard constraint regardless of
technique. (c) the data is one generated CSV, so the generator had to grow a
weekly rhythm and a longer horizon before any of this was testable.

## Decision

### 1. The point forecast is gradient-boosted trees on lag + calendar features

Daily good-bottle production (the same dated series ADR-0006 projected) is
forecast by a `GradientBoostingRegressor` (quantile loss, median) over features
`[lag1, lag2, lag7, roll7, day-of-week, trend-counter]`. On real 6-month data
it is the best point forecast:

```
model                                   MAE     MAPE
linear trend (ADR-0006 math)          2,965    7.39%   <- current, worst
persistence (7d)                      1,793    4.47%
linear on features                    2,020    5.04%
gradient boosting                     1,670    4.16%   <- chosen
```

GBR cuts the current model's error **44%** and beats both the clever baseline
(weekly persistence) and linear-on-features. We explicitly do **not** pretend
the synthetic run didn't happen: on clean planted data linear *won* (892 vs
982). The decision rests on the real-data result. The flexible model wins once
the weekly signal is muddied by genuine interval-sampling noise, which is the
regime the app actually ships in. Deep learning is rejected: 180 days is far
too little, and it would overfit.

### 2. The band is conformal-calibrated, never raw quantile

Raw quantile bands **under-cover** on real (fat-tailed) residuals. The spike
measured it:

```
band                          coverage   target
linear trend ±1σ (current)      54.5%    ~68%   <- overconfident (a latent bug today)
GBR 80% quantile (raw)          69.7%    ~80%   <- overconfident
GBR 80% conformal               84.8%    ~80%   <- honest (calibrated)
```

So the band is **split-conformal**: fit the median model on a train-proper
slice, take the calibration quantile of its absolute residuals, emit `pred ±
half-width`. This carries a finite-sample coverage guarantee under
exchangeability, and errs conservative (84.8% vs 80%). The safe direction for
the never-overclaim ethic. The spike also surfaced that the **current ±1σ band
is already overconfident on real data** (54.5% vs 68%). Conformal fixes that
existing flaw too, not just ML's.

### 3. The deterministic Projection stays as the thin-data fallback

A learned model needs weekly cycles to learn from. Below **~3 months** of daily
history the app falls back to the deterministic Projection (ADR-0006's trend +
band) rather than invent a learned forecast on too little data. The generator
now also emits `fictional_6month.csv` (180 days, weekend dip) so the learned
path is exercisable. The 30-day `fictional_month.csv` is regenerated
byte-identical (six tests/oracles depend on it).

### 4. The "beat the baseline" gate stays visible

Weekly-persistence and linear-on-features remain rendered baselines alongside
the forecast, so ML's value is auditable on real data going forward. If GBR
ever stops beating the simple line, it shows immediately. The discipline that
keeps the model honest forever, not just at ship time.

### 5. First target is daily good production only

M8 transplants the daily-good forecaster. OEE, downtime, and the
maintenance/breakage signal are later nodes. Forecasting them needs separate
series and (for maintenance) data the CSV does not contain.

## Consequences

- **`scikit-learn` becomes a real `pyproject` dependency** (the learned core
  needs it). `matplotlib` stays spike/dev-only. It is not a runtime dep.
- **A pure, unit-tested forecast module** (successor to `forecast.py`'s
  technique, same "pure function of a dated series" contract as `compute_oee`)
  hosts the GBR + conformal core. Training uses a **time-aware split only**,
  never shuffled and with no lookahead. That is the guard against the leakage
  that would otherwise inflate every score without saying so.
- **The always-band ethic is strengthened, not weakened.** It moves from a
  model *assumption* (Gaussian ±1σ) to a *measured* coverage (conformal), and
  it repairs the existing band's overconfidence into the bargain.
- **Known ceilings.** A learned model drifts as the line changes. The retrain
  cadence (on load? periodic? on drift?) is a later decision. Conformal
  coverage assumes the future exchanges with the calibration set. A regime
  change (new product, new shift pattern) breaks that, and the band would need
  re-calibration. Both are flagged, not solved here.
- **Non-goals for M8.** Remaining-useful-life / breakage prediction (needs
  labeled failures or a degradation sensor. The state CSV has neither.
  MTBF-from-Faults is the honest ceiling, a separate node), multi-target
  forecasting, and neural nets.
- **Open for the next nodes.** UI naming ("future line" vs the section) and
  where the forecast plugs into the page narrative are UI decisions still to
  grill. The glossary's Forecast/Projection split is captured in `CONTEXT.md`.
