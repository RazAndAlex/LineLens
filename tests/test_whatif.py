"""M6 what-if tests — hand-computed oracles (ADR-0005).

The what-if (``linelens.whatif``) cuts a stop cause's unplanned downtime by a
fraction ``r`` and re-runs the pure ``compute_oee`` core on the rebuilt arrays.
ADR-0005 pins the freed-time model: the freed seconds become run time at the
line's current effective speed, so **Performance and Quality are held exactly**
while Availability / OEE / good / bottles-lost move. These tests are the
hand-computed oracle for that arithmetic — every expected value is derived from
the published M4 fixture constants (the same ones ``tests/test_oee.py`` pins),
independently of ``whatif.perturb``'s implementation.

The suite stays free of the ``ui`` extra (pyproject): ``perturb`` is a pure
function of per-row arrays + a ``{cause: r}`` map, mirroring ``compute_oee``.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from linelens import ingestion, schema, validation
from linelens.oee import compute_oee
from linelens.whatif import perturb, spread_recovered, whatif_from_context

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FICTIONAL_MONTH = _REPO_ROOT / "sample_data" / "fictional_month.csv"

# Fixture A — first 6 rows of fictional_month.csv (M4 spec). Single recipe,
# target 2200 bottles/hr, no Idle, all unplanned. Constants published in
# tests/test_oee.py and .scratch/m4/spec.md.
_COLS = [
    "state", "stop_cause", "speed_target", "speed_actual",
    "duration_seconds", "good_count", "reject_count", "planned",
]
_A_ROWS = [
    ("Stopped", "Starvation", 2200, 0, 517, 0, 0, False),
    ("Running", None, 2200, 2017, 3241, 1816, 7, False),
    ("Running", None, 2200, 2043, 2043, 1159, 4, False),
    ("Running", None, 2200, 2086, 1321, 765, 3, False),
    ("Stopped", "Fault", 2200, 0, 368, 0, 0, False),
    ("Stopped", "Supplies", 2200, 0, 162, 0, 0, False),
]
# Derived baseline constants (the oracle's source of truth).
_A_RUN = 6605
_A_UNPLANNED = 1047              # Starvation 517 + Fault 368 + Supplies 162
_A_GOOD = 3740
_A_REJECT = 14
_A_PERF_NUM = 13466552           # 2017·3241 + 2043·2043 + 2086·1321
_A_PERF_DEN = 14531000           # 2200·6605
_A_DENOM = _A_RUN + _A_UNPLANNED  # + idle(0) = 7652
_A_P = _A_PERF_NUM / _A_PERF_DEN
_A_Q = _A_GOOD / (_A_GOOD + _A_REJECT)
_A_STARVATION_BOTTLES = 517 * 2200 / 3600
_A_FAULT_BOTTLES = 368 * 2200 / 3600
_A_SUPPLIES_BOTTLES = 162 * 2200 / 3600


def _arrays(rows, planned_col=True):
    df = pd.DataFrame(rows, columns=_COLS)
    planned = df["planned"] if planned_col else None
    return dict(
        state=df["state"], stop_cause=df["stop_cause"], duration=df["duration_seconds"],
        planned=planned, speed_target=df["speed_target"], speed_actual=df["speed_actual"],
        good=df["good_count"], reject=df["reject_count"],
    )


def _a_arrays():
    return _arrays(_A_ROWS)


def _bottles_by_cause(oee):
    return {b.cause: b.bottles for b in oee.bottles_lost}


# --- Oracle 1: cut Starvation 100% — A rises, P/Q held, Starvation gone ----


def test_cut_starvation_fully_raises_availability_holds_p_and_q():
    base = compute_oee(**_a_arrays())
    freed = 517.0
    hypo = perturb(**_a_arrays(), reductions={"Starvation": 1.0})

    # Availability: freed time moved unplanned -> run, denominator invariant.
    assert hypo.availability == pytest.approx((_A_RUN + freed) / _A_DENOM)
    # Performance and Quality held to the last digit (ADR-0005 decision 2).
    assert hypo.performance == pytest.approx(_A_P, abs=1e-12)
    assert hypo.quality == pytest.approx(_A_Q, abs=1e-12)
    # OEE = A_new · P · Q (P/Q held -> OEE tracks Availability exactly).
    assert hypo.oee == pytest.approx((_A_RUN + freed) / _A_DENOM * _A_P * _A_Q)
    # Time breakdown: run absorbed the freed seconds, unplanned shed them.
    assert hypo.run_time == pytest.approx(_A_RUN + freed)
    assert hypo.unplanned_stop_time == pytest.approx(_A_UNPLANNED - freed)
    assert hypo.idle_time == pytest.approx(0.0)
    # Good rises by the freed time's output at the line's effective speed,
    # split at the baseline quality ratio (Q held -> good/reject ratio fixed).
    actual_eff = _A_PERF_NUM / _A_RUN
    parts_added = freed * actual_eff / 3600
    assert hypo.good == pytest.approx(_A_GOOD + parts_added * _A_Q)
    # Starvation fully recovered: absent from bottles_lost; others unchanged.
    bl = _bottles_by_cause(hypo)
    assert "Starvation" not in bl
    assert bl["Fault"] == pytest.approx(_A_FAULT_BOTTLES)
    assert bl["Supplies"] == pytest.approx(_A_SUPPLIES_BOTTLES)
    # ranking re-sorts with Starvation gone: Fault > Supplies
    assert [b.cause for b in hypo.bottles_lost] == ["Fault", "Supplies"]


# --- Oracle 2: cut Starvation 50% — linear recovery, ranking re-sorts -------


def test_cut_starvation_half_recovers_linearly_and_reranks():
    freed = 258.5  # 0.5 · 517
    hypo = perturb(**_a_arrays(), reductions={"Starvation": 0.5})
    assert hypo.availability == pytest.approx((_A_RUN + freed) / _A_DENOM)
    assert hypo.performance == pytest.approx(_A_P, abs=1e-12)
    assert hypo.quality == pytest.approx(_A_Q, abs=1e-12)
    bl = _bottles_by_cause(hypo)
    # exactly half the Starvation bottles recovered; others untouched
    assert bl["Starvation"] == pytest.approx(_A_STARVATION_BOTTLES * 0.5)
    assert bl["Fault"] == pytest.approx(_A_FAULT_BOTTLES)
    assert bl["Supplies"] == pytest.approx(_A_SUPPLIES_BOTTLES)
    # Starvation (157.9) now sits below Fault (224.9): ranking re-sorts
    assert [b.cause for b in hypo.bottles_lost] == ["Fault", "Starvation", "Supplies"]


# --- Oracle 3: cut two causes at once — freed time sums, both drop out ------


def test_cut_two_causes_sums_freed_time():
    freed = 368 + 162  # Fault + Supplies at 100%
    hypo = perturb(**_a_arrays(), reductions={"Fault": 1.0, "Supplies": 1.0})
    assert hypo.availability == pytest.approx((_A_RUN + freed) / _A_DENOM)
    assert hypo.performance == pytest.approx(_A_P, abs=1e-12)
    assert hypo.run_time == pytest.approx(_A_RUN + freed)
    # only Starvation remains priced
    assert [b.cause for b in hypo.bottles_lost] == ["Starvation"]
    assert _bottles_by_cause(hypo)["Starvation"] == pytest.approx(_A_STARVATION_BOTTLES)


# --- Oracle 4: no reductions -> identical to the baseline (sanity) ----------


def test_empty_reductions_returns_baseline():
    base = compute_oee(**_a_arrays())
    hypo = perturb(**_a_arrays(), reductions={})
    for field in ("availability", "performance", "quality", "oee",
                  "run_time", "unplanned_stop_time", "idle_time", "good", "reject"):
        assert getattr(hypo, field) == pytest.approx(getattr(base, field))
    assert _bottles_by_cause(hypo) == pytest.approx(_bottles_by_cause(base), rel=1e-9)
    assert [b.cause for b in hypo.bottles_lost] == [b.cause for b in base.bottles_lost]


# --- Oracle 5: reduction on an absent cause is a no-op, not a crash ---------


def test_reduction_on_absent_cause_is_noop():
    base = compute_oee(**_a_arrays())
    hypo = perturb(**_a_arrays(), reductions={"External": 1.0})  # not in fixture A
    assert hypo.availability == pytest.approx(base.availability)
    assert _bottles_by_cause(hypo) == pytest.approx(_bottles_by_cause(base), rel=1e-9)


# --- Oracle 6: planned Changeover is never a lever (ADR-0003/0005) ----------


def _b_arrays():
    # Fixture B (M4 spec): exercises Idle-in-denominator + planned Changeover.
    rows = [
        ("Running", None, 2400, 2400, 3600, 2400, 0, False),
        ("Running", None, 2400, 1800, 3600, 1800, 100, False),
        ("Idle", None, 2400, 0, 600, 0, 0, False),
        ("Stopped", "Changeover", 2400, 0, 1800, 0, 0, True),
        ("Stopped", "Starvation", 2400, 0, 900, 0, 0, False),
    ]
    return _arrays(rows)


def test_planned_changeover_cannot_be_levered():
    base = compute_oee(**_b_arrays())
    # Changeover is planned -> no unplanned rows to scale -> no-op.
    hypo = perturb(**_b_arrays(), reductions={"Changeover": 1.0})
    assert hypo.availability == pytest.approx(base.availability)
    assert _bottles_by_cause(hypo) == pytest.approx(_bottles_by_cause(base), rel=1e-9)
    # Changeover is absent from bottles_lost either way (priced as unplanned: never).
    assert "Changeover" not in _bottles_by_cause(base)
    assert "Changeover" not in _bottles_by_cause(hypo)


def test_cut_starvation_in_fixture_b_uses_strict_idle_denominator():
    # freed 900s of Starvation: run 7200->8100, unplanned 900->0, idle 600 stays.
    # Strict OEE keeps Idle in the denominator (ADR-0003), so A = 8100/8700.
    hypo = perturb(**_b_arrays(), reductions={"Starvation": 1.0})
    assert hypo.availability == pytest.approx(8100 / 8700)
    assert hypo.run_time == pytest.approx(8100.0)
    assert hypo.unplanned_stop_time == pytest.approx(0.0)
    assert hypo.idle_time == pytest.approx(600.0)
    assert hypo.bottles_lost == ()  # only unplanned cause was Starvation, now gone


# --- Oracle 7: reduction clamps to [0, 1]; values outside are bounded -------


def test_reduction_is_clamped_to_unit_interval():
    # r > 1 behaves like r = 1 (can't recover more than all of a cause's downtime).
    full = perturb(**_a_arrays(), reductions={"Starvation": 1.0})
    over = perturb(**_a_arrays(), reductions={"Starvation": 2.5})
    assert over.availability == pytest.approx(full.availability)
    assert over.run_time == pytest.approx(full.run_time)
    # r < 0 behaves like r = 0 (a negative cut can't add downtime here).
    none = perturb(**_a_arrays(), reductions={"Starvation": -0.3})
    base = compute_oee(**_a_arrays())
    assert none.availability == pytest.approx(base.availability)


# --- End-to-end on the real dataset via the context wrapper ------------------


def _ctx_for(csv_path: Path):
    raw, profile = ingestion.load_csv(csv_path)
    sug = schema.suggest_roles(profile.columns)
    role_to_col = {role: col for col, (role, _conf) in sug.items()}
    mapping = schema.build_mapping(role_to_col)
    return validation.make_context(raw, profile, mapping)


def test_whatif_from_context_none_without_time_basis():
    # No duration axis and no STATE mapped -> the wrapper mirrors
    # oee_from_context and returns None (the KPIs are time/state-based).
    raw, profile = ingestion.load_csv(_FICTIONAL_MONTH)
    ctx = validation.make_context(raw, profile, schema.build_mapping({}))
    assert whatif_from_context(ctx, {"Starvation": 1.0}) is None


def test_whatif_from_context_on_fictional_month_starvation_full():
    ctx = _ctx_for(_FICTIONAL_MONTH)
    from linelens.oee import oee_from_context
    base = oee_from_context(ctx)
    assert base is not None
    base_bl = _bottles_by_cause(base)
    starvation_secs = next(b.seconds_lost for b in base.bottles_lost if b.cause == "Starvation")

    hypo = whatif_from_context(ctx, {"Starvation": 1.0})
    assert hypo is not None
    # Availability rises by exactly the freed Starvation time over the invariant
    # denominator (freed moves unplanned -> run; ADR-0005 identity).
    denom = base.run_time + base.unplanned_stop_time + base.idle_time
    assert hypo.availability == pytest.approx((base.run_time + starvation_secs) / denom)
    # OEE tracks Availability (P/Q held).
    assert hypo.oee == pytest.approx(
        (base.run_time + starvation_secs) / denom * base.performance * base.quality
    )
    # Starvation fully recovered; total bottles-lost drops by exactly that amount.
    hypo_bl = _bottles_by_cause(hypo)
    assert hypo_bl.get("Starvation", 0.0) == pytest.approx(0.0, abs=1e-6)
    recovered = sum(base_bl.values()) - sum(hypo_bl.values())
    assert recovered == pytest.approx(base_bl["Starvation"], rel=1e-6)


def test_whatif_baseline_matches_oee_baseline():
    # The wrapper with no reductions must reproduce oee_from_context exactly —
    # the single-source-of-truth guarantee from the shared _arrays_from_context.
    ctx = _ctx_for(_FICTIONAL_MONTH)
    from linelens.oee import oee_from_context
    base = oee_from_context(ctx)
    hypo = whatif_from_context(ctx, {})
    assert base is not None and hypo is not None
    for field in ("availability", "performance", "quality", "oee",
                  "run_time", "unplanned_stop_time", "good", "reject"):
        assert getattr(hypo, field) == pytest.approx(getattr(base, field))
    assert [b.cause for b in hypo.bottles_lost] == [b.cause for b in base.bottles_lost]


# --- spread_recovered: proportional to forecast level (M8 node 4) -----------
# Pure oracle: out[d] = v[d] + recovered · v[d] / Σv, summing addends to exactly
# `recovered` (the bridge invariant the lever waterfall also relies on). Honest
# fallbacks for the empty / zero-level / zero-recovered edges so the helper
# never divides by zero and the zero-slider coincides with the forecast.


def test_spread_proportional_to_forecast_level():
    # Each day's bump is its share of the forecast level: 100/600, 200/600, 300/600.
    out = spread_recovered([100.0, 200.0, 300.0], 60.0)
    assert out == pytest.approx([110.0, 220.0, 330.0])


def test_spread_addends_sum_to_recovered():
    # The bridge invariant: Σ(out) − Σ(horizon) == recovered, across inputs.
    for horizon, recovered in [
        ([100.0, 200.0, 300.0], 60.0),
        ([1000.0, 800.0, 200.0, 500.0], 12_500.0),
        ([20_000.0, 21_000.0, 19_500.0], 0.0),
    ]:
        out = spread_recovered(horizon, recovered)
        assert sum(out) - sum(horizon) == pytest.approx(recovered, abs=1e-9)


def test_spread_recovered_zero_returns_horizon_unchanged():
    # Zero-slider: the what-if line coincides with the forecast (the baseline view).
    horizon = [21_000.0, 19_800.0, 20_400.0]
    assert spread_recovered(horizon, 0.0) == pytest.approx(horizon)


def test_spread_empty_horizon_returns_empty():
    assert spread_recovered([], 100.0) == []


def test_spread_zero_sum_horizon_falls_back_to_flat():
    # A zero-level forecast can't be proportioned -> distribute flatly, still
    # summing to recovered so the bridge invariant holds.
    out = spread_recovered([0.0, 0.0, 0.0], 30.0)
    assert out == pytest.approx([10.0, 10.0, 10.0])
    assert sum(out) == pytest.approx(30.0)


def test_spread_keeps_negative_levels_unclamped():
    # The output is the forecast plus a non-negative addend, so it goes negative
    # only when the forecast does — the honest "unsustainable trend" signal
    # ADR-0006 forbids hiding. Clipping would break the exact bridge invariant.
    horizon = [-50.0, 100.0, 150.0]
    out = spread_recovered(horizon, 30.0)
    assert sum(out) - sum(horizon) == pytest.approx(30.0, abs=1e-9)
    # the addend on the negative day is itself negative (proportional to its
    # negative level) — the line dips further, not clipped to zero.
    assert out[0] < horizon[0]


def test_spread_accepts_tuple_forecast_slice():
    # forecast_ml / forecast return tuples for their central series slices; the
    # helper must coerce, since the future-line chart passes whatever they emit.
    out = spread_recovered((100.0, 200.0, 300.0), 60.0)
    assert out == pytest.approx([110.0, 220.0, 330.0])
    assert isinstance(out, list)
