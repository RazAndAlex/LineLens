# Sample data

Synthetic industrial-machine CSVs for demos, tests, and the example reports in
[`../examples/`](../examples/). **None of this is real industrial data.** Every
file is hand-authored, and a person worked out the golden numbers by hand.
Safe to publish.

## Golden datasets (hand-truthed)

Each carries a sibling `<name>.expected.json` documenting the input, the
expected totals/findings, and the known resets/invalid rows. These are the
source of truth for numerical tests and the example reports.

| File | Demonstrates | Headline number |
|---|---|---|
| `golden/totalizer_summed.csv` | A cumulative idle-time totalizer a dashboard **sums** instead of differencing. Stair-step export, no reset. | **87,000 naive against 24,000 honest** |
| `golden/cumulative_with_reset.csv` | A cumulative parts totalizer with **one endorsed reset**. Clean event data otherwise. | reset at row 6, **235 naive against 75 honest** |
| `golden/two_day.csv` | Clean 2-day event data proving daily grouping does not leak across days. | day 1 Running 1800 plus Idle 600, day 2 Running 1200 plus Idle 300 |
| `valid_event.csv` (truth in `golden/valid_event.expected.json`) | Clean event data with state / stop-reason / shift / counts. The "no findings" case. | 6 rows, yield 98.4% |

## Fictional month (v2.5 full-schema demo)

A generated, realistic month of event-interval data carrying **every v2.5
column** (recipe, speed_target, speed_actual, planned, and the renamed
stop_cause). These are the largest clean datasets. They load, map, and coerce with zero
findings, so they are the demo for the full wizard-to-analyze flow and the
fixtures for the OEE, what-if, and forecast milestones (M4 to M7).

| File | Demonstrates | Headline number |
|---|---|---|
| `fictional_month.csv` | 30 days, 1 machine, 3 shifts, 2 recipes. The 7 stop-cause families with a clear Pareto, the `planned` flag on Changeover, and a gentle OEE drift. | 1576 rows, Quality 99.6%, OEE 82.5% |
| `fictional_6month.csv` | The same schema over 6 months. It also carries planned Maintenance. Long enough that the forecast and the reliability estimates have real history behind them. | 9297 rows, Quality 99.6%, OEE 77.3% |

The six-month file is wide enough that the Now charts switch from one bar per
day to one bar per week. The server picks the grain (`state_timeline` in
`server/serialize.py`) and the chart hints name it, so a weekly total is never
read as a daily one.

Regenerate it deterministically with
`.venv\Scripts\python.exe sample_data\generate_month.py` (fixed seed, so the same CSV
every run). The generator's docstring records *why* each design choice keeps the dataset
clean against the validation rules. Neither is a golden set: they have no hand-truthed
`.expected.json`, because their totals are machine-derived rather than checked
by a person.

## Load fixtures (non-golden)

Small files that exercise ingestion edge cases. No golden truth needed.

| File | Exercises |
|---|---|
| `empty.csv` | 0-data-row dataset (header only or fully empty). |
| `header_only.csv` | Header present, no rows. |
| `latin1.csv` | latin-1 encoded content. Exercises the utf-8 to latin-1 fallback path. |
| `numeric_with_text.csv` | Numeric columns contaminated with text. Produces per-column parse-failure findings. |
| `semicolon.csv` | Semicolon-delimited. Exercises separator auto-sniffing. |

## Add a dataset

Put the CSV here, or under `golden/` for a golden set. For a golden set, write
the `.expected.json` by hand. A golden number is only golden because a person
worked it out and checked it. Never derive one with AI, and never copy one back
out of the tool's own output: that would make the test agree with whatever the
code currently does.
