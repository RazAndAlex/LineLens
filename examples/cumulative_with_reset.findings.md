# LineLens report

_10 rows · 6 columns_

_0 error · 2 warning · 0 info_


### [WARNING] 1 reset(s) detected in counter 'parts_total' `(PROBABLE_COUNTER_RESET)`
1 endorsed reset(s) in cumulative counter 'parts_total'. Cause(s): anomalous_decrease. Affected rows are the post-drop readings.
- affected rows: 6
- signal: parts_total
- suspected cause: anomalous_decrease
- confidence: 0.6756

### [WARNING] Summing cumulative counter 'parts_total' overstates its total `(CUMULATIVE_TOTALIZER_SUMMED)`
A dashboard that sums 'parts_total' would show 235, but it is a cumulative totalizer whose honest period increase is 75 (last - first, plus resets). Summing a running total double-counts.
- affected rows: —
- signal: parts_total
- observed: 235
- calculated: 75
- suspected cause: cumulative_totalizer_summed
- confidence: 0.6756
