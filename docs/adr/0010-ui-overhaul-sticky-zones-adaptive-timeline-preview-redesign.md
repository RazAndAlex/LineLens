# UI overhaul: per-section sticky zones, adaptive timeline, auto-first preview, color-by-message

## Status

Accepted (2026-07-24, M9 grilling, after firsthand Playwright verification).
Touches ADR-0008: it **reverses the deferred Act-3 slider rail** (decision 7
below supersedes the deferral), narrows the sticky Now-bar's scope, and
revises the cause-color rule (decision 10). ADR-0008's composition
(three-act narrative), palette-validation gate, and `theme=None` rule stand.

## Context

Verified in-browser on `fictional_6month.csv` (9,302 rows,
`.scratch/probe_*.png`): the sticky Now-bar pins but only its date pill stays
visible (the group-by radios hide above the fold), and it stays pinned
through Future line, Reliability, and Export where it is irrelevant; the
state timeline is confetti at 9,302 intervals; the preview & map section
gates the user on 13 technical dropdowns they cannot parse; cause colors are
a meaningless rainbow. Five decisions were resolved by grilling (numbered
6-10, continuing ADR-0009's 1-5, matching .scratch/m9/spec.md):

6. **Narration order.** The user's narration (present → alarms → Pareto →
   future → maintenance) vs ADR-0008's Diagnosis-first. Chosen: **Diagnosis
   stays first** (a number is only worth reading once the data is
   trustworthy) but collapses to a **slim banner**, expanding inline when
   findings exist. The maintenance view (ADR-0009) joins Reliability as the
   final act — it consumes the degradation forecast.
7. **Sticky controls.** Chosen: **two independent per-section CSS zones** —
   Now-controls pin only within Now (fully visible: radios + date range,
   opaque background), the five what-if sliders pin only within Future line.
   A single JS-driven swapping bar was rejected (scroll-position detection in
   Streamlit is the version-fragile hack ADR-0008 already warned about). This
   supersedes ADR-0008's deferral of the Act-3 rail — the rail is now
   decided, as a sticky-top zone like Now's.
8. **State timeline.** Chosen: **adaptive** — wide date ranges render daily
   state-composition bars (Running/Stopped/Idle share per day); ranges
   ≤ ~14 days render the true interval timeline. A calendar heatmap was
   rejected: it hides the stopped/idle split the alarms narrative needs.
9. **Preview & map.** Chosen: **auto-first redesign** — silent auto-map with
   a plain-words summary (rows, date span, machines, recipes, recognized
   roles); the 13 dropdowns move behind an "Adjust column mapping" expander;
   the preview is labeled "first 10 of N"; the machine_id picker hides for
   single-machine files; counter columns are auto-detected, preselected, and
   explained in one plain sentence ("odometer columns — we difference them,
   not sum them"). The mapping UI becomes a fallback, not a gate.
10. **Color & design.** Chosen: a full design pass (frontend skill) **after**
   the structural fixes, under one rule — **color by message, not by
   category**: loss charts (Pareto, downtime-by-reason) share the
   problem-orange family ordered by impact; planned causes (Changeover,
   Maintenance) are neutral ("scheduled, not a loss"); state colors stay
   fixed (ADR-0008); the forecast keeps one accent. Every new hex passes the
   accessibility validator; every chart gains a one-line plain-words caption
   stating its message.

## Consequences

- The sticky Now-bar's CSS now scopes pinning to its section container; the
  version-fragility warning (Streamlit 1.59.2 DOM) carries over — browser
  probes are the re-verification path.
- `_STATE_COLOR` is untouched; the cause-color rule from ADR-0008
  (`_category_color_map`, entity-keyed) is **replaced for loss charts** by
  the message-keyed orange family. Entity-keyed coloring survives only where
  causes are genuinely categories, if anywhere — the design pass decides.
- Preview redesign changes the first-run flow: upload → summary → Analyze,
  zero required decisions. Golden/sample files must all auto-map cleanly or
  the summary must honestly say what wasn't recognized.
- The design pass (P6) is sequenced last so structural changes don't get
  designed twice.
