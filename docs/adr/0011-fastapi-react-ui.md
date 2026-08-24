# The UI is a FastAPI + React command deck; the Streamlit app is archived

## Status

Accepted (2026-07-24, cutover). Supersedes the Streamlit *implementation* of
the analyzed page — every UI ADR up to and including
[ADR-0010](0010-ui-overhaul-sticky-zones-adaptive-timeline-preview-redesign.md)
describes behavior that this rebuild re-implements and extends in React. The
`linelens` library is untouched by construction; the archived Streamlit app
lives under `archive/streamlit-ui/` as a frozen reference. Amends
[ADR-0006](0006-banded-trend-forecast-linear-least-squares.md)'s horizon for
UI display only (Decision 4).

## Context

The Streamlit UI (M6b through M9, ADR-0008/0010) hit a design ceiling that
three structural properties of the framework made permanent:

1. **The rerun model fights a command deck.** Every widget interaction
   re-executes the whole script top to bottom; the results the page renders
   live in `session_state` and every render is a re-wire. A dense,
   always-visible OEE hero with live what-if feedback is exactly the shape
   this model makes expensive and brittle.
2. **Sticky control zones were version-fragile by construction.** ADR-0008
   Decision 2 and ADR-0010 Decision 7 pinned controls by targeting Streamlit's
   internal DOM (`stLayoutWrapper:has([data-ll=...])`) from injected CSS, with
   an explicit "re-verify on every version bump" warning. The M9 bug — the
   filter bar sliding under `stHeader` — was that fragility realized.
3. **The charts could not carry the design.** Plotly-through-Streamlit gave no
   cheap route to the review-driven interactions the user asked for
   (zoom-windowed forecast, per-chart sliders, a merged reliability view), and
   the design system lived as a CSS string injected at runtime.

User review of the M9 page added four concrete complaints the framework
couldn't answer: the OEE read as plain body text, the what-if OEE was
indistinguishable from the baseline, the future line opened on six months of
history with the interesting part squashed right, and the chart legend spoke
jargon ("conformal band", "median forecast").

## Decision

### 1. Streamlit is replaced by FastAPI + React, with `linelens` untouched

The backend is a thin FastAPI shell (`server/app.py`, served by `api.py` on
127.0.0.1:8741) over the same calls the Analyze button ran — `make_context →
summarize → run_validation → oee_from_context → maintenance_from_context` —
plus the pure, UI-free helpers the Streamlit app used, extracted verbatim into
`server/logic.py` (single source for both frontends while the old one lived).
Serialization (`server/serialize.py`) is the one place pandas shapes become
JSON; the frontend is Vite + React + TypeScript + Tailwind + ECharts (`web/`),
built to `web/dist` and served as static files, so **Node.js is a build-time
dependency only**. The `ui`/`browser` extras (streamlit, plotly, playwright)
are retired; `web` (fastapi, uvicorn) and `forecast` (sklearn) remain.

### 2. The page is a command deck with takeaway titles

A sticky hero bar carries only the OEE (display font, 3–4× body size) with
A·P·Q satellite chips and an inline what-if delta badge (`77.3% → 80.1%
(+2.8 pts)`) the moment a lever moves — zero eye movement between baseline
and delta. A scroll-spy anchor nav leads six sections (Diagnosis · Now ·
Loss · Future · Health · Export). Every section and card headline *says*
something computed from the data ("Starvation costs you 307,067 bottles —
40% of all loss"), never a bare label; explanations are on-demand tooltips,
never inline paragraphs. Dark control-room theme: near-black, amber accent
reserved for actions and active signal, semantic green/red for machine
states and deltas, tabular numerals throughout.

### 3. Chart labels speak plain language; the domain glossary is untouched

On charts and legends the band is the **"expected range"** and the central
line the **"most likely path"** — the words "conformal band" and "median
forecast" no longer appear on a chart. The methodology stays one hover away
(the card's info tooltip names the learned-vs-deterministic technique and
coverage). These labels are UI copy: `CONTEXT.md`'s domain glossary
(deliberately) does not change, and the library's own names
(`MLForecastResult.median`, conformal calibration in `forecast_ml`) stay as
they are.

### 4. The API resolves a 14-day display horizon; ADR-0006's 7-day default stands

The future chart opens future-majority — roughly the last 7 observed days
plus the horizon — with an ECharts dataZoom (inside drag + slider) to zoom
out to full history. To make that view useful, the analyze/whatif routes
resolve forecasts with a **14-day horizon** (`_API_FORECAST_HORIZON`).
ADR-0006's 7-day horizon is unchanged as the library/logic default
(`server/logic._FORECAST_HORIZON_DAYS`); `_resolve_forecast` and
`_degradation_caption` take a `horizon` parameter defaulting to it, so the
archived Streamlit app's behavior is byte-identical. The what-if endpoint
also returns the production forecast's horizon lifted by the recovered
bottles (`whatif.spread_recovered`, the archived app's `_future_line_chart`
move), drawn as a green "what-if path"; the Performance/Health chart
deliberately does not react to levers (ADR-0005's held-P/Q semantics).

### 5. The group-by segmented control is replaced by chart zoom

The overall/day/shift toggle and the daily charts' double-listening (picker
vs segmented control) are gone. The Now charts show the full daily series
with the same dataZoom interaction as the forecast; the date-window picker
remains but scopes only the takeaway numbers and totals tables (via
`/scope`, mirroring the archived `_scoped_ctx` semantics, forecast excluded
per ADR-0007's leakage guard). Shift grouping as a UI mode disappears
(the library still computes shift rows; the totals tables show them).

### 6. Reliability is one merged Health view

The two overlapping M8/M9 views (Performance-degradation forecast and the
MTBF tile) plus the M9 maintenance act merge into a single Health section:
degradation chart with the concern floor, MTBF band tile, and the
maintenance due-window block — thin-data honesty states preserved (never a
broken chart: `too_few` / `zero_scatter` / `no_series` render explicit
empty states).

### 7. The old UI is archived, not deleted

`app.py`, its four render test files, and `.streamlit/` move to
`archive/streamlit-ui/` (a plain folder, like `LineLens_export/`). The repo
has no git; the archive is the reference for the behaviors this ADR
re-implements. The pure helpers and their ported tests live on in
`server/logic.py` and `tests/test_server_logic.py`.

## Consequences

- **Validation surface changes shape.** `uv run pytest` (117 tests) covers
  the library, the pure logic, and the API end-to-end via FastAPI's
  TestClient; the rendered page is verified in-browser (Playwright passes
  `pass2_*`/`pass3_*`/`pass4_*` screenshots at the repo root), the same
  contract the Streamlit page had.
- **The frontend build is a new release step.** `web/dist` ships built;
  `LineLens.bat` rebuilds it (via `npm ci && npm run build`) only when
  missing, keeping the double-click experience the Streamlit launcher had.
- **ADR-0008/0010 read as behavior specs now.** Their decisions (three-act
  order, sticky controls, auto-first preview, color-by-message) are
  re-implemented in React; where this rebuild intentionally diverges
  (group-by removal, merged Health, 14-day horizon), this ADR records it.
- **New-hex discipline carries over.** The palette is the theme's design
  tokens (amber accent, semantic green/red); the loss-tiering idea from
  ADR-0010 Decision 10 is preserved, re-hued to the amber family.
