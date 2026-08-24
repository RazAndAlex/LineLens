# Sample data

Synthetic industrial-machine CSVs for demos, tests, and the example reports in
[`../examples/`](../examples/). **None of this is real industrial data** — every
file is hand-authored and the golden numbers are hand-truthed by a human, never
AI-derived (AGENTS §5). Safe to publish.

## Golden datasets (hand-truthed)

Each carries a sibling `<name>.expected.json` documenting the input, the
expected totals/findings, and the known resets/invalid rows. These are the
source of truth for numerical tests and the example reports.

| File | Demonstrates | Headline number |
|---|---|---|
| `golden/totalizer_summed.csv` | Brief §5: a cumulative idle-time totalizer a dashboard **sums** instead of differences. Stair-step export, no reset. | **87,000 naive vs 24,000 honest** |
| `golden/cumulative_with_reset.csv` | A cumulative parts totalizer with **one endorsed reset**; clean event data otherwise. | reset at row 6; **235 naive vs 75 honest** |
| `golden/two_day.csv` | Clean 2-day event data proving daily grouping doesn't leak across days. | day-1 Running 1800 + Idle 600; day-2 Running 1200 + Idle 300 |
| `valid_event.csv` (truth in `golden/valid_event.expected.json`) | Clean event data with state / stop-reason / shift / counts. The "no findings" case. | 6 rows, yield 98.4% |

## Fictional month (v2.5 full-schema demo)

A generated, realistic month of event-interval data carrying **every v2.5
column** (recipe, speed_target, speed_actual, planned, and the renamed
stop_cause). The largest clean dataset — it loads, maps, and coerces with zero
findings, so it's the demo for the full wizard → analyze flow and the fixture
for the OEE / what-if / forecast milestones (M4–M7).

| File | Demonstrates | Headline number |
|---|---|---|
| `fictional_month.csv` | 30 days, 1 machine, 3 shifts, 2 recipes; the 7 stop-cause families with a clear Pareto; the `planned` flag (Changeover); a gentle OEE drift. | 1576 rows, Quality 99.6%, OEE 82.5% |

Regenerate it deterministically with
`.venv\Scripts\python.exe sample_data\generate_month.py` (fixed seed; same CSV
every run). The generator's docstring records *why* each design choice keeps
the dataset clean against the validation rules. Not a golden set: it has no
hand-truthed `.expected.json` (its totals are machine-derived, not human-truthed
per AGENTS §5).

## Load fixtures (non-golden)

Small files that exercise ingestion edge cases; no golden truth needed.

| File | Exercises |
|---|---|
| `empty.csv` | 0-data-row dataset (header only or fully empty). |
| `header_only.csv` | Header present, no rows. |
| `latin1.csv` | latin-1 encoded content — the utf-8 → latin-1 fallback path. |
| `numeric_with_text.csv` | Numeric columns contaminated with text — per-column parse-failure findings. |
| `semicolon.csv` | Semicolon-delimited — separator auto-sniffing. |

## Add a dataset

See `AGENTS.md` §5. Put the CSV here (or under `golden/` for a golden set) and,
for golden sets, write the `.expected.json` by hand. Golden numbers are never
AI-derived.
