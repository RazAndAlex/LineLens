# The analyzed page is a three-act narrative with sticky Now-controls and a validated palette

## Status

Accepted (2026-07-24, M8). Records the three M8 **UI** decisions the build plan
deferred to this record: the page's three-act composition (plan node 2, built
P3–P5), the sticky Now-controls (node 6, built P2), and the canonical color
system (node 8, built P1). Pulls the reasoning from the plan's resolved nodes
and the per-phase DONE notes in `.scratch/m8/plan.md`. Cites them rather than
re-deriving.

Touches, rather than supersedes, the prior UI/forecast ADRs: it **reverses
ADR-0005's what-if placement** (Decision 1), restates ADR-0002's
never-a-confident-number ethic at the composition layer, and carries
ADR-0006/ADR-0007's band discipline into where each band is drawn. Cross-links
ADR-0002, ADR-0005, ADR-0006, ADR-0007.

## Context

Through M7 the analyzed page had grown by accretion. OEE cards, a Pareto, a
"5 · What-if" section, generic charts, a forecast overlay, export. Each added
wherever it slotted numerically. Three pressures forced a composition decision
rather than another append:

1. **The forecast and the what-if answer different questions but had been
   separated.** The forecast ("where is this heading") and the what-if ("what
   would move it") are two views of the *future*. ADR-0005 had placed the
   what-if in its own section right after the OEE cards, and ADR-0006 had
   overlaid the forecast on the Now production bars. A reader asking "what's
   next" had to visit two unrelated places, and the all-history forecast trend
   drawn over a date-narrowed bar window (ADR-0007's leakage guard, see P2)
   was incoherent.
2. **The Now-charts scroll out of view.** Group-by and date-range are the
   controls a reader returns to most, yet they sat at the top of a tall chart
   block. Without a sticky control bar, narrowing the date range or switching
   day/shift meant scrolling back up.
3. **State color was not stable across charts.** The same state could read as
   blue in one chart and orange in another (a categorical colorway applied by
   rank, not by entity), which is the classic "blue means Stopped here, blue
   means Idle there" trap.

The decisions below are UI-layer only. Every number still comes from the
`linelens` library. This ADR governs ordering, stickiness, and color.

## Decision

### 1. The page is a three-act narrative: Diagnosis → Now → Loss → Future line → Reliability → Export

`_render_results` emits six sections, each behind an `st.divider()`, in this
exact order (asserted in-browser by `.scratch/m8/p3_section_order_check.py` as
the `h2` tail `[Diagnosis, Now, Loss, Future line, Reliability, Export]`):

- **Diagnosis** (pre-act): the data-quality findings, severity-grouped, plus the
  aggregation-contrast chart lifted out of the charts block. It is a
  whole-dataset diagnosis that the date range must never scope.
- **Act 1. Now:** OEE cards (A/P/Q/OEE) + the state/production/downtime charts.
  This is the only section the date range and group-by scope.
- **Act 2. Loss:** the bottles-lost Pareto (the problem).
- **Act 3. Future line:** the forecast (observed + conformal band + what-if
  line) and the lever waterfall. **The forecast relocated here out of the Now
  production chart, and the what-if relocated here out of its own "5 · What-if"
  section**. Both future views now sit together.
- **Act 4. Reliability:** the Performance-degradation forecast and the banded
  MTBF tile (ADR-0007's ceiling).
- **Export:** the download buttons.

**This reverses ADR-0005's placement** (Decision 4 there: "a new 5 · What-if
section, Charts → 6, Export → 7"). ADR-0005's *arithmetic* is untouched: freed
time becomes run time at the line's current effective speed, P and Q held, with
top-5 sliders (ADR-0005 Decisions 1-3). Only *where on the page* the what-if
renders moves. The reversal is justified: with a forecast now in the page, the two
future views belong together under one act, and the "5 ·" numbering that
ADR-0005 pinned no longer holds once the sections are acts rather than a flat
list. The what-if's held-vs-live KPI semantics (ADR-0005 Decision 2) still
govern the Act-3 KPI cards.

The narrative answers the reader's three questions in order: *what is wrong
with the data, where do we stand today, where is this heading*. It keeps the
export out of the story. Findings stay first because a number is only worth
reading once the data behind it is trustworthy (ADR-0002's ethic, applied to
page order).

### 2. Sticky controls pin the Now-filter bar. The Act-3 slider rail was deferred

The Group-by selector + date-range `st.date_input` render inside an
`st.container` whose `stLayoutWrapper` is made `position: sticky; top: 0` via
the instrument CSS (`.scratch/m8/p2_browser_check.py` proves `top == 0` while
the charts scroll under, on both the full span and a narrowed range). The
anchor is a `[data-ll="filterbar"]` marker inside that one container. The CSS
targets `[data-testid="stLayoutWrapper"]:has([data-ll="filterbar"])`.

The plan's node-6 *second* sticky zone, a sticky-left slider rail for Act 3,
was **deferred**. Act 3 did not exist until P3, so the rail had nothing to pin
to at P2. Node 6's own recorded fallback was "sticky-top for both." The Act-3
sliders are few (top-5 causes, ADR-0005 Decision 3) and sit immediately above
the chart they move, so the cost of the absent rail is low. It is the named
upgrade if Act 3 grows.

**Why the wrapper, not the inner block:** `position: sticky` is bounded by the
*parent*. `st.container` renders `stLayoutWrapper > stVerticalBlock`. The inner
block's parent is the (short) wrapper, so making the block sticky never sticks.
The wrapper's parent is the tall root block, so the wrapper pins. This is
Streamlit-DOM-specific and therefore version-fragile (Streamlit 1.59.2 today).
The CSS comment names the re-verification step if a version bump breaks it.

### 3. Palette: reuse the validated tokens. Palette A's literal hexes were rejected

Node 8 asked for a "Cobalt & Amber" palette (Palette A) plus canonical
`STATE_COLOR` / `CAUSE_COLOR` maps. The dataviz validator the plan itself
mandated **rejected Palette A's literal hexes.** Its cause pair `#58A6B8`↔
`#4A90E2` measures ΔE 10.1, below the 15 normal-vision hard floor (and fails the
lightness/chroma checks). Rather than hunt for new hexes, the intent ("evolve
the blue identity") was mapped onto the already-validated tokens:

- `_STATE_COLOR = {Running: _PRIMARY (#3987e5), Stopped: _DOWN (#d95926), Idle:
  _INK_MUTED (#6B7B8F)}`. Same state = same hex in every chart (overall,
  stacked-by-day, timeline), proven deterministically on the 6-month CSV.
  `Idle` is a deliberately recessive low-chroma neutral (it clears the CVD and
  normal-vision separation floors. Its below-categorical-chroma status is the
  named ceiling, secondary-encoded via segment gaps + legend).
- **No `CAUSE_COLOR` string dict.** Stop causes are *dynamic* CSV strings
  (`summaries` emits raw `stop_cause` values. The sample has 7 including
  `Changeover`, not a fixed 6). A hardcoded cause→hex dict would silently
  mis-color every real export. Instead `_category_color_map(sorted unique
  causes, _COLORWAY)` assigns slots entity-keyed (by the cause name), never by
  rank. So the same cause keeps its color however the data is sliced.
- Pareto stays **uniform orange** (`_DOWN`): node 3 and its own docstring define
  it as the single "problem" slot, which overrides node 8's "wire CAUSE_COLOR
  into Pareto." Causes are colored where they are categories (the downtime
  charts), not where the bar is "the loss."

Every chart hex is a validated categorical/status slot or a lone surface/ink
value, and `st.plotly_chart` is called with `theme=None` so Streamlit never
remaps the palette. Legibility (template margins `l=64, b=72`, axis-title
standoff 18, Pareto `tickangle -30°`) is set once in `_apply_chart_theme`,
inherited by every figure.

## Consequences

- **The forecast is no longer drawn over a date-narrowed bar window.** Relocating
  it to Act 3 resolves the incoherence ADR-0007's leakage guard was papering
  over (the guard trained on all history but displayed over a scoped window).
  Act 3 always trains and displays on the full history, and the Now production
  chart is plain bars.
- **`_render_results` is the composition root and has no unit test of its own.**
  Its regression check is "library tests green + behaves in browser"
  (`.scratch/m8/p6_full_sweep.py` is the consolidated evidence pass). The pure
  helpers it calls (`compute_oee`, `forecast_ml`, `whatif.perturb`,
  `reliability.mtbf_band`, …) are the tested seam. The page wires them.
- **The what-if's KPI semantics are unchanged by the move.** ADR-0005 Decision 2
  (P/Q held, A/OEE/good live) still governs the Act-3 cards. Only the section's
  address changed. ADR-0005 should be read with this reversal in mind.
- **Sticky CSS is Streamlit-version-fragile.** A version bump that renames
  `stLayoutWrapper` or changes the container DOM will silently stop pinning. The
  CSS comment and `p2_browser_check.py` are the re-verification path. The
  node-6 fallback (sticky-top for both zones) remains the retreat.
- **Palette A is closed, not deferred.** Its hexes are recorded as validator-
  failed so a future "refresh the palette" pass does not reintroduce them. New
  charts reuse `_COLORWAY` / `_STATE_COLOR` / `_category_color_map`. No
  off-palette defaults, no new hexes without a passing validator run.
- **The Act-3 sticky-left rail and a second Pareto remain out of scope.** The
  rail is the named Act-3 upgrade. A second Pareto (downtime-seconds ranking)
  was rejected (node 3: it ranks causes near-identically to bottles-lost, and
  the downtime bar chart already covers the time lens).
