"""Core data models for LineLens."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class CanonicalRole(Enum):
    """Canonical internal field roles a source column can be mapped to."""

    MACHINE_ID = "machine_id"
    TIMESTAMP_START = "timestamp_start"
    TIMESTAMP_END = "timestamp_end"
    STATE = "state"
    STOP_CAUSE = "stop_cause"  # renamed from stop_reason (v2.5) — one of 7 families
    SHIFT = "shift"
    DURATION = "duration_seconds"
    GOOD_COUNT = "good_count"
    REJECT_COUNT = "reject_count"
    # v2.5 enrichments (plan schema): recipe, speeds, planned flag.
    RECIPE = "recipe"  # product being run (e.g. "Lampone Zero 560ml")
    SPEED_TARGET = "speed_target"  # target bottles/hr for the recipe
    SPEED_ACTUAL = "speed_actual"  # actual bottles/hr this interval (0 when not running)
    PLANNED = "planned"  # bool — scheduled stop excluded from Availability


class ParseError(Exception):
    """Raised when a CSV cannot be loaded or parsed."""


@dataclass(frozen=True)
class DatasetProfile:
    """Immutable, JSON-safe summary of a loaded dataset."""

    row_count: int
    columns: tuple[str, ...]
    dtypes: dict[str, str]
    null_counts: dict[str, int]
    head_preview: tuple[tuple[str, ...], ...]

    def to_dict(self) -> dict:
        return {
            "row_count": self.row_count,
            "columns": list(self.columns),
            "dtypes": dict(self.dtypes),
            "null_counts": dict(self.null_counts),
            "head_preview": [list(row) for row in self.head_preview],
        }


@dataclass(frozen=True)
class ColumnMapping:
    """Maps canonical roles to source column names.

    `counters` names the source columns the user wants analyzed as counters --
    any numeric column, not just the fixed roles. Classification (kind,
    confidence) is derived from the data downstream, never asserted here.
    """

    roles: dict[CanonicalRole, str]
    counters: tuple[str, ...] = ()

    def source_for(self, role: CanonicalRole) -> str | None:
        return self.roles.get(role)

    def missing_required(
        self, required: tuple[CanonicalRole, ...]
    ) -> list[CanonicalRole]:
        return [role for role in required if role not in self.roles]


class CounterKind(Enum):
    """How a numeric column behaves as a counter."""

    INSTANTANEOUS = "instantaneous"  # a level (temperature); average, never sum
    INCREMENTAL = "incremental"      # an amount per record; sum is correct
    CUMULATIVE = "cumulative"        # a running total; difference is correct
    UNKNOWN = "unknown"              # can't tell from shape alone


@dataclass(frozen=True)
class CounterColumn:
    """A classified counter column and the evidence behind the call."""

    source_name: str
    kind: CounterKind
    confidence: float
    evidence: dict


class Severity(Enum):
    """Finding severity levels."""

    ERROR = "error"  # data is wrong / a total is impossible
    WARNING = "warning"  # likely wrong, needs a human
    INFO = "info"  # note / handled automatically


@dataclass(frozen=True)
class Finding:
    """A structured diagnostic produced by a validation rule."""

    rule_id: str
    severity: Severity
    title: str
    description: str
    evidence: dict
    affected_rows: tuple[int, ...]  # 1-based source rows
    # optional context
    machine_id: str | None = None
    signal: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    observed_value: float | None = None
    maximum_possible_value: float | None = None
    calculated_value: float | None = None
    suspected_cause: str | None = None  # cause-code string; enum arrives in M4
    confidence: float | None = None  # for inference-based findings
    suggested_action: str | None = None

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "evidence": dict(self.evidence),
            "affected_rows": list(self.affected_rows),
            "machine_id": self.machine_id,
            "signal": self.signal,
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "observed_value": self.observed_value,
            "maximum_possible_value": self.maximum_possible_value,
            "calculated_value": self.calculated_value,
            "suspected_cause": self.suspected_cause,
            "confidence": self.confidence,
            "suggested_action": self.suggested_action,
        }
