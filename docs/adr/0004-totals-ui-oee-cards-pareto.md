# Totals UI: OEE card tiles + bottles-lost Pareto

## Status

Accepted (2026-07-23, M5). Implements plan row 5 and locked decision #6
("Totals UI. KPI card tiles + charts. Raw tables collapsed into an expander").
Supersedes nothing. ADR-0001 (grain), ADR-0002 (deterministic prediction), and
ADR-0003 (the KPI formulas) stand. This one pins the *rendering* of the numbers
those earlier decisions produce.

## Context

M5 turns M4's `OEEResult` into the page's headline. Three things had to be
decided before writing the render code, because the dataset's degenerate paths
and the existing page structure both push on them:

1. **Where do the cards + Pareto sit relative to the existing sections?** The
   page already had numbered sections (Findings · Totals · Charts · Export), and
   locked decision #6 says the *raw tables* get collapsed into an expander. It
   does not say which section the cards live in or whether the page gets
   renumbered.
2. **What does a degenerate KPI read as?** M4 yields 0.0 (never NaN) for an
   empty-Running Performance, a no-parts Quality, or a no-time Availability, and
   records a human `note` explaining why (ADR-0003). A bare "0.0%" tile reads as
   a catastrophic score, not "undefined."
3. **What does the wrapper's `None` mean in the UI?** `oee_from_context`
   returns `None` when there is no duration axis or no STATE column (ADR-0003).
   M5 is its first consumer, so an unguarded `None` would crash the page.

## Decision

The former **"Totals"** section becomes **"OEE".** Same slot, no renumbering
(Findings stays 3, OEE is 4, Charts 5, Export 6). It holds, in order:

1. **Four `st.metric` tiles**. Availability / Performance / Quality / OEE.
   Each showing the ratio as a percent plus a one-line derivation caption built
   from M4's time-breakdown / count fields (the reason those fields exist).
   `st.metric` is reused, not a custom card: the existing `_INSTRUMENT_CSS`
   already styles `[data-testid="stMetricValue"]` as an instrument readout, so
   the cards match the look with no new CSS.
2. **A bottles-lost Pareto.** A vertical `px.bar` per unplanned stop cause in
   the downtime/problem color slot (`_DOWN`, the same orange the existing
   downtime chart uses) plus a cumulative-% line on a right axis. Built with
   `px.bar` (not a bare `go.Figure`) so it inherits the `_apply_chart_theme`
   instrument template automatically. The cumulative line is added as a second
   trace.
3. **The three raw totals tables** (state / production / downtime-by-reason)
   **collapsed into an `st.expander`** below the Pareto. They come from
   `summaries`, independent of OEE, so they render whether or not OEE resolved.

Degenerate and missing-data UX:

- A KPI with an M4 `note` renders **"—"** for its value and the note as its
  caption. Never a bare 0%. Notes not tied to a KPI (e.g. a negative-duration
  warning) surface as an alert under the tile row.
- A `None` `OEEResult` renders an info message naming the two things that must
  be mapped (a STATE column, and a time basis: a duration column or both
  start/end timestamps). The raw-tables expander still shows.

OEE is **consumed, never recomputed in the UI**: `oee_from_context(ctx)` runs
once at Analyze time and is stored on the result. M5 does not recompute KPIs
(ADR-0003's pure core is the contract M6/M7 will perturb).

## Consequences

- **Cards and charts read as one system** with the existing instrument look.
  No new palette, fonts, or CSS. The Pareto reuses the downtime color slot and
  the shared chart template.
- **No page renumbering churn.** Only the "Totals" header text changes (to
  "OEE"). Findings/Charts/Export keep their numbers.
- **The raw tables are not lost.** They move behind one expander click for
  anyone who wants the seconds-by-state / counts drill-down that produced the
  cards.
- **Degenerate inputs are legible.** A user who loads a file with no Running
  rows sees "—" and "no Running time. Performance undefined", not a misleading
  0.0% OEE.
- **The `None` path is the contract boundary with M6/M7.** If a future what-if
  or forecast wants to render KPIs without a full context, it calls the pure
  `compute_oee` and builds an `OEEResult` directly. The render helpers take that
  object, not a context.
