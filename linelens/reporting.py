"""Reporting: deterministic exports of the cleaned data and findings (M6a).

See docs/m6-ui-design.md (approved v1). These are pure serialisation wrappers
over the coerced DataFrame and Finding.to_dict() -- no calculation lives here
("Python calculates the truth"). The findings JSON is versioned and is the
machine-readable artifact the v2.5 model (what-if, forecast) and any downstream
reader consume -- deterministic only, no LLM in the loop.

Dependency direction: sits at the end of the lib arrow (summaries -> reporting);
imports models + validation for types only.
"""
from __future__ import annotations

import csv
import io
import json
from collections import Counter

from .models import DatasetProfile, Finding
from .validation import ValidationContext

# Findings export schema (brief §11: "planned and versioned"). Bump when the
# Finding shape or this blob's top-level structure changes.
FINDINGS_SCHEMA_VERSION = "1.0"


def cleaned_csv(ctx: ValidationContext) -> str:
    """The coerced dataset as CSV (flat cleaned file for Power BI, etc.).

    Timestamps are parsed and numerics typed (ctx.data); the raw frame is never
    mutated. No index column.
    """
    return ctx.data.to_csv(index=False)


def findings_json(
    findings: list[Finding], profile: DatasetProfile | None = None
) -> str:
    """Findings as a versioned JSON blob: {schema_version, generated_for, findings}.

    Order is preserved as given (callers pass the canonical merged order). Output
    is deterministic: sorted keys, stable across runs.
    """
    return json.dumps(
        {
            "schema_version": FINDINGS_SCHEMA_VERSION,
            "generated_for": profile.to_dict() if profile is not None else None,
            "findings": [f.to_dict() for f in findings],
        },
        indent=2,
        sort_keys=True,
        default=str,
    )


def findings_csv(findings: list[Finding]) -> str:
    """Findings as one CSV row per finding, for spreadsheet users.

    `affected_rows` is the ;-joined 1-based source rows (traceability, AGENTS §7);
    empty numeric fields are blank rather than "None" so spreadsheets stay typed.
    """
    columns = (
        "rule_id",
        "severity",
        "signal",
        "affected_rows",
        "observed_value",
        "calculated_value",
        "maximum_possible_value",
        "suspected_cause",
        "confidence",
        "title",
        "description",
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for f in findings:
        writer.writerow(
            [
                f.rule_id,
                f.severity.value,
                f.signal or "",
                ";".join(str(r) for r in f.affected_rows),
                _num(f.observed_value),
                _num(f.calculated_value),
                _num(f.maximum_possible_value),
                f.suspected_cause or "",
                "" if f.confidence is None else f.confidence,
                f.title,
                f.description,
            ]
        )
    return buf.getvalue()


def _num(value: float | None) -> str:
    return "" if value is None else str(value)


# --- markdown report (deterministic) ------------------------------------


def _md_num(value: float) -> str:
    return f"{value:g}"


def finding_markdown(finding: Finding) -> str:
    """One finding's verified facts as markdown. Deterministic -- every fact is
    computed, never guessed or invented."""
    lines = [
        f"### [{finding.severity.value.upper()}] {finding.title} `({finding.rule_id})`"
    ]
    if finding.description:
        lines.append(finding.description)
    rows = "; ".join(str(r) for r in finding.affected_rows) or "—"
    lines.append(f"- affected rows: {rows}")
    if finding.signal:
        lines.append(f"- signal: {finding.signal}")
    if finding.observed_value is not None:
        lines.append(f"- observed: {_md_num(finding.observed_value)}")
    if finding.calculated_value is not None:
        lines.append(f"- calculated: {_md_num(finding.calculated_value)}")
    if finding.maximum_possible_value is not None:
        lines.append(f"- maximum possible: {_md_num(finding.maximum_possible_value)}")
    if finding.suspected_cause:
        lines.append(f"- suspected cause: {finding.suspected_cause}")
    if finding.confidence is not None:
        lines.append(f"- confidence: {finding.confidence}")
    return "\n".join(lines)


def report_markdown(
    findings: list[Finding], profile: DatasetProfile | None = None
) -> str:
    """The deterministic, offline-capable human-readable report."""
    lines = ["# LineLens report"]
    if profile is not None:
        lines += ["", f"_{profile.row_count} rows · {len(profile.columns)} columns_"]
    if findings:
        c = Counter(f.severity.value for f in findings)
        lines += [
            "",
            (f"_{c.get('error', 0)} error · {c.get('warning', 0)} warning · "
            f"{c.get('info', 0)} info_"),
        ]
    lines += [""]
    if not findings:
        lines.append("No problems detected — the data is clean.")
    for f in findings:
        lines += ["", finding_markdown(f)]
    return "\n".join(lines).rstrip() + "\n"
