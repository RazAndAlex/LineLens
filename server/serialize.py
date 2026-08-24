"""JSON-safe serializers: linelens dataclasses / frames -> plain dicts.

Every value that crosses the API passes through ``_json_safe`` (NaN/NaT ->
null, Timestamps/dates -> ISO strings, numpy scalars -> Python scalars), so
FastAPI's jsonable_encoder never trips over pandas types.

The ``scope_value`` gotcha: summaries builds it as an object column mixing
None (overall), datetime.date (day) and str (shift). Here the overall scope
serializes as JSON **null** (not the string "overall") — the ``scope`` column
already says "overall", and null round-trips unambiguously. Dates become ISO
strings; every ``scope_value`` in a payload is therefore either null or a
string.
"""
from __future__ import annotations

import datetime
import math

import pandas as pd

from linelens.models import CanonicalRole, DatasetProfile, Finding


def _json_safe(v):
    """One scalar -> a JSON-safe value (null / str / int / float / bool)."""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if v is pd.NaT:
        return None
    if isinstance(v, pd.Timestamp):
        return None if pd.isna(v) else v.isoformat()
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.isoformat()
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):  # numpy scalar
        return _json_safe(v.item())
    return v


def profile_dict(profile: DatasetProfile) -> dict:
    """DatasetProfile -> dict. ``to_dict()`` is already JSON-safe by contract
    (ints, strings, lists of strings)."""
    return profile.to_dict()


def finding_dict(f: Finding) -> dict:
    """Finding -> dict; ``to_dict()`` gives ISO period strings, but evidence is
    a free-form dict, so it is scrubbed defensively."""
    d = f.to_dict()
    d["evidence"] = {k: _json_safe(v) for k, v in d["evidence"].items()}
    return d


def frame_records(frame: pd.DataFrame) -> list[dict]:
    """A totals frame -> a records list with every value JSON-safe.

    ``scope_value``: None (overall) -> null, date (day) -> ISO string,
    shift label -> unchanged string.
    """
    return [
        {k: _json_safe(v) for k, v in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def report_dict(rep) -> dict:
    """SummaryReport -> the three totals frames as records + duration_source.
    ``aggregation_findings`` is deliberately not repeated here — the findings
    are merged and serialized once at the deck level."""
    return {
        "state_totals": frame_records(rep.state_totals),
        "production_totals": frame_records(rep.production_totals),
        "downtime_by_reason": frame_records(rep.downtime_by_reason),
        "duration_source": rep.duration_source,
    }


def oee_dict(oee) -> dict | None:
    """OEEResult -> dict (None passthrough: OEE undefined for the mapping)."""
    if oee is None:
        return None
    return {
        "availability": oee.availability,
        "performance": oee.performance,
        "quality": oee.quality,
        "oee": oee.oee,
        "run_time": oee.run_time,
        "unplanned_stop_time": oee.unplanned_stop_time,
        "planned_stop_time": oee.planned_stop_time,
        "idle_time": oee.idle_time,
        "good": oee.good,
        "reject": oee.reject,
        "bottles_lost": [
            {
                "cause": b.cause,
                "seconds_lost": b.seconds_lost,
                "weighted_target": b.weighted_target,
                "bottles": b.bottles,
            }
            for b in oee.bottles_lost
        ],
        "duration_source": oee.duration_source,
        "notes": list(oee.notes),
    }


def maintenance_dict(report) -> dict | None:
    """MaintenanceReport -> dict (None passthrough); dates as ISO strings."""
    if report is None:
        return None
    interval = report.interval
    due = report.due
    return {
        "bottles_since_service": report.bottles_since_service,
        "last_service_end": _json_safe(report.last_service_end),
        "n_service_events": report.n_service_events,
        "repair_threshold_s": report.repair_threshold_s,
        "interval": (
            None
            if interval is None
            else {
                "median": interval.median,
                "q1": interval.q1,
                "q3": interval.q3,
                "n": interval.n,
            }
        ),
        "due": (
            None
            if due is None
            else {
                "remaining_early": due.remaining_early,
                "remaining_late": due.remaining_late,
                "date_early": _json_safe(due.date_early),
                "date_late": _json_safe(due.date_late),
                "adjusted_earlier": due.adjusted_earlier,
                "reasons": list(due.reasons),
            }
        ),
        "notes": list(report.notes),
    }


def forecast_dict(view, reason: str) -> dict:
    """A resolved forecast -> {reason, view}. ``reason`` is "ok" |
    "too_few" | "zero_scatter" (from logic._resolve_forecast) or "no_series"
    (no dated series to forecast at all); ``view`` is null unless "ok"."""
    if view is None:
        return {"reason": reason, "view": None}
    return {
        "reason": reason,
        "view": {
            "line_dates": [_json_safe(d) for d in view.line_dates],
            "central": list(view.central),
            "band_dates": [_json_safe(d) for d in view.band_dates],
            "lower": list(view.lower),
            "upper": list(view.upper),
            "slope": view.slope,
            "r_squared": view.r_squared,
            "technique": view.technique,
        },
    }


def series_dict(series) -> dict | None:
    """A (dates, values) daily series -> {dates: ISO strings, values} (None
    passthrough)."""
    if series is None:
        return None
    dates, values = series
    return {"dates": [_json_safe(d) for d in dates], "values": list(values)}


def mtbf_dict(band) -> dict | None:
    """A (median, q1, q3) MTBF band in seconds -> dict (None passthrough)."""
    if band is None:
        return None
    median, q1, q3 = band
    return {"median": median, "q1": q1, "q3": q3}


def preview_records(raw: pd.DataFrame, n: int = 10) -> list[dict]:
    """The raw head as records with string-safe values (the upload preview)."""
    return [
        {k: _json_safe(v) for k, v in row.items()}
        for row in raw.head(n).to_dict(orient="records")
    ]


def state_interval_records(ctx) -> list[dict]:
    """The state-timeline intervals app.py's ``_state_timeline`` reads, as
    records: start/end ISO timestamps, state, machine (null when unmapped).

    Same derivation as the Streamlit chart: the end comes from the mapped end
    column, or start + duration when only a duration column exists. Empty when
    there is no start timestamp, no state column, or neither an end nor a
    duration column.
    """
    start = ctx.mapping.source_for(CanonicalRole.TIMESTAMP_START)
    end = ctx.mapping.source_for(CanonicalRole.TIMESTAMP_END)
    dur = ctx.mapping.source_for(CanonicalRole.DURATION)
    state = ctx.mapping.source_for(CanonicalRole.STATE)
    machine = ctx.mapping.source_for(CanonicalRole.MACHINE_ID)
    if not (start and state and (end or dur)):
        return []
    df = ctx.data[[c for c in (start, end, state, machine) if c]].copy()
    df[start] = pd.to_datetime(df[start])
    if end:
        df[end] = pd.to_datetime(df[end])
    else:
        end = "__end__"
        df[end] = df[start] + pd.to_timedelta(
            pd.to_numeric(ctx.data[dur], errors="coerce"), unit="s"
        )
    records = []
    for row in df.to_dict(orient="records"):
        records.append(
            {
                "start": _json_safe(row[start]),
                "end": _json_safe(row[end]),
                "state": _json_safe(row[state]),
                "machine": _json_safe(row[machine]) if machine else None,
            }
        )
    return records
