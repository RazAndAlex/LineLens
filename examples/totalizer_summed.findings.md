# LineLens report

_10 rows · 5 columns_

_0 error · 1 warning · 0 info_


### [WARNING] Summing cumulative counter 'idle_seconds_total' overstates its total `(CUMULATIVE_TOTALIZER_SUMMED)`
A dashboard that sums 'idle_seconds_total' would show 87000, but it is a cumulative totalizer whose honest period increase is 24000 (last - first, plus resets). Summing a running total double-counts.
- affected rows: —
- signal: idle_seconds_total
- observed: 87000
- calculated: 24000
- suspected cause: cumulative_totalizer_summed
- confidence: 0.4205
