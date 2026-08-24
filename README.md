# LineLens

[![CI](https://github.com/RazAndAlex/LineLens/actions/workflows/ci.yml/badge.svg)](https://github.com/RazAndAlex/LineLens/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

**Local-first diagnostics for industrial machine data.** Drop in a CSV exported
from a PLC, historian, SCADA system, or production database. LineLens checks it,
totals it honestly, and shows you what it found. Nothing leaves your machine.

Industrial dashboards routinely **sum cumulative totalizers** — odometers that
should be differenced. The result is idle time and parts counts that are wrong
by multiples, reported with total confidence. LineLens finds that class of
mistake and shows the naive number next to the honest one.

Here it is on the demo file shipped in this repository, where a summed idle
totalizer reads **87,000 seconds against a true 24,000** — an overstatement of
3.6×. The number in the heading is calculated by the tool, not written by hand:

![A naive dashboard would overstate idle_seconds_total 3.6×](docs/screenshots/01-diagnosis-overstated-3.6x.jpg)

Every calculation, validation, and finding is deterministic. No AI, no guessed
totals, no invented severities, and nothing ever touches a raw row.

## What you get

Map the columns once and the file becomes a command deck: a sticky OEE figure
with its Availability, Performance, and Quality satellites, then five sections
that each answer one question.

![The command deck: OEE with A·P·Q satellites and the daily state timeline](docs/screenshots/02-command-deck.jpg)

**Loss** prices every stop in bottles and ranks them, so the argument about
where to spend the next maintenance hour has a number attached.

![The vital few stops, priced in bottles](docs/screenshots/03-loss-pareto.jpg)

**Future** projects daily output forward as a band, never a single confident
number, and gives you levers: shrink a stop cause by a percentage and watch the
horizon and the OEE move with it.

![Daily output continued 14 days ahead, with what-if levers](docs/screenshots/04-future-what-if.jpg)

**Health** asks whether the line is slowing down, how often it fails, and when
the next service is due.

![Performance band against the 85% concern floor, MTBF, and service counter](docs/screenshots/05-health-reliability.jpg)

Mapping is the only step that asks anything of you, and it guesses first. The
panel on the right tells you what each mapping unlocks before you commit to it.

![Thirteen columns mapped automatically, with a live capability checklist](docs/screenshots/06-map-columns.jpg)

## What it does, precisely

- Accept one CSV; preview and profile it.
- Map columns with heuristic suggestions, and designate counters.
- Validate timestamps, durations, and machine states; surface affected rows.
- Classify counters as cumulative or unknown, and detect resets with a cause.
- Calculate state, production, and downtime totals, overall or by day or shift.
- Flag the headline aggregation problem: a cumulative totalizer a dashboard
  **sums** instead of differences, shown as naive sum against honest total.
- Compute OEE with an explicit availability scope ([ADR-0003](docs/adr/0003-oee-availability-scope.md)).
- Forecast daily good output as a band, gradient-boosted with a conformal
  interval ([ADR-0007](docs/adr/0007-forecast-is-gradient-boosted-with-conformal-band.md)).
- Estimate reliability and a maintenance due window ([ADR-0009](docs/adr/0009-predictive-maintenance-service-counter-due-window.md)).
- Export a cleaned CSV and a structured findings file, as JSON or CSV.

## Status

**v2.5.** Ten milestones shipped, from CSV ingestion through the OEE module,
the bottles-lost Pareto, the what-if model, the banded and learned forecasts,
predictive maintenance, and the cutover from Streamlit to FastAPI + React. The
old Streamlit UI is frozen under `archive/streamlit-ui/` for reference.

**117 tests, all passing**, run on every push by the CI workflow above. Eleven
architecture decisions are recorded in [`docs/adr/`](docs/adr/), each one
explaining a choice this project had to make and could have made differently.

Not production software. It is a single-user local tool with no authentication,
no multi-tenancy, and no hardening; it reads files you hand it, on your machine.

## Read it without installing it

The [`examples/`](examples/) folder holds committed reports for the synthetic
datasets, so you can see the output before deciding whether to run anything:

- [`totalizer_summed.findings.md`](examples/totalizer_summed.findings.md) — the
  headline case: **87,000 naive against 24,000 honest**.
- [`cumulative_with_reset.findings.md`](examples/cumulative_with_reset.findings.md)
  — a counter reset at row 6, plus a **235 against 75** contrast.
- [`valid_event.findings.md`](examples/valid_event.findings.md) — the clean
  case, where the answer is that there is nothing wrong.

## Run it

Requires Python 3.12 or newer and [uv](https://docs.astral.sh/uv/). Node.js 20+
is needed once, to build the frontend.

```bash
git clone https://github.com/RazAndAlex/LineLens.git
cd LineLens

npm --prefix web ci && npm --prefix web run build   # build the UI (first time only)
uv sync --extra web --extra forecast                # install the app
uv run python api.py                                # start it
```

A browser opens at http://127.0.0.1:8741. On Windows, `LineLens.bat` does all
of this in one double-click and builds the frontend for you if it is missing.

If port 8741 is busy, uvicorn exits with a bind error. Close whatever owns it,
usually an older LineLens window, and start again.

Then upload one of the bundled datasets:

- `sample_data/fictional_month.csv` — a full month of line data. Start here.
- `sample_data/golden/totalizer_summed.csv` — the 3.6× case above. Keep
  `idle_seconds_total` mapped as a counter.
- `sample_data/golden/cumulative_with_reset.csv` — a parts totalizer with one
  reset in it.
- `sample_data/valid_event.csv` — clean data, no findings.

## Tests

```bash
uv sync --all-extras --dev
uv run pytest
```

Unit, integration, golden-driven, and API end-to-end tests. The golden datasets
under `sample_data/golden/` carry hand-checked `.expected.json` files and are
the source of truth for every number — written by hand, never AI-derived.

Without the `forecast` extra, `tests/test_forecast_ml.py` skips itself on
import and the suite quietly shrinks, which is why CI installs `--all-extras`.

## Project layout

```
linelens/     the library: ingestion → schema → validation → counters → summaries → reporting
server/       FastAPI backend: routes, serializers, UI-free logic (ADR-0011)
web/          React + TypeScript frontend (Vite, Tailwind, ECharts); builds to web/dist
api.py        entry point: serves the API and the built frontend on 127.0.0.1:8741
tests/        unit, integration, golden-driven, and API tests
sample_data/  synthetic fixtures; golden/ holds the hand-checked sets
examples/     committed reports, readable on GitHub without running anything
docs/adr/     the eleven architecture decisions
archive/      frozen history: the retired Streamlit UI, kept for reference
```

[`CONTEXT.md`](CONTEXT.md) carries the domain vocabulary and the architecture in
prose. [`docs/LineLens_in_plain_words.md`](docs/LineLens_in_plain_words.md)
explains the whole thing without assuming you know what a totalizer is.

## Stack

Python and pandas for the core, which stays pandas-only so the library can be
imported without dragging in a web server. FastAPI serves a React and
TypeScript frontend. scikit-learn lives in its own `forecast` extra. Dataclasses
for models, with Pydantic only where a boundary earns it.

## License

MIT. See [LICENSE](LICENSE).

Built by Andrei Razvan Alexandru.
