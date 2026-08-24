# LineLens v2.5

Notes for coding agents working in this repository. A human reader wants
[README.md](README.md) instead.

## Domain docs

Single context: [`CONTEXT.md`](CONTEXT.md) holds the vocabulary, and
[`docs/adr/`](docs/adr/) holds the decisions. See `docs/agents/domain.md`.

Add an ADR when a choice closes off an alternative someone could reasonably
have taken. Record what was rejected and why, not only what was chosen.

## Issues

Use GitHub Issues. Earlier work tracked issues as markdown files under
`.scratch/<feature>/`, because the project had no remote at the time. That
directory is working scratch and is not published, so some older ADRs cite
probe scripts under `.scratch/` that are not in the repository. Those
citations are a record of how a decision was reached, not a link you can open.

See `docs/agents/issue-tracker.md` for the file-based scheme, which still
applies to any work done offline.

## Triage labels

Five labels, each label string equal to its role name: `needs-triage`,
`needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See
`docs/agents/triage-labels.md`.

## The `ponytail:` comment marker

Around fourteen comments in `linelens/` and `server/` open with `ponytail:`. It
marks a deliberate simplification and records why it was accepted, so that a
later reader can tell a considered limit from an oversight. Example, from
`linelens/ingestion.py`:

    # ponytail: utf-8-sig (handles BOM) then latin-1 covers the vast majority
    # of industrial CSVs without a chardet dependency.

Grep for it to find every known limit in one pass. It is not a TODO. Nothing is
promised, and each one names the condition that would justify revisiting it.

## House rules

Golden numbers under `sample_data/golden/` are worked out by a person and
checked by hand. Never derive one with AI, and never copy one back out of the
tool's own output: the test would then agree with whatever the code currently
does, which is not a test.

The core library stays pandas-only. A web server dependency belongs in the
`web` extra, and scikit-learn belongs in `forecast`.
