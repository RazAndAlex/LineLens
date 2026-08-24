"""M9 preview & map wiring tests (app.py section 1, ADR-0010 decision 9).

The auto-first redesign's pure seams: the conflict-free silent auto-map
(``_auto_roles``), the counter preselection (``_auto_counters``), the
single-machine picker hiding (``_single_machine_col``), and the plain-words
summary sentence (``_preview_summary``). The gate behavior — expander reveals
the dropdowns, Analyze needs zero decisions — is browser-verified
(.scratch/m9/p5_preview_check.py).
"""
from __future__ import annotations

from pathlib import Path

import app
from linelens import ingestion, schema, validation
from linelens.models import CanonicalRole

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FICTIONAL_6MONTH = _REPO_ROOT / "sample_data" / "fictional_6month.csv"


def _load():
    return ingestion.load_csv(_FICTIONAL_6MONTH)


# --- _auto_roles: conflict-free silent map ------------------------------------


def test_auto_roles_resolves_conflicts_by_confidence():
    suggestions = {
        "good": (CanonicalRole.GOOD_COUNT, 0.7),        # keyword substring
        "good_count": (CanonicalRole.GOOD_COUNT, 1.0),  # exact match wins
        "state": (CanonicalRole.STATE, 1.0),
    }
    roles = app._auto_roles(suggestions)
    assert roles[CanonicalRole.GOOD_COUNT] == "good_count"
    assert roles[CanonicalRole.STATE] == "state"
    assert len(roles) == 2  # conflict-free: one column per role


def test_auto_roles_skips_none_suggestions():
    assert app._auto_roles({"mystery": (None, 0.0)}) == {}


# --- _auto_counters: numeric leftovers, not role-mapped measures ----------------


def test_auto_counters_excludes_role_mapped_numerics():
    _raw, profile = _load()
    roles = app._auto_roles(
        {c: (r, 1.0) for c, r in
         [("good_count", CanonicalRole.GOOD_COUNT),
          ("reject_count", CanonicalRole.REJECT_COUNT),
          ("duration_seconds", CanonicalRole.DURATION),
          ("speed_target", CanonicalRole.SPEED_TARGET),
          ("speed_actual", CanonicalRole.SPEED_ACTUAL)]}
    )
    # the fictional file's numerics are all role-mapped measures -> nothing left
    assert app._auto_counters(profile, roles) == []
    # drop one mapping -> that numeric column becomes a counter candidate
    del roles[CanonicalRole.SPEED_ACTUAL]
    assert app._auto_counters(profile, roles) == ["speed_actual"]


# --- _single_machine_col: hide the picker for single-machine files --------------


def test_single_machine_col_detects_one_machine():
    raw, _profile = _load()
    roles = {CanonicalRole.MACHINE_ID: "machine_id"}
    assert app._single_machine_col(raw, roles) == "machine_id"
    multi = raw.copy()
    multi.loc[multi.index[:10], "machine_id"] = "M02"
    assert app._single_machine_col(multi, roles) is None
    assert app._single_machine_col(raw, {}) is None  # no machine role mapped


# --- _preview_summary: plain words, honest about the unrecognized ---------------


def test_preview_summary_states_rows_span_machines_recipes_roles():
    raw, profile = _load()
    roles = app._auto_roles(schema.suggest_roles(profile.columns))
    text = app._preview_summary(raw, profile, roles)
    assert f"{profile.row_count:,} rows" in text
    assert "2026-06-23 → 2026-12-19" in text and "(180 days)" in text
    assert "1 machine (M01)" in text
    assert "2 recipes" in text
    assert "Recognized:" in text and "good_count" in text
    # every fictional column is recognized -> no honest "not recognized" tail
    assert "Not recognized" not in text


def test_preview_summary_names_unrecognized_columns():
    raw, profile = _load()
    roles = {CanonicalRole.STATE: "state"}  # nearly nothing recognized
    text = app._preview_summary(raw, profile, roles)
    assert "Not recognized: machine_id" in text
    assert "ignored" in text


# --- color-by-message helpers (ADR-0010 decision 10) ---------------------------


def test_loss_color_map_tiers_by_cumulative_impact():
    # 3 unplanned causes: 60 / 30 / 10 -> vital few (60) strong, middle (30)
    # base, tail (10) deep. A planned cause is always neutral.
    cmap = app._loss_color_map(
        ["A", "B", "C", "Planned"], [60.0, 30.0, 10.0, 50.0], {"Planned"})
    assert cmap["A"] == app._LOSS_STRONG
    assert cmap["B"] == app._DOWN
    assert cmap["C"] == app._LOSS_DEEP
    assert cmap["Planned"] == app._INK_MUTED


def test_loss_color_map_all_small_shares_start_strong():
    # many tiny causes: the first (biggest) still opens the strong tier
    cmap = app._loss_color_map(["x", "y", "z"], [3.0, 2.0, 1.0], set())
    assert cmap["x"] == app._LOSS_STRONG
    assert cmap["z"] == app._LOSS_DEEP  # past the 80% split


def test_planned_causes_reads_the_planned_flag():
    raw, profile = _load()
    sug = schema.suggest_roles(profile.columns)
    ctx = validation.make_context(
        raw, profile, schema.build_mapping({r: c for c, (r, _x) in sug.items()}))
    planned = app._planned_causes(ctx)
    assert planned == {"Changeover", "Maintenance"}
