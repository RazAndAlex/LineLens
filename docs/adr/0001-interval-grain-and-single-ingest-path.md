# Interval grain with a single ingest path

LineLens v2.5 keeps the **state interval** as its atomic unit (one row = one state interval) and enriches it with the variety of datatypes a real machine produces, recipe, target/actual speed, alarm family, maintenance counters, as per-interval attributes the engine can sum. The real machine's native export is a **tag snapshot** (pre-aggregated period totals, lifetime cumulative counters, already-computed KPIs): a different grain that cannot be summed as intervals without committing the exact odometer error LineLens exists to flag.

We considered adopting the snapshot grain directly, and a hybrid (ingest snapshots, derive intervals), but chose the interval base because the existing validation and totals engine is built around it and the user wanted to build on the current structure. Snapshot ingestion is **out of scope for v2.5**. The real export is reference for column design and realistic sample data, not a directly-loaded input.
