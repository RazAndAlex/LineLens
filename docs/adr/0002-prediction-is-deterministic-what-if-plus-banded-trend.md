# Prediction is a deterministic what-if plus a banded trend (no ML)

The "predictive model" in v2.5 is **two deterministic features, not a learned model**:

1. **What-if / sensitivity (core).** Sliders on stop-causes and Availability recompute OEE → production in real time using the OEE identity (OEE = Availability × Performance × Quality). The Pareto's biggest bars become the most impactful sliders, so "tackle the top cause" is a live lever.
2. **Banded trend forecast.** A lightweight extrapolation of the period's trend (e.g. daily production), shown with an explicit uncertainty band — "where is this heading," not "the AI predicts."

We rejected a full time-series/ML forecasting model (scope + overclaiming risk, and it conflicts with removing the AI section and with LineLens's "the computer does the math" ethos), and what-if-only (drops the legitimate "where is it heading" view). The banded forecast must always show its uncertainty; it never states a single confident future number.
