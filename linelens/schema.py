"""Schema mapping: canonical roles, column mapping, coercion, and suggestions."""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

import pandas as pd

from .models import CanonicalRole, ColumnMapping

# ponytail: the time axis is the one thing every downstream analysis needs.
# Keep the default required set minimal; callers pass more when they need to.
DEFAULT_REQUIRED: tuple[CanonicalRole, ...] = (CanonicalRole.TIMESTAMP_START,)

_DATETIME_ROLES: tuple[CanonicalRole, ...] = (
    CanonicalRole.TIMESTAMP_START,
    CanonicalRole.TIMESTAMP_END,
)
_NUMERIC_ROLES: tuple[CanonicalRole, ...] = (
    CanonicalRole.DURATION,
    CanonicalRole.GOOD_COUNT,
    CanonicalRole.REJECT_COUNT,
    CanonicalRole.SPEED_TARGET,
    CanonicalRole.SPEED_ACTUAL,
)

# v2.5: bool columns (the `planned` flag) are a new coercion path — the existing
# machinery only handled datetime + numeric. True/False/truthy strings -> bool.
_BOOL_ROLES: tuple[CanonicalRole, ...] = (CanonicalRole.PLANNED,)


def build_mapping(
    roles: dict[CanonicalRole, str], counters: Iterable[str] = ()
) -> ColumnMapping:
    """Build a ColumnMapping from a role -> source column name dict.

    `counters` are source columns the user wants analyzed as counters (M4); they
    are arbitrary numeric columns, distinct from the fixed roles.
    """
    return ColumnMapping(roles=dict(roles), counters=tuple(counters))


def validate_mapping(
    mapping: ColumnMapping,
    columns: Iterable[str],
    required: tuple[CanonicalRole, ...] = DEFAULT_REQUIRED,
) -> list[str]:
    """Return human-readable problems with a mapping against the given columns.

    Detects: required roles not mapped, source columns absent from the dataset,
    and one source column claimed by multiple roles. Returns [] when clean.
    """
    present = set(columns)
    problems: list[str] = []

    for role in mapping.missing_required(required):
        problems.append(f"required role {role.value} is not mapped to any column")

    for role, source in mapping.roles.items():
        if source not in present:
            problems.append(f"role {role.value} maps to missing column {source!r}")

    claimed: dict[str, list[CanonicalRole]] = {}
    for role, source in mapping.roles.items():
        claimed.setdefault(source, []).append(role)
    for source, roles in claimed.items():
        if len(roles) > 1:
            names = ", ".join(role.value for role in roles)
            problems.append(f"column {source!r} is mapped to multiple roles: {names}")

    for source in mapping.counters:
        if source not in present:
            problems.append(f"counter column {source!r} is absent from the dataset")

    return problems


@dataclass(frozen=True)
class ColumnCoercion:
    """Result of coercing one mapped column to its target type."""

    role: CanonicalRole
    source: str
    target: str  # "datetime" | "numeric" | "bool"
    failed_rows: tuple[int, ...]  # 1-based source rows that could not be coerced


def coerce(
    mapping: ColumnMapping, df: pd.DataFrame
) -> tuple[pd.DataFrame, tuple[ColumnCoercion, ...]]:
    """Coerce mapped datetime/numeric columns on a copy of df.

    Returns (coerced_df, report). The report lists, per mapped coercible column,
    the 1-based source rows that had a value but could not be parsed. These are
    not Findings yet (M3 wraps them); they are structured facts only.
    """
    out = df.copy()
    reports: list[ColumnCoercion] = []
    for role in _DATETIME_ROLES:
        src = mapping.source_for(role)
        if not src or src not in out.columns:
            continue
        parsed = pd.to_datetime(out[src], format="mixed", errors="coerce")
        reports.append(
            ColumnCoercion(role, src, "datetime", _failed_rows(out[src], parsed))
        )
        out[src] = parsed
    for role in _NUMERIC_ROLES:
        src = mapping.source_for(role)
        if not src or src not in out.columns:
            continue
        parsed = pd.to_numeric(out[src], errors="coerce")
        reports.append(
            ColumnCoercion(role, src, "numeric", _failed_rows(out[src], parsed))
        )
        out[src] = parsed
    for role in _BOOL_ROLES:
        src = mapping.source_for(role)
        if not src or src not in out.columns:
            continue
        parsed = _to_bool(out[src])
        reports.append(
            ColumnCoercion(role, src, "bool", _failed_rows(out[src], parsed))
        )
        out[src] = parsed
    return out, tuple(reports)


def _failed_rows(original: pd.Series, parsed: pd.Series) -> tuple[int, ...]:
    # Rows where a value existed but could not be coerced (now NaT/NaN).
    # ponytail: assumes input row order reflects source order (true for a freshly
    # loaded CSV); 1-based with the header as row 1, so positional i -> i + 2.
    mask = parsed.isna() & original.notna()
    return tuple(i + 2 for i, keep in enumerate(mask) if keep)


# Strings that mean True / False for the `planned` flag. Kept conservative so a
# stray product code or note is reported as unparseable rather than silently
# coerced to a boolean. NA stays NA (a blank planned flag is not an error).
_BOOL_TRUE = frozenset({"true", "t", "yes", "y", "1", "planned"})
_BOOL_FALSE = frozenset({"false", "f", "no", "n", "0", "unplanned"})


def _to_bool(series: pd.Series) -> pd.Series:
    """Coerce a column to nullable boolean; unparseable values become NA.

    Accepts common truthy/falsy spellings (true/false/yes/no/1/0, plus
    planned/unplanned). Anything else with a value -> NA, which _failed_rows
    flags. Returns a pandas nullable boolean (`boolean` dtype), not python bool,
    so NA survives.
    """
    lowered = series.astype("string").str.strip().str.lower()
    truthy = lowered.isin(_BOOL_TRUE)
    falsy = lowered.isin(_BOOL_FALSE)
    # Start from the existing (string) values masked to NA, then a nullable bool
    # array where nothing has been decided yet. Build via a Series so length and
    # index line up regardless of the input dtype.
    result = pd.array([pd.NA] * len(series), dtype="boolean")
    truthy_mask = truthy.values
    falsy_mask = falsy.values
    result[truthy_mask] = True
    result[falsy_mask] = False
    return pd.Series(result, index=series.index, name=series.name)


SUGGEST_MIN_CONFIDENCE = 0.7

_ROLE_KEYWORDS: dict[CanonicalRole, tuple[str, ...]] = {
    CanonicalRole.MACHINE_ID: ("machineid", "machine", "asset", "equipment", "lineid"),
    CanonicalRole.TIMESTAMP_START: ("timestampstart", "starttime", "begin"),
    CanonicalRole.TIMESTAMP_END: ("timestampend", "endtime", "finish"),
    CanonicalRole.STATE: ("machinestate", "state", "status", "mode"),
    CanonicalRole.MACHINE_ID: ("machineid", "machine", "asset", "equipment", "lineid"),
    CanonicalRole.TIMESTAMP_START: ("timestampstart", "starttime", "begin"),
    CanonicalRole.TIMESTAMP_END: ("timestampend", "endtime", "finish"),
    CanonicalRole.STATE: ("machinestate", "state", "status", "mode"),
    CanonicalRole.STOP_CAUSE: ("stopcause", "downtimecause", "almfamily", "alarmfamily", "reason", "fault"),
    CanonicalRole.SHIFT: ("shift", "shiftid"),
    CanonicalRole.RECIPE: ("rcprn", "recipe", "product", "productname"),
    CanonicalRole.SPEED_TARGET: ("speedtarget", "targetspeed", "target"),
    CanonicalRole.SPEED_ACTUAL: ("speedactual", "actualspeed", "actual"),
    CanonicalRole.PLANNED: ("planned", "scheduled", "plannedstop", "isplanned"),
    CanonicalRole.DURATION: ("durationseconds", "duration", "dwell"),
    CanonicalRole.GOOD_COUNT: ("goodcount", "good", "produced", "okcount"),
    CanonicalRole.REJECT_COUNT: ("rejectcount", "reject", "scrap", "badcount"),
}


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _score(name_norm: str, keyword: str) -> float:
    if name_norm == keyword:
        return 1.0
    if len(keyword) >= 4 and keyword in name_norm:
        return 0.7
    return 0.0


def suggest_roles(columns: Iterable[str]) -> dict[str, tuple[CanonicalRole, float]]:
    """Suggest a best-fit role per source column, with confidence in [0.7, 1.0].

    Returns {source_column: (role, confidence)} only for columns whose best
    keyword score >= SUGGEST_MIN_CONFIDENCE. These are per-column hints, not a
    conflict-free mapping; run validate_mapping before trusting them.
    """
    suggestions: dict[str, tuple[CanonicalRole, float]] = {}
    for col in columns:
        norm = _normalize(col)
        best_role: CanonicalRole | None = None
        best_score = 0.0
        for role, keywords in _ROLE_KEYWORDS.items():
            for keyword in keywords:
                score = _score(norm, keyword)
                if score > best_score:
                    best_role, best_score = role, score
        if best_role is not None and best_score >= SUGGEST_MIN_CONFIDENCE:
            suggestions[col] = (best_role, best_score)
    return suggestions
