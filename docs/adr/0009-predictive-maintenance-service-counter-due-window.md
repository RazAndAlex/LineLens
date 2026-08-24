# Predictive maintenance: service counter + learned due window

## Status

Accepted (2026-07-24, M9 grilling). **Re-opens ADR-0007's non-goal** ("RUL /
breakage prediction needs labeled failures. MTBF-from-Faults is the honest
ceiling"). With `Maintenance` added to the schema, the CSV *does* carry
labeled service events, so a learned maintenance forecast becomes honest.
ADR-0001 (single ingest path) stands. ADR-0007's always-band ethic is
extended, not weakened.

## Context

The user's vision: a car-style service counter (bottles since last service)
plus a "you should do maintenance around this window" forecast learned from
the line's own history. Including "when it broke and they had to fix."
ADR-0007 had ruled this out because the interval CSV carried no maintenance
events and no degradation sensor. Five decisions were resolved by grilling:

1. **Where does the service signal come from?** Inferring maintenance from
   proxies (long stops, performance resets) was rejected. The model would
   learn from guesses, against "the computer does the math." Ingesting the
   machine's `CntMaintenance*` snapshot counters was rejected. It reopens
   ADR-0001's single-ingest-path for one feature. Chosen: **`Maintenance` as
   the 8th stop cause** (always `planned`), planted by the generator. A real
   labeled signal inside the interval grain.
2. **What is the odometer?** Calendar time and run-hours were rejected
   (hours pass while the line sits powered-down, accruing no wear). Chosen:
   **bottles produced.** The truest analogue of a car's kilometers, and it
   matches the machine's own `Bottles_Counter`.
3. **What resets the counter?** Chosen: `Maintenance` stops **and**
   repair-length Faults (corrective service. "it broke and they fixed it"
   genuinely refreshes the machine). The duration threshold separating
   routine faults from the repair tail is learned from the data. Partial
   (minimal-repair) resets rejected: unverifiable from one CSV.
4. **Cadence-only or condition-adjusted?** Chosen: learned **service
   interval** (median + spread of bottles-between-services) counted down by
   the **service counter**, pulled **earlier only** when condition signals
   (fault-rate trend, Performance degradation. Already forecast in
   Reliability) worsen, with the reason always stated. Cadence-only would say
   "due in 3 weeks" while faults accelerate.
5. **Thin data?** The service counter always renders (pure arithmetic). The
   due window appears only with ≥ 2 service events. Otherwise the tile says
   "not enough service history." A default/industry interval was rejected.
   An invented number violates the tool's identity.

## Decision

Build `linelens/maintenance.py` as a pure core (same contract as
`compute_oee` / `whatif.perturb`): service events → service counter → learned
service interval → condition-adjusted **due window**, always a band (median +
spread), never a bare date. The UI renders it in the final act alongside
Reliability (ADR-0010), since the condition adjustment consumes the
Performance-degradation forecast.

## Consequences

- `CONTEXT.md` gains **service counter**, **service interval**, **due
  window**. The stop-cause family list gains **Maintenance**.
- The generator plants `Maintenance` stops + repair-length Faults in
  `fictional_6month.csv`. `fictional_month.csv` stays byte-identical. The M8
  forecast oracles (beats-linear, conformal coverage) must re-pass after
  regeneration. Re-baseline numbers, never weaken gates.
- The known ceiling moves but does not vanish: the model learns *this line's
  service rhythm*, not component physics. A regime change (new recipe, new
  maintenance policy) breaks the learned interval. Same exchangeability
  caveat as ADR-0007's conformal band.
- Snapshot-based `CntMaintenance*` ingestion remains the named upgrade path
  if the real one-week export proves the inferred signal wrong.
