"""LineLens — FastAPI backend for the React UI.

Thin HTTP shell over ``linelens`` + ``server.logic``: every number is computed
by the same functions app.py's Analyze button runs, serialized by
``server.serialize``. Local single-user app: datasets live in an in-memory
store keyed by a random id, and each dataset caches its ``ValidationContext``
keyed by the mapping fingerprint (``logic._mapping_fingerprint``) so analyze /
scope / whatif / export never rebuild a context they have seen. No eviction —
a session holds a handful of CSVs.

Forecasts are always trained on the FULL context, never a date-scoped one
(ADR-0007 leakage guard) — the scope endpoint therefore returns only the
re-aggregated totals, no forecast.
"""
from __future__ import annotations

import hashlib
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, UploadFile
from fastapi.responses import Response

from linelens import ingestion, maintenance, reliability, reporting, schema, summaries, validation, whatif
from linelens.models import CanonicalRole, DatasetProfile, ParseError, Severity
from linelens.oee import oee_from_context
from server import logic, serialize
from server.schemas import AnalyzeRequest, MappingIn, ScopeRequest, WhatIfRequest

_SEVERITY_RANK = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}

# The API's display horizon: 14 days (the new UI opens the future chart
# future-majority). The Streamlit app keeps logic._FORECAST_HORIZON_DAYS (7) —
# _resolve_forecast/_degradation_caption default to it, so app.py is untouched.
_API_FORECAST_HORIZON = 14


@dataclass
class DatasetState:
    """One uploaded CSV: the raw frame + profile, plus per-mapping caches."""

    name: str
    raw: pd.DataFrame
    profile: DatasetProfile
    ctxs: dict[str, object] = field(default_factory=dict)     # fingerprint -> ValidationContext
    findings: dict[str, list] = field(default_factory=dict)   # fingerprint -> sorted findings


def _sorted_findings(findings: list) -> list:
    """The display order app.py renders: errors, then warnings, then infos —
    stable within each severity (validation/aggregation order preserved)."""
    return sorted(findings, key=lambda f: _SEVERITY_RANK[f.severity])


def create_app() -> FastAPI:
    app = FastAPI(title="LineLens")
    store: dict[str, DatasetState] = {}

    def _state(dataset_id: str) -> DatasetState:
        try:
            return store[dataset_id]
        except KeyError:
            raise HTTPException(404, f"unknown dataset {dataset_id!r}") from None

    def _ctx_for(state: DatasetState, mapping_in: MappingIn):
        """(mapping, ctx, fingerprint) — validated, cached by fingerprint."""
        roles: dict[CanonicalRole, str] = {}
        for name, col in mapping_in.roles.items():
            try:
                roles[CanonicalRole(name)] = col
            except ValueError:
                raise HTTPException(422, f"unknown canonical role {name!r}") from None
        mapping = schema.build_mapping(roles, counters=mapping_in.counters)
        problems = schema.validate_mapping(mapping, state.profile.columns)
        if problems:
            raise HTTPException(422, {"problems": problems})
        fingerprint = hashlib.sha1(
            repr(logic._mapping_fingerprint(state.name, mapping)).encode()
        ).hexdigest()[:16]
        ctx = state.ctxs.get(fingerprint)
        if ctx is None:
            ctx = validation.make_context(state.raw, state.profile, mapping)
            state.ctxs[fingerprint] = ctx
        return mapping, ctx, fingerprint

    def _findings_for(state: DatasetState, fingerprint: str, ctx) -> list:
        findings = state.findings.get(fingerprint)
        if findings is None:
            rep = summaries.summarize(ctx)
            findings = _sorted_findings(
                validation.run_validation(ctx) + rep.aggregation_findings
            )
            state.findings[fingerprint] = findings
        return findings

    # --- upload ---------------------------------------------------------------

    @app.post("/api/upload")
    async def upload(file: UploadFile):
        # Same shim as app.py's _load_uploaded: ingestion.load_csv takes a
        # path, so the upload lands in a temp file with the original suffix;
        # the temp name is scrubbed from any ParseError before it reaches the
        # client.
        suffix = Path(file.filename or "").suffix or ".csv"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(await file.read())
            tmp_path = Path(tmp.name)
        try:
            raw, profile = ingestion.load_csv(tmp_path)
        except ParseError as exc:
            raise HTTPException(422, logic._clean_parse_error(exc, tmp_path)) from None
        finally:
            tmp_path.unlink(missing_ok=True)

        dataset_id = uuid.uuid4().hex
        name = file.filename or tmp_path.name
        store[dataset_id] = DatasetState(name=name, raw=raw, profile=profile)

        # The auto-first mapping (ADR-0010 decision 9), mirroring app.py's
        # _render_preview_and_map: silent conflict-free auto-map + auto counters.
        suggestions = schema.suggest_roles(profile.columns)
        auto_roles = logic._auto_roles(suggestions)
        auto_counters = logic._auto_counters(profile, auto_roles)
        auto_mapping = schema.build_mapping(auto_roles, counters=auto_counters)
        return {
            "dataset_id": dataset_id,
            "name": name,
            "profile": serialize.profile_dict(profile),
            "preview": serialize.preview_records(raw),
            "preview_summary": logic._preview_summary(raw, profile, auto_roles),
            "suggested_roles": {
                col: {"role": role.value if role is not None else None, "confidence": conf}
                for col, (role, conf) in suggestions.items()
            },
            "auto_roles": {role.value: col for role, col in auto_roles.items()},
            "auto_counters": auto_counters,
            "numeric_counter_options": logic._numeric_counter_options(profile),
            "capabilities": logic._capabilities(auto_mapping),
        }

    # --- analyze: the full results deck ----------------------------------------

    @app.post("/api/datasets/{dataset_id}/analyze")
    def analyze(dataset_id: str, req: AnalyzeRequest):
        state = _state(dataset_id)
        mapping, ctx, fingerprint = _ctx_for(state, req.mapping)

        # Exactly app.py's Analyze button: summarize -> findings -> oee ->
        # maintenance, computed once and consumed, never recomputed downstream.
        rep = summaries.summarize(ctx)
        findings = _sorted_findings(
            validation.run_validation(ctx) + rep.aggregation_findings
        )
        state.findings[fingerprint] = findings
        oee = oee_from_context(ctx)
        maint = maintenance.maintenance_from_context(ctx)

        # The forecast layer trains on the full, un-scoped series (leak guard).
        good_series = logic._daily_good_series(rep.production_totals)
        if good_series is not None:
            good_view, good_reason = logic._resolve_forecast(
                *good_series, horizon=_API_FORECAST_HORIZON)
        else:
            good_view, good_reason = None, "no_series"

        perf_series = logic._daily_performance_series(ctx)
        if perf_series is not None:
            perf_view, perf_reason = logic._resolve_forecast(
                *perf_series, horizon=_API_FORECAST_HORIZON)
        else:
            perf_view, perf_reason = None, "no_series"
        crossing = (
            logic._threshold_crossing(perf_view, logic._PERFORMANCE_CONCERN)
            if perf_view is not None
            else None
        )

        intervals = reliability.fault_intervals(ctx)
        start_src = mapping.source_for(CanonicalRole.TIMESTAMP_START)
        span = logic._date_span(ctx, start_src)
        causes, bottles, cum = logic._pareto_series(oee) if oee is not None else ([], [], [])

        return {
            "fingerprint": fingerprint,
            "mapping": {"roles": dict(req.mapping.roles), "counters": list(req.mapping.counters)},
            "findings": [serialize.finding_dict(f) for f in findings],
            "severity_counts": logic._severity_counts(findings),
            "contrast_rows": [
                {k: serialize._json_safe(v) for k, v in row.items()}
                for row in logic._aggregation_contrast_rows(findings)
            ],
            "report": serialize.report_dict(rep),
            "oee": serialize.oee_dict(oee),
            "maintenance": serialize.maintenance_dict(maint),
            "planned_causes": sorted(logic._planned_causes(ctx)),
            "pareto": {"causes": causes, "bottles": bottles, "cumulative_pct": cum},
            "daily_good": serialize.series_dict(good_series),
            "forecast": serialize.forecast_dict(good_view, good_reason),
            "daily_performance": serialize.series_dict(perf_series),
            "performance_forecast": serialize.forecast_dict(perf_view, perf_reason),
            "performance_concern": logic._PERFORMANCE_CONCERN,
            "performance_crossing": serialize._json_safe(crossing),
            "degradation_caption": (
                logic._degradation_caption(perf_view, crossing, horizon=_API_FORECAST_HORIZON)
                if perf_view is not None
                else None
            ),
            "mtbf": serialize.mtbf_dict(reliability.mtbf_band(intervals)),
            "fault_interval_count": len(intervals),
            "date_span": [serialize._json_safe(d) for d in span] if span else None,
            "state_timeline": serialize.state_timeline(ctx),
            "capabilities": logic._capabilities(mapping),
        }

    # --- scope: Now-charts date window ------------------------------------------

    @app.post("/api/datasets/{dataset_id}/scope")
    def scope(dataset_id: str, req: ScopeRequest):
        state = _state(dataset_id)
        mapping, ctx, fingerprint = _ctx_for(state, req.mapping)
        start_src = mapping.source_for(CanonicalRole.TIMESTAMP_START)

        # _scoped_ctx semantics: a missing bound falls back to the dataset's
        # own span edge (the date picker's default window).
        span = logic._date_span(ctx, start_src)
        lo = req.start or (span[0] if span else None)
        hi = req.end or (span[1] if span else None)
        scoped_ctx, narrowed = logic._scoped_ctx(ctx, start_src, lo, hi)
        rep = summaries.summarize(scoped_ctx)
        # Deliberately no forecast/contrast here: the forecast trains on the
        # full series only (ADR-0007 leakage guard).
        return {
            "fingerprint": fingerprint,
            "narrowed": narrowed,
            "range": [serialize._json_safe(lo), serialize._json_safe(hi)],
            "state_timeline": serialize.state_timeline(scoped_ctx),
            "report": serialize.report_dict(rep),
        }

    # --- whatif -----------------------------------------------------------------

    @app.post("/api/datasets/{dataset_id}/whatif")
    def whatif_endpoint(dataset_id: str, req: WhatIfRequest):
        state = _state(dataset_id)
        _mapping, ctx, fingerprint = _ctx_for(state, req.mapping)
        for cause, r in req.reductions.items():
            if not 0.0 <= r <= 1.0:
                raise HTTPException(
                    422,
                    f"reduction for {cause!r} must be a fraction in [0, 1], got {r}",
                )
        baseline = oee_from_context(ctx)
        hypo = whatif.whatif_from_context(ctx, req.reductions)
        if baseline is None or hypo is None:
            raise HTTPException(
                422,
                "OEE is not computable for this mapping — it needs a state "
                "column and a time basis (duration or start+end timestamps).",
            )
        recovered = logic._recovered(baseline, hypo)

        # The what-if path: the production forecast's horizon lifted by the
        # recovered bottles, spread proportionally to each day's forecast level
        # (app.py's _future_line_chart move, via whatif.spread_recovered).
        # Null when nothing moved or no honest forecast exists. Performance is
        # deliberately NOT lifted (ADR-0005: P/Q stay at baseline).
        forecast_lift = None
        if recovered > 1e-9:
            rep = summaries.summarize(ctx)
            good_series = logic._daily_good_series(rep.production_totals)
            if good_series is not None:
                view, reason = logic._resolve_forecast(
                    *good_series, horizon=_API_FORECAST_HORIZON)
                if view is not None:
                    h = _API_FORECAST_HORIZON
                    lifted = whatif.spread_recovered(list(view.central[-h:]), recovered)
                    forecast_lift = {
                        "dates": [serialize._json_safe(d) for d in view.line_dates[-(h + 1):]],
                        "values": [view.central[-(h + 1)], *lifted],
                    }
        return {
            "fingerprint": fingerprint,
            "baseline": serialize.oee_dict(baseline),
            "hypo": serialize.oee_dict(hypo),
            "recovered": recovered,
            "lever_deltas": [
                {"cause": cause, "bottles": delta}
                for cause, delta in logic._lever_deltas(baseline, hypo, req.reductions)
            ],
            "forecast_lift": forecast_lift,
        }

    # --- exports ----------------------------------------------------------------

    def _cached_ctx(state: DatasetState, fingerprint: str):
        ctx = state.ctxs.get(fingerprint)
        if ctx is None:
            raise HTTPException(
                409,
                "unknown fingerprint — run analyze with this mapping first",
            )
        return ctx

    @app.get("/api/datasets/{dataset_id}/export/cleaned.csv")
    def export_cleaned(dataset_id: str, fingerprint: str = Query(...)):
        state = _state(dataset_id)
        ctx = _cached_ctx(state, fingerprint)
        return Response(
            content=reporting.cleaned_csv(ctx),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="linelens_cleaned.csv"'},
        )

    @app.get("/api/datasets/{dataset_id}/export/findings.json")
    def export_findings_json(dataset_id: str, fingerprint: str = Query(...)):
        state = _state(dataset_id)
        ctx = _cached_ctx(state, fingerprint)
        findings = _findings_for(state, fingerprint, ctx)
        return Response(
            content=reporting.findings_json(findings, state.profile),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="linelens_findings.json"'},
        )

    @app.get("/api/datasets/{dataset_id}/export/findings.csv")
    def export_findings_csv(dataset_id: str, fingerprint: str = Query(...)):
        state = _state(dataset_id)
        ctx = _cached_ctx(state, fingerprint)
        findings = _findings_for(state, fingerprint, ctx)
        return Response(
            content=reporting.findings_csv(findings),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="linelens_findings.csv"'},
        )

    return app
