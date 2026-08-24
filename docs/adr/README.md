# Architecture decisions

Eleven records, one per decision that closed off an alternative someone could
reasonably have picked. Each states the choice, what it rejected, and why.

Read them in order if you want the shape of the project. Read
[0001](0001-interval-grain-and-single-ingest-path.md) first: the interval grain
it fixes is the assumption everything else rests on.

| ADR | Decision |
|---|---|
| [0001](0001-interval-grain-and-single-ingest-path.md) | The state interval is the atomic unit, and there is one ingest path |
| [0002](0002-prediction-is-deterministic-what-if-plus-banded-trend.md) | Prediction is a deterministic what-if plus a banded trend |
| [0003](0003-oee-availability-scope.md) | What availability counts, and what it does not |
| [0004](0004-totals-ui-oee-cards-pareto.md) | Totals read as OEE cards plus a bottles-lost Pareto |
| [0005](0005-what-if-freed-time-and-held-kpis.md) | What-if frees time and holds the other KPIs fixed |
| [0006](0006-banded-trend-forecast-linear-least-squares.md) | The banded trend is ordinary least squares |
| [0007](0007-forecast-is-gradient-boosted-with-conformal-band.md) | The learned forecast is gradient-boosted with a conformal band |
| [0008](0008-three-act-narrative-sticky-now-controls-validated-palette.md) | A three-act narrative, sticky controls, a validated palette |
| [0009](0009-predictive-maintenance-service-counter-due-window.md) | Predictive maintenance is a due window from a service counter |
| [0010](0010-ui-overhaul-sticky-zones-adaptive-timeline-preview-redesign.md) | Sticky zones, an adaptive timeline, a redesigned preview |
| [0011](0011-fastapi-react-ui.md) | The UI moves from Streamlit to FastAPI and React |

## A note on the evidence they cite

Several records cite probe scripts and screenshots under `.scratch/`, such as
`.scratch/m8/spike.py`. That directory was the working area while the decision
was being made and it is not published, so those paths do not resolve here.

They are kept as written on purpose. An ADR is a record of how a conclusion was
reached, and rewriting the citations afterwards would quietly change the
history. Read them as "this was measured, here is what ran", not as a link.

Where a decision is checked by something that ships, the record points at that
instead: a test, a golden dataset, or the code itself.
