# Contributing

LineLens is a portfolio project. One person builds it, in their own time,
around a full-time job. That shapes what is useful to send.

## Most useful

**Tell me a number is wrong.** This tool exists to catch machine data that
does not add up, so a wrong total here is the worst kind of bug. Open an issue
with the CSV that reproduces it, or a description of its shape if the data is
not yours to share. That goes to the front of the queue.

**Tell me the quickstart failed.** The README claims a stranger can clone this
and see it running in under ten minutes. If that was not true for you, say
where it broke and what your machine is. A quickstart that only works on the
author's laptop is a broken quickstart.

## Also welcome

Bug reports, a CSV export shape the mapper does not recognize, and questions
about why something is built the way it is. The eleven records in
[`docs/adr/`](docs/adr/) answer many of the "why" questions already.

## Before you send a pull request

Open an issue first. This is a small project with a deliberate shape, and I
would rather discuss a change than turn down finished work.

If we agree on the change:

```bash
uv sync --all-extras --dev
uv run pytest                       # 120 tests, all must pass
npm --prefix web run lint
npm --prefix web run build
```

CI runs the same commands, so a green local run means a green badge.

Two house rules the tests depend on:

- Golden numbers under `sample_data/golden/` are worked out by a person. Never
  derive one with AI, and never copy one back out of the tool's own output. A
  test written from the code's current answer only proves the code agrees with
  itself.
- The core library stays pandas-only. A web dependency belongs in the `web`
  extra, and scikit-learn in `forecast`.

Add an ADR when a change closes off an alternative someone could reasonably
have picked, and write down what you rejected as well as what you chose.

## Response time

Days to weeks. If a pull request goes quiet, it is not a verdict on your work.
