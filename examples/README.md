# Example reports

Reports that LineLens produced against the synthetic datasets in
[`../sample_data/`](../sample_data). They are committed so that you can read
what the tool outputs without installing it or running anything.

| Example | Dataset | What it shows |
|---|---|---|
| [`totalizer_summed.findings.md`](totalizer_summed.findings.md) | `golden/totalizer_summed.csv` | **The headline case.** A dashboard sums a cumulative idle-time totalizer instead of differencing it. **87,000 naive against 24,000 honest.** The contrast is the diagnosis. |
| [`cumulative_with_reset.findings.md`](cumulative_with_reset.findings.md) | `golden/cumulative_with_reset.csv` | A cumulative parts totalizer with one reset. It produces a `PROBABLE_COUNTER_RESET` finding at row 6, and the **235 naive against 75 honest** contrast. |
| [`valid_event.findings.md`](valid_event.findings.md) | `valid_event.csv` | The clean case. State, production and downtime totals, and **"No problems detected."** |

Each `.findings.md` is the report a person reads. The matching `.findings.json`
is the same findings as structured data, carrying `schema_version: "1.0"` so
another program can consume it.

`linelens.reporting` writes both. Nothing here is hand-edited, and no model is
involved at any point. The reports are deterministic: the same CSV and the same
mapping always produce the same file.

## Keeping them current

These files are a snapshot. There is no one-command regeneration script and no
test that re-renders them, so a change to `linelens.reporting` can leave them
stale without anything failing.

To refresh one, run the tool against the dataset in the table above and export
the findings from the Export section, then replace the file here.
