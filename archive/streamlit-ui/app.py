"""LineLens — Streamlit UI (M6b). The composition root.

Run locally:

    uv sync --extra ui
    uv run streamlit run app.py

A left-to-right wizard: upload -> preview & map columns -> analyze -> read
findings + totals + charts -> export. All numbers come from the `linelens`
library; this file only wires widgets to library calls and renders results.

streamlit/plotly are lazy-imported inside main(), so `import app` (and the pure
helpers below) work without the `ui` extra installed -- the helpers are unit-
tested in the core suite. The rendered page itself is verified by running the app.
"""
from __future__ import annotations

import html
import tempfile
from pathlib import Path

import pandas as pd

from linelens import ingestion, maintenance, reliability, reporting, schema, summaries, validation, whatif
from linelens.models import (
    CanonicalRole,
    Finding,
    ParseError,
    Severity,
)
from linelens.oee import oee_from_context

# Pure, UI-free helpers (pandas + linelens only) live in server.logic, shared
# with the FastAPI backend; re-imported here under their original underscore
# names so every reference below (and the existing test suite) is unchanged.
from server.logic import (
    _DOWN,
    _FORECAST_HORIZON_DAYS,
    _FORECAST_MIN_DAYS,
    _INK_MUTED,
    _LOSS_DEEP,
    _LOSS_STRONG,
    _PERFORMANCE_CONCERN,
    _WHATIF_TOP_N,
    _ForecastView,
    _aggregation_contrast_rows,
    _auto_counters,
    _auto_roles,
    _bottle_countdown,
    _capabilities,
    _clean_parse_error,
    _daily_good_series,
    _daily_performance_series,
    _date_span,
    _degradation_caption,
    _display_frame,
    _due_window_phrasing,
    _fmt_num,
    _fmt_seconds,
    _fmt_span,
    _has_time_basis,
    _is_mapping_key,
    _lever_deltas,
    _loss_color_map,
    _mapping_fingerprint,
    _numeric_counter_options,
    _pareto_series,
    _planned_causes,
    _preview_summary,
    _recovered,
    _resolve_forecast,
    _scoped_ctx,
    _severity_counts,
    _single_machine_col,
    _threshold_crossing,
    _to_forecast_view,
)

# Selectable roles, None first ("unmapped"). `*CanonicalRole` unpacks the members.
_ROLE_OPTIONS: list = [None, *CanonicalRole]

# _WHATIF_TOP_N / _FORECAST_HORIZON_DAYS / _FORECAST_MIN_DAYS /
# _PERFORMANCE_CONCERN live in server.logic (imported above).


# --- design system: "diagnostic instrument" -------------------------------
# A tinted-graphite control surface with IBM Plex Sans (UI) + Plex Mono
# (tabular-numerics) and the dataviz skill's validated categorical palette.
# Charts carry their own Plotly template (below) and render with theme=None so
# Streamlit's theme never remaps their colors. Every hex here is either a
# validated categorical/status slot (see dataviz/references/palette.md) or a
# lone surface/ink value.

_INK = "#E8EDF2"
# _INK_MUTED and _DOWN live in server.logic (imported above) — shared with the
# API so the loss/severity colors can never fork between the two frontends.
_GRID = "rgba(255,255,255,0.06)"
_PANEL = "#141A22"
_PRIMARY = "#3987e5"      # categorical slot 1 (blue) — primary widgets & "state"
_HONEST = "#199e70"       # slot 5 (aqua) — trusted/honest path
_NAIVE = "#e66767"        # slot 8 (red) — overstatement
_REJECT = "#d95926"       # parts rejected
_COLORWAY = [
    "#3987e5", "#008300", "#d55181", "#c98500",
    "#199e70", "#d95926", "#9085e9", "#e66767",
]
# Canonical per-state hue (M8 node 8): same state = same color in every chart,
# killing the blue=Stopped-here / blue=Idle-there bug. Palette A's literal hexes
# FAILED the dataviz validator (cause pair #58A6B8<->#4A90E2 ΔE 10.1 < the 15
# normal-vision floor), so this reuses the already-validated tokens above. Idle
# is a recessive neutral by intent (low chroma = inert); it clears the CVD /
# normal-vision separation floors and is backed by segment gaps + legend labels.
# ponytail: Idle sits below the 0.1 categorical chroma floor — the known ceiling;
# raise its saturation only if it must read as a saturated category, not a neutral.
_STATE_COLOR = {"Running": _PRIMARY, "Stopped": _DOWN, "Idle": _INK_MUTED}
# The color-by-message loss tiers (M9, ADR-0010 decision 10: _LOSS_STRONG /
# _LOSS_DEEP / _LOSS_TIERS / _LOSS_TIER_SPLITS) live in server.logic with
# _loss_color_map, the only consumer that must stay unit-testable.
# Finding severity as status colors (icon+label carry it, never hue alone).
_SEVERITY_COLOR = {"error": "#d03b3b", "warning": "#fab219", "info": "#5AA9FF"}

# Capability status marks in the favicon's dot language (filled = on, ring = off).
_DOT_ON = '<svg width="9" height="9" viewBox="0 0 9 9"><circle cx="4.5" cy="4.5" r="3.3" fill="#199e70"/></svg>'
_DOT_OFF = '<svg width="9" height="9" viewBox="0 0 9 9"><circle cx="4.5" cy="4.5" r="2.9" fill="none" stroke="#6B7B8F" stroke-width="1.5"/></svg>'

# Favicon (favicon.png at repo root): the wordmark as a mark — dark tile, white
# L, blue accent dot. Passed to st.set_page_config(page_icon=) so Streamlit
# serves it directly instead of the default emoji.
_INSTRUMENT_CSS = """
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');
html, body, .stApp { font-family: 'IBM Plex Sans', system-ui, -apple-system, sans-serif !important; }
.stApp { background: #0B0F14; }
#MainMenu, footer { visibility: hidden; }
.stDeployButton { display: none !important; }

.ll-wordmark { font-family:'IBM Plex Sans'; font-weight:700; font-size:2.5rem !important; letter-spacing:-0.025em; line-height:1; margin:0; color:#E8EDF2; }
.ll-wordmark .dot { color:#3987e5; }
.ll-tag { font-family:'IBM Plex Mono'; font-weight:400; font-size:0.72rem; letter-spacing:0.06em; color:#6B7B8F; margin:0.4rem 0 0; }
.ll-rule { border:0; border-top:1px solid rgba(255,255,255,0.08); margin:0.9rem 0 1.3rem; }

/* section headers read as instrument eyebrows */
.stApp h2 { font-family:'IBM Plex Mono'; font-weight:500; font-size:0.82rem; letter-spacing:0.04em; text-transform:uppercase; color:#9FB2C7; border-bottom:1px solid rgba(255,255,255,0.08); padding-bottom:0.45rem; margin-top:0.4rem; }
.stApp h3 { font-family:'IBM Plex Sans'; font-weight:600; color:#E8EDF2; }

/* captions, status alerts, and finding text render here — force Plex Sans so the
   default theme font does not bleed through the instrument look */
[data-testid="stMarkdownContainer"] { font-family: 'IBM Plex Sans', system-ui, sans-serif; }

/* every measurement reads as an instrument readout */
[data-testid="stMetricLabel"] { font-family:'IBM Plex Mono'; font-size:0.66rem; letter-spacing:0.06em; text-transform:uppercase; color:#6B7B8F; }
[data-testid="stMetricValue"], [data-testid="stMetricDelta"] { font-family:'IBM Plex Mono', monospace; font-variant-numeric: tabular-nums; font-weight:500; }
[data-testid="stMetricValue"] { color:#E8EDF2; }

/* data tables: quiet panel, hairline edge */
[data-testid="stDataFrameResizable"] { border:1px solid rgba(255,255,255,0.08); border-radius:8px; overflow:hidden; }

/* severity chip beside each finding */
.ll-sev { font-family:'IBM Plex Mono'; font-size:0.64rem; font-weight:600; letter-spacing:0.07em; text-transform:uppercase; padding:1px 6px; border-radius:4px; border:1px solid currentColor; }

/* Diagnosis slim banner (M9, ADR-0010 decision 1): one quiet line with the
   finding counts as severity chips; the details expand inline behind it. */
.ll-banner { background:#141A22; border:1px solid rgba(255,255,255,0.08); border-radius:8px; padding:0.55rem 0.9rem; color:#E8EDF2; font-size:0.92rem; display:flex; gap:12px; align-items:center; flex-wrap:wrap; }

/* capability chips: dot + label, the favicon's mark language */
.caps { display:flex; flex-wrap:wrap; gap:6px 16px; margin:0.35rem 0 0.1rem; }
.cap { display:inline-flex; align-items:center; gap:7px; font-family:'IBM Plex Mono'; font-size:.72rem; letter-spacing:.01em; }
.cap svg { display:block; }
.cap-on .cap-label { color:#E8EDF2; }
.cap-off .cap-label { color:#6B7B8F; }

/* Sticky per-section control zones (M9, ADR-0010 decision 2, supersedes the
   M8 single bar). Each zone is a plain st.container wrapping its section; the
   control bar is a second, nested container carrying a [data-ll] anchor. The
   selector matches a stLayoutWrapper holding the anchor that is itself nested
   inside another stLayoutWrapper — the inner bar, never the zone (the zone's
   wrapper is a direct child of the root block). position:sticky is bounded by
   the parent, so the Now filter bar pins only within Now and the what-if
   slider rail only within Future line — two independent zones, no JS scroll
   detection (rejected: version-fragile). top: 2.875rem clears Streamlit's
   opaque stHeader on 1.59.2 — the M8 bug was pinning at top 0, which slid the
   radios and the date label under the header and left only the date pill
   showing. Background is the opaque app surface so charts scrolling under
   never bleed through. Streamlit's DOM classes shift between versions —
   re-verify in-browser if this stops sticking. */
[data-testid="stLayoutWrapper"] [data-testid="stLayoutWrapper"]:has([data-ll="filterbar"]),
[data-testid="stLayoutWrapper"] [data-testid="stLayoutWrapper"]:has([data-ll="sliderrail"]) {
    position: -webkit-sticky; position: sticky; top: 2.875rem; z-index: 1000;
    background: #0B0F14; border-bottom: 1px solid rgba(255,255,255,0.08);
    padding: 0.35rem 0 0.5rem;
}
"""


def _inject_chrome(st):
    """Wordmark + fonts + instrument CSS. Idempotent across reruns."""
    st.markdown(
        '<p class="ll-wordmark">LineLens<span class="dot">.</span></p>'
        '<p class="ll-tag">Deterministic totals from machine CSV exports</p>'
        '<hr class="ll-rule">',
        unsafe_allow_html=True,
    )
    st.markdown(f"<style>{_INSTRUMENT_CSS}</style>", unsafe_allow_html=True)


def _apply_chart_theme(px, go):
    """One Plotly template every chart inherits: recessive hairline grid, Plex
    fonts (Mono for ticks), validated categorical colorway. Set once on px.defaults."""
    tmpl = go.layout.Template()
    lay = tmpl.layout
    lay.paper_bgcolor = "rgba(0,0,0,0)"
    lay.plot_bgcolor = "rgba(0,0,0,0)"
    lay.font = dict(family="IBM Plex Sans, sans-serif", size=12, color=_INK_MUTED)
    lay.colorway = _COLORWAY
    lay.margin = dict(l=64, r=16, t=40, b=72)
    lay.bargap = 0.32
    lay.bargroupgap = 0.12
    axis = dict(
        gridcolor=_GRID, zerolinecolor=_GRID, showline=False,
        tickfont=dict(family="IBM Plex Mono, monospace", size=10.5, color=_INK_MUTED),
        linecolor="rgba(255,255,255,0.10)",
    )
    lay.xaxis = axis
    lay.yaxis = axis
    lay.hoverlabel = dict(
        bgcolor=_PANEL, font=dict(family="IBM Plex Mono", size=11.5, color=_INK),
        bordercolor="rgba(255,255,255,0.12)",
    )
    lay.legend = dict(
        orientation="h", y=-0.22, x=0, font=dict(size=10.5, color=_INK_MUTED),
        title_font=dict(size=10.5), bgcolor="rgba(0,0,0,0)",
    )
    px.defaults.template = tmpl
    px.defaults.color_discrete_sequence = _COLORWAY
    px.defaults.color_continuous_scale = [
        "#0d366b", "#184f95", "#256abf", "#3987e5", "#86b6ef"
    ]


# --- the page (streamlit/plotly lazy-imported inside main) ----------------


def main() -> None:
    import plotly.express as px
    import plotly.graph_objects as go
    import streamlit as st

    st.set_page_config(page_title="LineLens", page_icon="favicon.png", layout="wide")
    _inject_chrome(st)
    _apply_chart_theme(px, go)

    uploaded = st.file_uploader("Upload a CSV export", type=["csv", "tsv", "txt"])
    if uploaded is None:
        st.info("Upload a machine CSV export to begin.")
        return

    raw, profile = _load_uploaded(uploaded, st)

    st.divider()
    st.header("1 · Preview & map columns")
    mapping, problems, duplicate_role = _render_preview_and_map(st, raw, profile)
    _render_capabilities(st, mapping)
    if problems or duplicate_role:
        st.warning("Resolve the mapping problems above to analyze.")
        return

    st.divider()
    st.header("2 · Analyze")
    fingerprint = _mapping_fingerprint(uploaded.name, mapping)
    if st.button("Analyze", type="primary"):
        ctx = validation.make_context(raw, profile, mapping)
        rep = summaries.summarize(ctx)
        st.session_state["result"] = {
            "fingerprint": fingerprint,
            "findings": validation.run_validation(ctx) + rep.aggregation_findings,
            "report": rep,
            "ctx": ctx,
            "oee": oee_from_context(ctx),
            "maintenance": maintenance.maintenance_from_context(ctx),
        }

    result = st.session_state.get("result")
    if not result:
        st.info("Click **Analyze**.")
        return
    if result["fingerprint"] != fingerprint:
        st.info("Mapping changed since the last run. Click **Analyze** to refresh.")
        return

    _render_results(st, px, go, result, profile)


def _load_uploaded(uploaded, st):
    """Load the UploadedFile once per file (cached in session_state) via a temp
    path, since ingestion.load_csv takes a path. Temp file is removed after load."""
    key = (uploaded.name, uploaded.size, getattr(uploaded, "id", None))
    if st.session_state.get("loaded_key") != key:
        suffix = Path(uploaded.name).suffix or ".csv"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(uploaded.getvalue())
            tmp_path = Path(tmp.name)
        try:
            raw, profile = ingestion.load_csv(tmp_path)
        except ParseError as exc:
            st.error(f"Could not parse **{uploaded.name}**: {_clean_parse_error(exc, tmp_path)}")
            st.stop()
        finally:
            tmp_path.unlink(missing_ok=True)
        st.session_state.update(
            loaded_key=key, loaded_raw=raw, loaded_profile=profile
        )
        st.session_state.pop("result", None)  # new file -> prior results are stale
        # bug #2: a new file must start from a fresh mapping, not the previous
        # file's role/counter selections that linger under these widget keys.
        for k in [k for k in st.session_state if _is_mapping_key(k)]:
            st.session_state.pop(k, None)
    return st.session_state["loaded_raw"], st.session_state["loaded_profile"]


# --- section 1: auto-first preview & map (M9, ADR-0010 decision 9) ----------
# The pure seams of this section (_auto_roles / _auto_counters /
# _single_machine_col / _preview_summary) live in server.logic.


def _render_preview_and_map(st, raw, profile):
    """Section 1, auto-first (ADR-0010 decision 9): silent auto-map with a
    plain-words summary, the raw preview labeled as a sample, and the 13
    mapping dropdowns demoted behind an "Adjust column mapping" expander — a
    fallback, not a gate. Upload -> read the summary -> Analyze, zero required
    decisions.

    Returns ``(mapping, problems, duplicate_role)`` exactly like the old
    gate-style ``_render_mapping`` so the Analyze flow is unchanged.
    """
    auto_roles = _auto_roles(schema.suggest_roles(profile.columns))
    st.markdown(_preview_summary(raw, profile, auto_roles))
    auto_counters = _auto_counters(profile, auto_roles)
    if auto_counters:
        # decision 9: auto-detected counters are explained in the auto-first
        # flow, not only inside the expander the lay user may never open.
        st.caption(
            f"Auto-detected {len(auto_counters)} odometer column"
            f"{'s' if len(auto_counters) != 1 else ''} "
            f"({', '.join(auto_counters)}) — we difference them, not sum them."
        )
    st.caption(f"First 10 of {profile.row_count:,} rows")
    st.dataframe(raw.head(10), width="stretch")

    with st.expander("Adjust column mapping", expanded=False):
        hidden_machine = _single_machine_col(raw, auto_roles)
        col_to_role = {c: r for r, c in auto_roles.items()}
        chosen: list[tuple[str, object]] = []
        roles: dict[CanonicalRole, str] = {}
        if hidden_machine is not None:
            chosen.append((hidden_machine, CanonicalRole.MACHINE_ID))
            roles[CanonicalRole.MACHINE_ID] = hidden_machine
            st.caption(f"`{hidden_machine}` holds a single machine — auto-mapped, no picker.")
        cols = st.columns(3)
        i = 0
        for col_name in profile.columns:
            if col_name == hidden_machine:
                continue
            with cols[i % 3]:
                i += 1
                current = col_to_role.get(col_name)
                default = _ROLE_OPTIONS.index(current) if current in _ROLE_OPTIONS else 0
                role = st.selectbox(
                    col_name,
                    _ROLE_OPTIONS,
                    index=default,
                    format_func=lambda r: r.value if r is not None else "(none)",
                    key=f"role::{col_name}",
                )
                chosen.append((col_name, role))
                if role is not None:
                    roles[role] = col_name  # last wins; duplicates flagged below

        counters = st.multiselect(
            "Counter columns",
            _numeric_counter_options(profile),
            default=_auto_counters(profile, roles),
            key="counters",
        )
        st.caption(
            "Counters are odometer columns — we difference them, not sum them."
        )

    # two columns mapped to the same role (validate_mapping checks the reverse)
    role_to_cols: dict[CanonicalRole, list[str]] = {}
    for col, role in chosen:
        if role is not None:
            role_to_cols.setdefault(role, []).append(col)
    duplicate_role = any(len(cs) > 1 for cs in role_to_cols.values())

    mapping = schema.build_mapping(roles, counters=counters)
    problems = schema.validate_mapping(mapping, profile.columns)
    if duplicate_role:
        dup = ", ".join(
            f"{r.value} <- {', '.join(cs)}"
            for r, cs in role_to_cols.items()
            if len(cs) > 1
        )
        st.error(f"Two columns map to the same role ({dup}). Keep one.")
    for problem in problems:
        st.warning(problem)
    return mapping, problems, duplicate_role


def _render_capabilities(st, mapping):
    caps = _capabilities(mapping)
    chips = "".join(
        f'<span class="cap {"cap-on" if v else "cap-off"}">'
        f'{_DOT_ON if v else _DOT_OFF}<span class="cap-label">{html.escape(k)}</span></span>'
        for k, v in caps.items()
    )
    st.markdown(f'<div class="caps">{chips}</div>', unsafe_allow_html=True)


def _render_results(st, px, go, result, profile):
    findings: list[Finding] = result["findings"]
    rep = result["report"]
    counts = _severity_counts(findings)

    # M8: the page is now a 3-act narrative (plan.md node 2): Now → Loss → Future
    # line → Reliability → Export. Findings stay first as the pre-act diagnosis;
    # the aggregation-contrast chart (whole-dataset, date-range-independent) is
    # lifted out of `_charts` to sit with them, not under Now. The forecast left
    # the Now production chart (P3) and lives in Act 3 (P4); the what-if moved out
    # of its own "5·What-if" section into Act 3 alongside it (reverses ADR-0005's
    # placement — to be recorded in the UI ADR drafted in P6).

    # --- Diagnosis (pre-act): what's wrong with the data ---------------------
    # M9 (ADR-0010 decision 1): Diagnosis stays first (trust-first, ADR-0008)
    # but collapses to a slim banner — one line of severity counts; the
    # findings themselves expand inline behind it (open by default when there
    # are errors, mirroring the M8 behavior).
    st.divider()
    st.header("Diagnosis")
    if not findings:
        st.success("No problems detected. The data is clean.")
    else:
        chips = " ".join(
            f'<span class="ll-sev" style="color:{_SEVERITY_COLOR[s]}">'
            f'{counts[s]} {s.upper()}</span>'
            for s in ("error", "warning", "info") if counts[s]
        )
        st.markdown(
            f'<div class="ll-banner"><span>{len(findings)} finding'
            f'{"s" if len(findings) != 1 else ""} in the data</span>{chips}</div>',
            unsafe_allow_html=True,
        )
        with st.expander("Inspect findings", expanded=counts["error"] > 0):
            for sev in (Severity.ERROR, Severity.WARNING, Severity.INFO):
                bucket = [(i, f) for i, f in enumerate(findings) if f.severity is sev]
                if not bucket:
                    continue
                st.subheader(f"{sev.value.title()} ({len(bucket)})")
                for i, f in bucket:
                    _render_finding(st, f)
    # The aggregation contrast is a diagnosis (whole dataset, never date-scoped)
    # — it belongs with the findings, not under the Now charts.
    contrast = _contrast_chart(go, findings)
    if contrast is not None:
        st.caption(
            "A dashboard that **sums** a cumulative totalizer overstates the "
            "period. The honest increase is last minus first (plus resets).")
        _show(st, contrast)

    # --- Act 1 — Now: where the production stands today ----------------------
    # OEE is consumed, never recomputed here -- oee_from_context ran at Analyze
    # time. The fallback (cached back onto the result) only serves a
    # session_state result from before this key existed; it also caches a
    # legitimate None so we don't re-derive on every rerun.
    if "oee" not in result:
        result["oee"] = oee_from_context(result["ctx"])
    oee = result["oee"]
    st.divider()
    st.header("Now")
    if oee is None:
        st.info(
            "OEE unavailable — map a **STATE** column and a time basis "
            "(a **duration** column, or both **start/end** timestamps) to compute "
            "Availability, Performance, Quality and OEE."
        )
    else:
        _render_kpi_cards(st, oee)
    # Raw totals tables (locked decision #6: collapsed into an expander). They
    # come from `summaries`, independent of OEE, so they show either way.
    with st.expander("Raw totals — state, production, downtime", expanded=False):
        _table(st, rep.state_totals, "State totals (seconds)")
        _table(st, rep.production_totals, "Production totals")
        _table(st, rep.downtime_by_reason, "Downtime by reason (seconds)")
        if rep.duration_source is None:
            st.info("No duration source. Time-based totals are unavailable.")
    # The Now sticky zone (ADR-0010): the container's box bounds the filter
    # bar's sticky pin, so Group-by + date range stay pinned through the Now
    # charts and release at the section's end — never into Loss/Future/Export.
    with st.container():
        _charts(st, px, go, result["ctx"], rep, findings)

    # --- Act 2 — Loss: where the bottles go ----------------------------------
    st.divider()
    st.header("Loss")
    if oee is None:
        st.info("No bottles lost to price — map **STATE** and a time basis to "
                "see the loss Pareto (the Now section names what's needed).")
    else:
        _render_pareto(st, px, go, oee)

    # --- Act 3 — Future line: where it's heading + what would move it -------
    st.divider()
    st.header("Future line")
    # The Future-line sticky zone (ADR-0010 decision 2): the what-if slider
    # rail pins only within this container's box — through the KPI cards, the
    # future-line chart, and the waterfall — and releases into Reliability.
    with st.container():
        whatif_state = _render_whatif(st, result)  # None when no baseline / priced stops
        baseline, hypo, reductions = whatif_state or (oee, None, {})
        # The forecast needs only production_totals (not OEE), so it renders even
        # when the what-if can't (no STATE / no priced stops) — only the what-if line
        # and the waterfall are gated on a baseline + hypo.
        _future_line_chart(st, go, rep.production_totals, baseline, hypo, reductions)
        if baseline is not None and hypo is not None:
            _lever_waterfall(st, go, baseline, hypo, reductions)

    # --- Act 4 — Reliability & Maintenance (P5/M9) --------------------------
    # (C) Performance-degradation forecast (the dated Performance ratio continued
    # as a banded forecast toward a concern threshold) + (A) the banded next-fault
    # tile (MTBF median ± IQR from the Fault inter-arrival intervals) + (M9) the
    # maintenance view: the service counter always, the learned due window when
    # the rhythm is learnable. The due window consumes the same degradation
    # signal as the forecast (ADR-0009 decision 4), which is why maintenance
    # joins Reliability as the final act (ADR-0010 decision 1). All three reuse
    # pure helpers (oee.performance_by_day, reliability.fault_intervals /
    # mtbf_band, maintenance.maintenance_from_context) and the Act-3 forecast
    # layer; the forecast trains on the full history (leakage guard, ADR-0007).
    st.divider()
    st.header("Reliability & Maintenance")
    _degradation_chart(st, go, result["ctx"])
    _mtbf_tile(st, result["ctx"])
    _maintenance_view(st, result)

    # --- Export --------------------------------------------------------------
    st.divider()
    st.header("Export")
    ctx = result["ctx"]
    st.download_button(
        "Cleaned CSV", reporting.cleaned_csv(ctx), "linelens_cleaned.csv", "text/csv"
    )
    st.download_button(
        "Findings JSON",
        reporting.findings_json(findings, profile),
        "linelens_findings.json",
        "application/json",
    )
    st.download_button(
        "Findings CSV",
        reporting.findings_csv(findings),
        "linelens_findings.csv",
        "text/csv",
    )


def _render_finding(st, f: Finding):
    color = _SEVERITY_COLOR[f.severity.value]
    st.markdown(
        f'<span class="ll-sev" style="color:{color}">{html.escape(f.severity.value.upper())}</span>'
        f' <span style="font-weight:600;color:#E8EDF2">{html.escape(f.title)}</span>'
        f' <code style="color:#6B7B8F;font-size:.82em">{html.escape(f.rule_id)}</code>',
        unsafe_allow_html=True,
    )
    st.write(f.description)
    bits: list[str] = []
    if f.affected_rows:
        bits.append("rows: " + "; ".join(str(r) for r in f.affected_rows))
    if f.signal:
        bits.append(f"signal: {f.signal}")
    if f.observed_value is not None:
        bits.append(f"observed: {f.observed_value:g}")
    if f.calculated_value is not None:
        bits.append(f"calculated: {f.calculated_value:g}")
    if f.suspected_cause:
        bits.append(f"cause: {f.suspected_cause}")
    if bits:
        st.caption(" · ".join(bits))


def _table(st, frame: pd.DataFrame, label: str):
    if frame.empty:
        return
    st.subheader(label)
    st.dataframe(_display_frame(frame), width="stretch", hide_index=True)


def _render_kpi_cards(st, oee) -> None:
    """The four OEE readouts as instrument tiles: A / P / Q / OEE.

    Each tile shows the ratio as a percent plus a one-line derivation caption
    built from the time-breakdown / count fields (the reason those exist,
    per the M4 contract). When a KPI is degenerate M4 records a human note;
    surface it as the caption and show "—" for the value rather than a bare
    0% that reads as a terrible score. Any note not tied to a KPI (e.g. a
    negative-duration warning) is shown as an alert beneath the row.
    """
    notes = oee.notes

    def _note(key: str) -> str | None:
        # ponytail: substring match on note text. Safe for the current note set
        # in oee.compute_oee (no note names another KPI); revisit if M6 adds a
        # note that mentions two KPIs.
        return next((n for n in notes if key in n), None)

    a_note, p_note, q_note = _note("Availability"), _note("Performance"), _note("Quality")

    def _tile(value: float, note: str | None) -> str:
        return "—" if note else f"{value * 100:.1f}%"

    a = _tile(oee.availability, a_note)
    p = _tile(oee.performance, p_note)
    q = _tile(oee.quality, q_note)
    # OEE = A·P·Q; if any factor is undefined, OEE is too (never a bare 0.0%).
    oee_val = "—" if (a_note or p_note or q_note) else f"{oee.oee * 100:.1f}%"

    cards = [
        (
            "Availability", a, a_note,
            f"run {_fmt_seconds(oee.run_time)} · "
            f"{_fmt_seconds(oee.unplanned_stop_time)} unplanned · "
            f"{_fmt_seconds(oee.idle_time)} idle",
        ),
        ("Performance", p, p_note, f"line speed over {_fmt_seconds(oee.run_time)} run"),
        ("Quality", q, q_note, f"{_fmt_num(oee.good)} good · {_fmt_num(oee.reject)} reject"),
        ("OEE", oee_val, None, f"A × P × Q = {a} × {p} × {q}"),
    ]
    cols = st.columns(4)
    for col, (label, value, note, sub) in zip(cols, cards):
        with col:
            st.metric(label, value)
            st.caption(note if note else sub)
    leftover = [
        n for n in notes
        if not any(k in n for k in ("Availability", "Performance", "Quality"))
    ]
    if leftover:
        st.warning(" · ".join(leftover))


def _render_pareto(st, px, go, oee) -> None:
    """Bottles-lost Pareto: downtime priced at target speed, ranked.

    Color by message (ADR-0010 decision 10): the bars share the problem-orange
    family, tiered by cumulative impact (vital few / middle / tail) — the eye
    reads how few causes drive most of the loss before it reads a single
    number. Planned causes never appear (they aren't priced; ADR-0003). A
    cumulative-% line on a right axis completes the classic Pareto.

    The left axis title is set inline (not via the shared _axis_title helper):
    _axis_title calls update_yaxes with no selector, which would also rewrite
    the secondary yaxis2 and clobber its "cumulative %" title.
    """
    causes, bottles, cum = _pareto_series(oee)
    # nothing to price: either no unplanned cause, or all causes priced at 0
    # (e.g. speed_target unmapped -> target 0). Skip the figure rather than draw
    # zero-height bars with a stray empty cumulative line.
    if not bottles or not cum:
        st.caption(
            "No bottles lost to price (no unplanned downtime, or target speed "
            "is zero/unmapped)."
        )
        return
    tier_colors = _loss_color_map(causes, bottles, planned_causes=set())
    fig = px.bar(x=causes, y=bottles)  # inherits the instrument template
    fig.update_traces(
        marker_color=[tier_colors[c] for c in causes],
        marker_line_width=2, marker_line_color=_PANEL,
        text=[_fmt_num(v) for v in bottles], textposition="outside",
        textfont=dict(family="IBM Plex Mono", size=11, color=_INK),
        hovertemplate="%{x}: %{y:,.0f} bottles<extra></extra>",
        name="Bottles lost",
    )
    fig.add_trace(go.Scatter(
        x=causes, y=cum, yaxis="y2", name="Cumulative %",
        mode="lines+markers+text",
        line=dict(color=_PRIMARY, width=2), marker=dict(size=7, color=_PRIMARY),
        text=[f"{p:.0f}%" for p in cum], textposition="top center",
        textfont=dict(family="IBM Plex Mono", size=10, color=_INK_MUTED),
        hovertemplate="cumulative: %{y:.1f}%<extra></extra>",
    ))
    fig.update_layout(
        title="Bottles lost by stop cause (Pareto)",
        yaxis_title_text="bottles lost",
        yaxis_title_standoff=14,
        yaxis_title_font=dict(size=10.5, color=_INK_MUTED),
        yaxis2=dict(
            title_text="cumulative %", overlaying="y", side="right",
            range=[0, 105], showgrid=False, title_standoff=14,
            tickfont=dict(family="IBM Plex Mono", size=10.5, color=_INK_MUTED),
        ),
        showlegend=False,
    )
    _axis_title(fig, "x", "stop cause")
    fig.update_xaxes(tickangle=-30)  # M8 node 9: long cause names read clear
    _show(st, fig)
    st.caption(
        f"{_fmt_num(sum(bottles))} bottles lost — stop time × target speed, "
        f"unplanned causes only (planned stops are excluded, not priced). "
        f"The vital few burn brightest: tiers split the loss at 50% and 80% "
        f"cumulative."
    )


def _render_whatif(st, result):
    """M6/M8: drag a top stop cause's downtime down; OEE + bottles recompute live.

    One 0–100% reduction slider per cause in the top-N of the baseline
    bottles_lost (the Pareto's biggest bars). On any change, ``whatif``
    re-prices OEE off the pure ``compute_oee`` core (ADR-0005: freed time
    becomes run at the line's current speed, Performance/Quality held). The
    hypothetical reuses the KPI cards for the live A/P/Q/OEE, plus a
    bottles-recovered readout vs the baseline stored at Analyze.

    Returns ``(baseline, hypo, reductions)`` so the Act 3 future-line + lever
    waterfall (M8) can reuse the scenario without re-deriving — a single source
    of truth for the what-if the three Act-3 views must not disagree on. The
    return is ``None`` when there is no baseline / no priced stops (the early
    ``st.info`` branches); Act 3 then renders no scenario charts (the forecast
    still does — it needs only ``production_totals``, not OEE).
    """
    baseline = result["oee"]
    if baseline is None:
        st.info(
            "What-if needs OEE — map a **STATE** column and a time basis "
            "(see the Now section) to model downtime reductions."
        )
        return None
    top = baseline.bottles_lost[:_WHATIF_TOP_N]
    if not top:
        st.info("No unplanned downtime is priced, so there is nothing to cut.")
        return None
    # The sticky slider rail (ADR-0010 decision 2): caption + sliders in a
    # nested container whose [data-ll=sliderrail] anchor the zone CSS pins —
    # the levers stay on screen while the cards, the future-line chart, and
    # the waterfall scroll under, and release at the Future-line zone's end.
    with st.container():
        st.markdown('<div data-ll="sliderrail"></div>', unsafe_allow_html=True)
        st.caption(
            "Cut a cause's unplanned downtime and OEE recomputes live. Freed time "
            "becomes run at the line's current speed — Performance and Quality are "
            "held at baseline (ADR-0005). The sliders below drive the future-line "
            "what-if and the lever waterfall in this section too."
        )
        reductions: dict[str, float] = {}
        cols = st.columns(len(top))
        for col, b in zip(cols, top):
            with col:
                pct = st.slider(b.cause, min_value=0, max_value=100, value=0, format="%d%%")
                if pct:
                    reductions[b.cause] = pct / 100.0
    # baseline wasn't None and has priced stops, so the wrapper can't be None;
    # guard anyway so a future degenerate edge never crashes the page.
    hypo = whatif.whatif_from_context(result["ctx"], reductions)
    if hypo is None:
        return None
    _render_kpi_cards(st, hypo)
    _render_whatif_delta(st, baseline, hypo)
    return baseline, hypo, reductions


def _render_whatif_delta(st, baseline, hypo) -> None:
    """The what-if payoff vs the baseline: bottles recovered + OEE move."""
    recovered = _recovered(baseline, hypo)
    cols = st.columns(2)
    with cols[0]:
        st.metric("Bottles recovered", _fmt_num(recovered))
    with cols[1]:
        st.metric(
            "OEE (what-if)", f"{hypo.oee * 100:.1f}%",
            delta=f"{(hypo.oee - baseline.oee) * 100:+.1f} pts",
        )
    st.caption(
        f"Availability {hypo.availability * 100:.1f}% "
        f"({(hypo.availability - baseline.availability) * 100:+.1f} pts vs baseline) · "
        f"{_fmt_num(hypo.good)} good · Performance/Quality held at baseline."
    )


def _available_scopes(rep) -> list[str]:
    """Which time groupings the data supports: overall always, day if a start
    timestamp is mapped, shift if a shift column is mapped."""
    scopes: set[str] = set()
    for f in (rep.state_totals, rep.downtime_by_reason, rep.production_totals):
        if not f.empty:
            scopes.update(f["scope"].unique().tolist())
    return [s for s in ("overall", "day", "shift") if s in scopes]


def _show(st, fig):
    """Render one chart with the instrument template (theme=None so Streamlit's
    theme never remaps the validated palette)."""
    if fig is not None:
        st.plotly_chart(fig, width="stretch", theme=None)


def _period_label(group_by: str) -> str:
    return {"overall": "", "day": "day", "shift": "shift"}[group_by]


def _axis_title(fig, axis: str, text: str):
    """A recessive, well-spaced axis title so labels never read as 'inside' the
    plot: small muted type with standoff from the ticks."""
    kw = dict(title_text=text, title_standoff=18,
              title_font=dict(size=10.5, color=_INK_MUTED))
    (fig.update_xaxes if axis == "x" else fig.update_yaxes)(**kw)
    return fig


def _state_chart(st, px, frame: pd.DataFrame, group_by: str):
    if frame.empty:
        return
    sub = frame[frame.scope == group_by]
    if sub.empty:
        return
    if group_by == "overall":
        d = sub.sort_values("seconds")  # ascending so the largest lands on top
        fig = px.bar(d, x="seconds", y="state", orientation="h")
        fig.update_traces(
            marker_color=[_STATE_COLOR.get(s, _PRIMARY) for s in d["state"]],
            text=[_fmt_seconds(s) for s in d["seconds"]], textposition="outside",
            textfont=dict(family="IBM Plex Mono", size=11, color=_INK),
            hovertemplate="%{y}: %{x:,.0f}s<extra></extra>",
        )
        fig.update_layout(title="Time in state", showlegend=False)
        _show(st, fig)
        total = float(d["seconds"].sum()) or 1.0
        shares = {r.state: r.seconds / total for r in d.itertuples()}
        st.caption(
            "Where the period's hours went: "
            f"{shares.get('Running', 0.0):.0%} running, "
            f"{shares.get('Stopped', 0.0):.0%} stopped, "
            f"{shares.get('Idle', 0.0):.0%} idle."
        )
    else:
        d = sub.assign(scope_value=sub["scope_value"].astype(str))
        fig = px.bar(d, x="scope_value", y="seconds", color="state", barmode="stack",
                     color_discrete_map=_STATE_COLOR,
                     category_orders={"scope_value": sorted(d["scope_value"].unique())})
        # 2px surface gap between stacked segments (dataviz mark spec)
        fig.update_traces(marker_line_width=2, marker_line_color=_PANEL)
        fig.update_layout(title="Time in state")
        _axis_title(fig, "x", _period_label(group_by))
        _show(st, fig)
        st.caption("How the running / stopped / idle split shifts across the window.")


# Ranges wider than this many days render the state timeline as daily
# state-composition bars; narrower ranges render the true interval Gantt
# (ADR-0010 decision 8). At 6-month scale the Gantt is confetti (~9k
# intervals); the composition bars keep the Running/Stopped/Idle split the
# alarms narrative needs (a calendar heatmap was rejected for hiding it).
_TIMELINE_MAX_GANTT_DAYS = 14


def _state_timeline(st, px, ctx):
    """The chronological 'what happened' view — adaptive by range width
    (ADR-0010 decision 8). Wide ranges render daily state-composition bars
    (Running/Stopped/Idle share per day); ranges of a couple of weeks or less
    render the true interval timeline (a Gantt strip). Needs a start timestamp,
    a state column, and an end timestamp (or a duration column to derive one)."""
    start = ctx.mapping.source_for(CanonicalRole.TIMESTAMP_START)
    end = ctx.mapping.source_for(CanonicalRole.TIMESTAMP_END)
    dur = ctx.mapping.source_for(CanonicalRole.DURATION)
    state = ctx.mapping.source_for(CanonicalRole.STATE)
    machine = ctx.mapping.source_for(CanonicalRole.MACHINE_ID)
    if not (start and state and (end or dur)):
        return
    cols = [c for c in (start, end, state, machine) if c]
    df = ctx.data[cols].copy()
    df[start] = pd.to_datetime(df[start])
    if end:
        df[end] = pd.to_datetime(df[end])
    else:
        df[end] = df[start] + pd.to_timedelta(
            pd.to_numeric(ctx.data[dur], errors="coerce"), unit="s")
    span_days = (df[end].max() - df[start].min()).days
    if span_days > _TIMELINE_MAX_GANTT_DAYS:
        _state_composition_chart(st, px, df, start, end, state)
        return
    df["lane"] = df[machine].astype(str) if machine else "State"
    fig = px.timeline(df, x_start=start, x_end=end, y="lane", color=state,
                      color_discrete_map=_STATE_COLOR)
    fig.update_xaxes(title_text=None)
    fig.update_yaxes(title_text=None, showticklabels=bool(machine))
    fig.update_layout(title="State timeline", showlegend=df[state].nunique() > 1,
                      height=150 + 56 * df["lane"].nunique())
    _show(st, fig)
    st.caption("Every state change in the selected window, in order.")


def _state_composition_chart(st, px, df, start: str, end: str, state: str):
    """The wide-range state timeline: one stacked bar per day showing the
    Running/Stopped/Idle share (ADR-0010 decision 8).

    Built from the same frame the Gantt would use: each interval's duration is
    attributed to its start's calendar day (the same bucketing
    ``daily_duration_exceeds_86400`` uses), so the shares sum to the covered
    time per day. State colors stay the fixed canonical map (ADR-0008).
    """
    d = df.assign(
        day=df[start].dt.floor("D").dt.strftime("%Y-%m-%d"),
        seconds=(df[end] - df[start]).dt.total_seconds(),
    )
    daily = d.groupby(["day", state], as_index=False)["seconds"].sum()
    fig = px.bar(daily, x="day", y="seconds", color=state, barmode="stack",
                 color_discrete_map=_STATE_COLOR,
                 category_orders={"day": sorted(daily["day"].unique())})
    fig.update_traces(
        marker_line_width=1, marker_line_color=_PANEL,
        hovertemplate="%{x}: %{y:,.0f}s<extra></extra>",
    )
    fig.update_layout(title="State timeline — daily composition",
                      xaxis=dict(tickangle=-45, nticks=24))
    _axis_title(fig, "y", "seconds / day")
    _show(st, fig)
    st.caption(
        "Each day's share of running, stopped, and idle time — the whole "
        "period at a glance. Narrow the date range to ~2 weeks for the "
        "interval-by-interval timeline."
    )


def _downtime_chart(st, px, frame: pd.DataFrame, group_by: str, planned: set[str]):
    if frame.empty:
        return
    sub = frame[frame.scope == group_by]
    if sub.empty:
        return
    # Color by message (ADR-0010): the problem-orange family tiered by impact,
    # planned causes neutral. The tier map is built on the whole selection's
    # totals so a cause keeps its color across the overall/stacked views.
    totals = sub.groupby("reason")["seconds"].sum()
    cmap = _loss_color_map(list(totals.index), list(totals.values), planned)
    if group_by == "overall":
        d = sub.sort_values("seconds", ascending=True)  # biggest cause on top
        fig = px.bar(d, x="seconds", y="reason", orientation="h")
        fig.update_traces(
            marker_color=[cmap.get(r, _DOWN) for r in d["reason"]],
            text=[_fmt_seconds(s) for s in d["seconds"]], textposition="outside",
            textfont=dict(family="IBM Plex Mono", size=11, color=_INK),
            hovertemplate="%{y}: %{x:,.0f}s<extra></extra>",
        )
        fig.update_layout(title="Downtime by reason", showlegend=False)
    else:
        d = sub.assign(scope_value=sub["scope_value"].astype(str))
        fig = px.bar(d, x="scope_value", y="seconds", color="reason", barmode="stack",
                     color_discrete_map=cmap,
                     category_orders={"scope_value": sorted(d["scope_value"].unique())})
        fig.update_traces(marker_line_width=2, marker_line_color=_PANEL)
        fig.update_layout(title="Downtime by reason")
        _axis_title(fig, "x", _period_label(group_by))
    _show(st, fig)
    st.caption(
        "What stops the line, ranked — the brighter the orange, the bigger the "
        "share of the loss; grey is planned time (scheduled, not a loss)."
    )


def _forecast_traces(go, view: "_ForecastView", yfmt: str = ":,.0f"):
    """The forecast overlay as plotly traces (ADR-0006/0007): a dashed central
    line over observed days + horizon, and a translucent widening band over the
    future, anchored at the last observed day.

    Pure plotly construction — no streamlit — so the trace shape is testable
    without the ``ui`` extra. Takes a ``_ForecastView`` (technique-agnostic); the
    trace construction is identical for the learned median and the deterministic
    line — only the central series source differs, already normalized upstream.
    ``yfmt`` is the plotly format for the band's range hover (default integer
    bottles; the degradation chart passes a percent format for the Performance
    ratio). Returns the traces in add-order (upper before lower so the lower
    trace's ``fill='tonexty'`` shades the ribbon) plus the ordered ISO-date
    category array that pins the x-axis order (real days then horizon days)."""
    line_x = [d.isoformat() for d in view.line_dates]
    band_x = [d.isoformat() for d in view.band_dates]
    name = "Median forecast" if view.technique == "gradient-boosted" else "7-day trend"
    trend = go.Scatter(
        x=line_x, y=list(view.central), mode="lines",
        line=dict(color=_INK_MUTED, width=2, dash="dash"), name=name,
        hoverinfo="skip",  # a visual guide only — never a bare future number (ADR-0002/0006/0007)
    )
    upper = go.Scatter(
        x=band_x, y=list(view.upper), mode="lines",
        line=dict(width=0), showlegend=False, hoverinfo="skip",
    )
    band_label = "conformal band" if view.technique == "gradient-boosted" else "±1σ band"
    lower = go.Scatter(
        x=band_x, y=list(view.lower), mode="lines", line=dict(width=0),
        fill="tonexty", fillcolor="rgba(57,135,229,0.14)",
        name=band_label, showlegend=True,
        customdata=[[u] for u in view.upper],
        hovertemplate=f"%{{x}}: %{{y{yfmt}}}–%{{customdata[0]{yfmt}}} (band)<extra></extra>",
    )
    return [trend, upper, lower], line_x


def _future_line_chart(st, go, frame: pd.DataFrame, baseline, hypo, reductions):
    """Act 3 (M8): the future line — observed daily good output continued as a
    banded forecast into the horizon, with the what-if overlaid as a hypothetical
    line when sliders have moved.

    The forecast is the learned model when there is ≥~3 months of daily history
    (ADR-0007), else the deterministic Projection (ADR-0006); ``_resolve_forecast``
    picks. It always trains on the *full* dated series (frame is the un-scoped
    production_totals; the P2 date picker scopes the Now charts only — leak
    guard). The what-if line spreads the recovered bottles across the horizon in
    proportion to the forecast level (node 4 — preserves the weekly shape), so
    it reads as the same line lifted, never a separate prediction.

    Honest by construction (ADR-0002/0006/0007): the central line hover is off (a
    visual guide), the band hover shows a *range*, and the what-if line is
    labelled hypothetical — a future day never surfaces a single confident number
    except as the bars' observed actuals. Pure-ish figure construction routed
    through ``_show``; the trace shape is testable without the ``ui`` extra."""
    series = _daily_good_series(frame)
    if series is None:
        st.caption("No daily good-parts series to forecast.")
        return
    dates, values = series
    view, reason = _resolve_forecast(dates, values)
    if view is None:
        # Distinct honesty captions: too-little history vs zero observed
        # scatter (ADR-0002's defining edge — a band that collapses to the line
        # would read as a single confident future number).
        if reason == "zero_scatter":
            st.caption(
                "The daily series fits a line with no observed scatter, so a "
                "statistical band can't bound the projection — and a trend line "
                "alone would read as a confident prediction, which it isn't. No "
                "forecast is drawn; the bars show the actual daily output.")
        else:
            st.caption(
                f"Not enough daily history to project a trend "
                f"(need ≥ {_FORECAST_MIN_DAYS} days).")
        return
    observed_x = [d.isoformat() for d in dates]
    fig = go.Figure()
    # observed good output as bars — the actuals a future day is never reduced to
    fig.add_trace(go.Bar(
        name="Good", x=observed_x, y=values, marker_color=_HONEST,
        marker_line_width=2, marker_line_color=_PANEL,
        hovertemplate="%{x}: %{y:,.0f} good<extra></extra>"))
    traces, cat_order = _forecast_traces(go, view)
    for t in traces:
        fig.add_trace(t)
    fig.update_xaxes(categoryorder="array", categoryarray=cat_order)
    _axis_title(fig, "y", "good bottles / day")

    # The hypothetical what-if line: the forecast continued, lifted across the
    # horizon by the proportionally-spread recovered bottles. Only drawn when a
    # slider has freed bottles (recovered > 0); zero-slider -> it would coincide
    # with the median, so we omit it rather than draw a duplicate.
    recovered = _recovered(baseline, hypo) if (baseline is not None and hypo is not None) else 0.0
    if recovered > 1e-9:
        horizon_central = view.central[-_FORECAST_HORIZON_DAYS:]
        whatif_y = list(view.central[:-_FORECAST_HORIZON_DAYS]) + whatif.spread_recovered(
            horizon_central, recovered)
        fig.add_trace(go.Scatter(
            x=cat_order, y=whatif_y, mode="lines",
            line=dict(color=_HONEST, width=2.5, dash="dot"),
            name="What-if (hypothetical)",
            hovertemplate="%{x}: %{y:,.0f} (hypothetical — slider scenario)<extra></extra>",
        ))
    fig.update_layout(title="Future line: observed good output + banded forecast")
    _show(st, fig)

    # Caption is technique-aware and explicitly never-confident (ADR-0002).
    if view.technique == "gradient-boosted":
        cap = (f"Learned median (gradient-boosted) drawn {_FORECAST_HORIZON_DAYS} days "
               f"ahead inside a widening conformal band. The band — not the line — "
               f"is the forecast: where daily good output is heading, within "
               f"growing calibrated uncertainty. A learned projection, not a "
               f"prediction of what will happen (ADR-0007).")
    else:
        cap = (f"Dashed line: the period's trend (≈ {view.slope:+,.0f} good "
               f"bottles/day, r² = {view.r_squared:.2f}), drawn "
               f"{_FORECAST_HORIZON_DAYS} days ahead inside a widening ±1σ band. "
               f"The band — not the line — is the forecast: where daily good "
               f"output is heading, within growing uncertainty. A projection of "
               f"the recent trend, not a prediction of what will happen.")
    if recovered > 1e-9:
        cap += (f" The dotted what-if line spreads {_fmt_num(recovered)} recovered "
                f"bottles across the horizon in proportion to the forecast level "
                f"(preserves the weekly shape).")
    # no "will be <number>" — a future day is never a single confident value.
    st.caption(cap)


def _lever_waterfall(st, go, baseline, hypo, reductions: dict[str, float]):
    """Act 3 (M8): the lever waterfall — a recovered-bottle bridge from zero,
    through one floating +Δ per moved cause, to the what-if's recovered total
    (node 3: "where the recovered bottles come from").

    Each floating bar is that lever's recovered bottles (``base_bl[c] −
    hypo_bl[c]``); summed they equal ``_recovered`` — the bridge's closing
    anchor — so the ``go.Waterfall`` closes exactly (the plan.md P4 verify
    clause). Recovered bottles (a cause's downtime repriced away at target speed)
    are a *different quantity* from the good parts the freed time adds (priced at
    the line's actual effective speed × Q, ADR-0005 Oracle 1) — ~10% apart on the
    sample month — so the bridge is drawn in recovered bottles end to end and
    never mixes in baseline/hypo good. Mixing the two was the overshoot-and-snap
    defect this replaced. The good-parts lift lives on the future-line what-if
    line, not here. No sliders moved -> nothing recovered to decompose, so no
    figure (just a caption), mirroring the future-line chart's ``recovered>0``
    gate."""
    if baseline is None or hypo is None:
        return
    deltas = _lever_deltas(baseline, hypo, reductions)
    if not deltas:
        st.caption(
            "No lever moved — drag a Future-line slider to see where the "
            "recovered bottles come from, cause by cause."
        )
        return
    recovered = _recovered(baseline, hypo)  # the closing anchor (single source of truth)
    measure = ["relative"] * len(deltas) + ["absolute"]  # Δs build up to the total
    x = [c for c, _ in deltas] + ["Recovered"]
    y = [d for _, d in deltas] + [recovered]
    text = [_fmt_num(v) for v in y]
    fig = go.Figure(go.Waterfall(
        x=x, y=y, measure=measure, text=text, textposition="outside",
        textfont=dict(family="IBM Plex Mono", size=11, color=_INK),
        increasing=dict(marker=dict(color=_HONEST)),
        decreasing=dict(marker=dict(color=_DOWN)),
        totals=dict(marker=dict(color=_HONEST)),  # Recovered anchor = recovered bottles too
        connector=dict(line=dict(color="rgba(255,255,255,0.16)")),
        hovertemplate="%{x}: %{y:,.0f} bottles<extra></extra>",
    ))
    fig.update_layout(
        title="Where the recovered bottles come from (lever waterfall)",
        showlegend=False,
    )
    _axis_title(fig, "y", "bottles recovered")
    fig.update_xaxes(tickangle=-30)  # long cause names read clear (node 9)
    _show(st, fig)
    n = len(deltas)
    st.caption(
        f"{n} lever{'s' if n != 1 else ''} moved, recovering "
        f"{_fmt_num(recovered)} bottles cause-by-cause — each bar is that "
        f"cause's downtime repriced away (freed at the held quality ratio, "
        f"ADR-0005). Recovered bottles are not the good parts the freed time "
        f"adds; those lift the future-line what-if line above."
    )


# --- Act 4 (M8, P5): Reliability — degradation forecast + banded MTBF tile ----


def _degradation_chart(st, go, ctx):
    """Act 4 (M8): the Performance-degradation forecast — the dated Performance
    ratio continued as a banded forecast toward a concern threshold.

    Reuses the Act-3 forecast layer (``_resolve_forecast`` / ``_forecast_traces``)
    on ``oee.performance_by_day``, so the same learned-or-deterministic discipline
    + conformal band carries over (the honest "band, not line" framing). A
    concern floor (``_PERFORMANCE_CONCERN``) is drawn; the caption names the first
    horizon day the band's lower edge crosses it, or notes it stays above. Honest
    by construction: the central line hover is off (a guide), the band hover shows
    a *range*, the floor is a concern guide — never a confident 'Performance will
    be X%'. Declines with a caption when there is no series / too few days / zero
    scatter (mirroring the future-line chart's edges)."""
    series = _daily_performance_series(ctx)
    if series is None:
        st.caption("No daily Performance series to forecast (needs STATE, a time "
                   "basis, a start timestamp, and speed columns).")
        return
    dates, values = series
    view, reason = _resolve_forecast(dates, values)
    if view is None:
        if reason == "zero_scatter":
            st.caption("The daily Performance series fits with no observed scatter, "
                       "so a band can't bound the projection — and a line alone would "
                       "read as a confident prediction, which it isn't. No forecast "
                       "is drawn; the bars show the actual daily Performance.")
        else:
            st.caption(f"Not enough daily Performance history to project a trend "
                       f"(need ≥ {_FORECAST_MIN_DAYS} days).")
        return
    observed_x = [d.isoformat() for d in dates]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Performance", x=observed_x, y=values, marker_color=_HONEST,
        marker_line_width=2, marker_line_color=_PANEL,
        hovertemplate="%{x}: %{y:.1%} Performance<extra></extra>"))
    traces, cat_order = _forecast_traces(go, view, yfmt=".1%")
    for t in traces:
        fig.add_trace(t)
    fig.update_xaxes(categoryorder="array", categoryarray=cat_order)
    fig.add_hline(
        y=_PERFORMANCE_CONCERN, line=dict(dash="dot", color=_DOWN, width=1.5),
        annotation_text=f"{_PERFORMANCE_CONCERN:.0%} concern floor",
        annotation_position="top left",
        annotation_font=dict(size=10.5, color=_DOWN, family="IBM Plex Mono"),
        annotation_bgcolor="#0B0F14",  # legible over the bars (instrument tag)
        annotation_bordercolor=_DOWN, annotation_borderwidth=1, annotation_borderpad=3,
    )
    _axis_title(fig, "y", "performance (actual / target speed)")
    fig.update_layout(title="Performance degradation: daily ratio + banded forecast")
    _show(st, fig)
    st.caption(_degradation_caption(view, _threshold_crossing(view, _PERFORMANCE_CONCERN)))


def _mtbf_tile(st, ctx):
    """Act 4 (M8): the banded next-fault tile — MTBF median ± IQR from the Fault
    inter-arrival intervals (ADR-0007's honest ceiling).

    A band, never a precise 'next fault in N days' countdown: fault inter-arrival
    CV ≈ 0.9 on the sample data, so a single number would be a confident lie
    (node 5 rejected the countdown). The median + IQR (central 50%) convey the
    honest spread. Declines with a caption when there are too few Fault events to
    summarize (``mtbf_band``'s floor)."""
    intervals = reliability.fault_intervals(ctx)
    band = reliability.mtbf_band(intervals)
    if band is None:
        st.info(f"Too few Fault events to estimate MTBF — only {len(intervals)} "
                f"inter-arrival interval(s) (need ≥ 4).")
        return
    median, q1, q3 = band
    st.metric("MTBF (median)", _fmt_span(median))
    st.caption(
        f"Typically {_fmt_span(q1)}–{_fmt_span(q3)} between Faults (central 50%, "
        f"from {len(intervals)} inter-arrival intervals). A band, not a countdown — "
        f"fault spacing varies widely (CV ≈ 0.9), so 'next fault in N days' would "
        f"overstate what the data supports. MTBF from Fault stop events is the "
        f"ceiling: the CSV has no labeled failures or degradation sensor (ADR-0007)."
    )


def _maintenance_view(st, result):
    """Act 4 (M9, ADR-0009): the service counter + learned due window.

    The counter always renders (pure bottle arithmetic); the learned service
    interval and the due window appear only with >= 2 service events, with the
    honest thin-data message otherwise (ADR-0009 decision 5 — nothing is
    invented). The report is computed at Analyze time and consumed here; this
    view never recomputes (same contract as the OEE cards). The fallback
    (cached back onto the result) only serves a session_state result from
    before this key existed.
    """
    if "maintenance" not in result:
        result["maintenance"] = maintenance.maintenance_from_context(result["ctx"])
    report = result["maintenance"]
    st.subheader("Maintenance")
    if report is None:
        st.info(
            "Maintenance needs a **start timestamp** and bottle counts "
            "(**good_count** / **reject_count**) mapped — the service counter "
            "is bottle arithmetic."
        )
        return
    cols = st.columns(3)
    with cols[0]:
        st.metric("Bottles since last service", _fmt_num(report.bottles_since_service))
    with cols[1]:
        st.metric("Service events", report.n_service_events)
    with cols[2]:
        if report.interval is not None:
            st.metric("Service interval (median)", _fmt_num(report.interval.median))
    if report.last_service_end is not None:
        st.caption(
            f"Last service ended {report.last_service_end:%Y-%m-%d %H:%M}. "
            + (
                f"The line's service rhythm: typically "
                f"{_fmt_num(report.interval.q1)}–{_fmt_num(report.interval.q3)} "
                f"bottles between services (central 50% of "
                f"{report.interval.n} learned intervals, Maintenance stops + "
                f"repair-length Faults)."
                if report.interval is not None
                else ""
            )
        )
    if report.due is not None:
        head, detail = _due_window_phrasing(report.due)
        st.metric("Next service due", head)
        st.caption(detail)
        # ADR-0009 decision 4: a fired condition signal is ALWAYS stated, even
        # when it couldn't move the window (a single learned interval has no
        # spread to pull within — adjusted_earlier is then False).
        if report.due.adjusted_earlier:
            st.warning("Pulled earlier: " + "; ".join(report.due.reasons) + ".")
        elif report.due.reasons:
            st.info(
                "Condition signal: " + "; ".join(report.due.reasons)
                + " — but the learned rhythm has no spread to pull the window "
                "earlier within (single observed interval)."
            )
    for note in report.notes:
        st.info(note)


def _production_chart(st, px, go, frame: pd.DataFrame, group_by: str):
    if frame.empty:
        return
    if group_by == "overall":
        ov = frame[frame.scope == "overall"]
        good = float(ov.loc[ov.metric == "good", "value"].sum())
        reject = float(ov.loc[ov.metric == "reject", "value"].sum())
        yld = ov.loc[ov.metric == "yield", "value"]
        yld = float(yld.iloc[0]) if not yld.empty else None
        if good + reject <= 0:
            return
        fig = go.Figure(go.Pie(
            labels=["Good", "Rejected"], values=[good, reject], hole=0.62,
            marker=dict(colors=[_HONEST, _REJECT], line=dict(width=2, color=_PANEL)),
            textinfo="percent", textfont=dict(family="IBM Plex Mono", size=11, color=_INK),
            hovertemplate="%{label}: %{value:,.0f} parts<extra></extra>",
        ))
        fig.update_layout(title="Production: good vs rejected", showlegend=True)
        c1, c2 = st.columns([1.2, 1])
        with c1:
            _show(st, fig)
        with c2:
            st.metric("First-pass yield",
                      f"{yld * 100:.1f}%" if yld is not None else "n/a")
            st.caption(f"{_fmt_num(good)} good parts · {_fmt_num(reject)} rejected")
    else:
        d = frame[(frame.scope == group_by) & (frame.metric.isin(["good", "reject"]))]
        if d.empty:
            return
        d = d.assign(scope_value=d["scope_value"].astype(str))
        piv = (d.pivot(index="scope_value", columns="metric", values="value")
                 .reindex(sorted(d["scope_value"].unique())))
        fig = go.Figure()
        fig.add_trace(go.Bar(name="Good", x=piv.index, y=piv.get("good"),
                             marker_color=_HONEST, marker_line_width=2, marker_line_color=_PANEL))
        fig.add_trace(go.Bar(name="Rejected", x=piv.index, y=piv.get("reject"),
                             marker_color=_REJECT, marker_line_width=2, marker_line_color=_PANEL))
        fig.update_layout(barmode="stack", title="Production: good vs rejected")
        _axis_title(fig, "x", _period_label(group_by))
        _axis_title(fig, "y", "parts")
        # P3 (node 2): the forecast left the Now chart — it lives in the Act 3
        # future-line stage (_future_line_chart). The bars here show actual output
        # only; "Now" carries no projection.
        _show(st, fig)
        st.caption(
            "Output per " + _period_label(group_by) +
            " — the good parts and the small rejected cap on top."
        )


def _contrast_chart(go, findings: list[Finding]):
    """The diagnosis, as a dumbbell: honest increase (aqua) vs naive sum (red),
    with the overstatement factor annotated on each red diamond. Returns None
    when no cumulative-totalizer finding exists."""
    rows = _aggregation_contrast_rows(findings)
    if not rows:
        return None
    counters = [r["counter"] for r in rows]
    naive = [float(r["naive sum"]) for r in rows]
    honest = [float(r["honest total"]) for r in rows]
    fig = go.Figure()
    for i, c in enumerate(counters):  # the gap line per counter
        fig.add_trace(go.Scatter(
            x=[honest[i], naive[i]], y=[c, c], mode="lines",
            line=dict(color="rgba(255,255,255,0.16)", width=2),
            showlegend=False, hoverinfo="skip",
        ))
    fig.add_trace(go.Scatter(
        x=honest, y=counters, mode="markers+text",
        marker=dict(size=15, color=_HONEST, symbol="circle"),
        text=[_fmt_num(v) for v in honest], textposition="middle left",
        textfont=dict(color=_HONEST, size=11, family="IBM Plex Mono"),
        name="Honest increase", hovertemplate="honest: %{x:,.0f}<extra></extra>",
    ))
    factors = [f"×{naive[i] / honest[i]:.1f}" if honest[i] else _fmt_num(naive[i])
               for i in range(len(rows))]
    fig.add_trace(go.Scatter(
        x=naive, y=counters, mode="markers+text",
        marker=dict(size=15, color=_NAIVE, symbol="diamond"),
        text=factors, textposition="middle right",
        textfont=dict(color=_NAIVE, size=11, family="IBM Plex Mono"),
        name="Naive sum (dashboard overstatement)",
        hovertemplate="naive sum: %{x:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text="Aggregation contrast: naive sum vs honest total",
                   font=dict(color=_INK, size=15)),
        legend=dict(orientation="h", y=-0.22, x=0),
        height=max(170, 120 + 56 * len(rows)),
    )
    _axis_title(fig, "x", "seconds")
    return fig


def _date_picker(st, span) -> tuple:
    """st.date_input range picker (full span default). Returns (lo, hi); a single
    selected date is treated as a one-day window [d, d]."""
    lo, hi = span
    sel = st.date_input("Date range (Now charts only)", value=(lo, hi),
                        min_value=lo, max_value=hi, key="ll_now_range")
    if isinstance(sel, (list, tuple)):
        return sel[0], sel[-1]
    return sel, sel


def _charts(st, px, go, ctx, rep, findings: list[Finding]):
    _SCOPE_LABEL = {"overall": "Overall", "day": "By day", "shift": "By shift"}
    scopes = _available_scopes(rep)
    start_src = ctx.mapping.source_for(CanonicalRole.TIMESTAMP_START)
    span = _date_span(ctx, start_src)

    group_by = "overall"
    lo = hi = None
    has_group = len(scopes) > 1

    # Sticky Now-filter bar (Group-by + date range). CSS in _INSTRUMENT_CSS pins
    # the st.container holding the [data-ll=filterbar] anchor. Streamlit-DOM
    # driven, so verified in-browser (node 6 risk); fallback = sticky-top for both.
    # Only rendered when there is at least one control (a window or >1 scope).
    if has_group or span:
        with st.container():
            st.markdown('<div data-ll="filterbar"></div>', unsafe_allow_html=True)
            if has_group and span:
                c_grp, c_date = st.columns([1, 1])
                with c_grp:
                    choice = st.radio("Group by", [_SCOPE_LABEL[s] for s in scopes],
                                      horizontal=True, label_visibility="collapsed")
                with c_date:
                    lo, hi = _date_picker(st, span)
                group_by = {_SCOPE_LABEL[s]: s for s in scopes}[choice]
            elif has_group:
                choice = st.radio("Group by", [_SCOPE_LABEL[s] for s in scopes],
                                  horizontal=True, label_visibility="collapsed")
                group_by = {_SCOPE_LABEL[s]: s for s in scopes}[choice]
            elif span:
                lo, hi = _date_picker(st, span)
            st.caption(
                "Recompute per window; the date range scopes these charts only. "
                "The aggregation-contrast diagnosis always covers the whole dataset.")

    scoped_ctx, narrowed = _scoped_ctx(ctx, start_src, lo, hi)
    scoped = summaries.summarize(scoped_ctx) if narrowed else rep

    # M8: the aggregation-contrast diagnosis was lifted out to the (pre-act)
    # Diagnosis section — it's whole-dataset and never date-scoped, so it doesn't
    # belong under the Now charts. `findings` is kept on the signature for API
    # stability but is no longer used here.
    _state_chart(st, px, scoped.state_totals, group_by)
    _state_timeline(st, px, scoped_ctx)
    _downtime_chart(st, px, scoped.downtime_by_reason, group_by,
                    _planned_causes(scoped_ctx))
    _production_chart(st, px, go, scoped.production_totals, group_by)


if __name__ == "__main__":
    main()
