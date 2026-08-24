"""LineLens — pure, UI-free presentation logic shared by the Streamlit app
(``app.py``, which re-exports these names) and the FastAPI backend.

Everything here is free of streamlit/plotly/fastapi: pandas + stdlib +
``linelens`` only, so the module imports without the ``ui`` extra and every
helper is unit-testable in the core suite (tests/test_server_logic.py).
Plotly trace construction (``_forecast_traces``) and every ``st``-taking
render function stay in ``app.py``.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pandas as pd

from linelens import forecast
from linelens.models import (
    CanonicalRole,
    ColumnMapping,
    DatasetProfile,
    Finding,
    ParseError,
    Severity,
)
from linelens.oee import performance_by_day

# How many of the Pareto's top stop causes become what-if sliders (ADR-0005).
# The top 5 cover ~98% of recoverable bottles on the sample month; the tail
# isn't an actionable lever. Planned causes never qualify (absent from
# bottles_lost).
_WHATIF_TOP_N = 5

# M7/M8: banded forecast of daily good production. M8 (ADR-0007) supersedes the
# M7 deterministic line with a learned GBR median + conformal band when there is
# ≥~3 months of daily history; the deterministic Projection (ADR-0006) stays the
# thin-data fallback. Horizon = days extrapolated past the last observed day;
# _FORECAST_MIN_DAYS = least history to fit a deterministic trend at all (ML
# needs ≥90, its own floor inside forecast_ml).
_FORECAST_HORIZON_DAYS = 7
_FORECAST_MIN_DAYS = 7

# M8 Act 4: the Performance concern floor — a ratio (actual / target speed)
# below which the line is materially off target. The degradation forecast flags
# where its band crosses this. CONTEXT.md's Performance is a ratio in [0, 1].
# ponytail: a fixed default; make it a Future-line-style control if a real ask
# needs a line-specific (target-speed-relative) floor rather than an absolute.
_PERFORMANCE_CONCERN = 0.85

# Color tokens shared with app.py's design system (single source of truth here
# so the API and the Streamlit charts can never disagree). _INK_MUTED and _DOWN
# are validated palette slots (see app.py's design-system notes); the loss
# tiers implement color-by-message (M9, ADR-0010 decision 10): loss charts
# (Pareto, downtime-by-reason) share the problem-orange family, tiered by
# impact (vital few / middle / tail, cumulative 50%/80% Pareto splits); planned
# causes (Changeover, Maintenance) are neutral — "scheduled, not a loss".
# _DOWN is the existing validated slot; the two new shades passed the
# ΔE/CVD validator (.scratch/m9/p6_palette_validator.py): pairwise ΔE ≥ 15
# normal vision, ≥ 10 under protanopia/deuteranopia/tritanopia.
_INK_MUTED = "#6B7B8F"
_DOWN = "#d95926"         # slot 6 (orange) — downtime / problems
_LOSS_STRONG = "#F5956A"  # dominant loss (vital few)
_LOSS_DEEP = "#8F3413"    # the tail
_LOSS_TIERS = (_LOSS_STRONG, _DOWN, _LOSS_DEEP)
_LOSS_TIER_SPLITS = (0.50, 0.80)  # cumulative-share tier boundaries


def _has_time_basis(roles: dict[CanonicalRole, str]) -> bool:
    # ponytail: mirrors summaries._event_durations's source rule -- a time basis
    # exists iff a DURATION column OR both timestamps are mapped. Keep aligned if
    # the duration fallback changes.
    return (
        CanonicalRole.DURATION in roles
        or (
            CanonicalRole.TIMESTAMP_START in roles
            and CanonicalRole.TIMESTAMP_END in roles
        )
    )


def _capabilities(mapping: ColumnMapping) -> dict[str, bool]:
    """Which analyses the current mapping enables (brief §6: tell the user what
    they'll get before they run)."""
    roles = mapping.roles
    has_time = _has_time_basis(roles)
    return {
        "State totals": CanonicalRole.STATE in roles and has_time,
        "Production totals": (
            CanonicalRole.GOOD_COUNT in roles and CanonicalRole.REJECT_COUNT in roles
        ),
        "Downtime by cause": CanonicalRole.STOP_CAUSE in roles and has_time,
        "Daily grouping": CanonicalRole.TIMESTAMP_START in roles,
        "Shift grouping": CanonicalRole.SHIFT in roles,
        "Counter findings": len(mapping.counters) > 0,
    }


def _numeric_counter_options(profile: DatasetProfile) -> list[str]:
    """Numeric columns eligible to be designated as counters.

    Counters must be numeric; offering machine_id / state / timestamps is
    misleading (previously the multiselect listed every column). Filtered by
    pandas dtype string -- int*/float* families, including nullable Int*/Float*
    and unsigned uint*/UInt*.
    """
    numeric_prefixes = ("int", "float", "Int", "Float", "uint", "UInt")
    return [
        c for c in profile.columns if profile.dtypes.get(c, "").startswith(numeric_prefixes)
    ]


def _severity_counts(findings: list[Finding]) -> dict[str, int]:
    counts = {s.value: 0 for s in Severity}
    for f in findings:
        counts[f.severity.value] += 1
    return counts


def _aggregation_contrast_rows(findings: list[Finding]) -> list[dict]:
    """One {counter, naive sum, honest total} row per cumulative-totalizer
    finding, to drive the §5 contrast chart."""
    rows = []
    for f in findings:
        if f.rule_id == "CUMULATIVE_TOTALIZER_SUMMED":
            rows.append(
                {
                    "counter": f.signal,
                    "naive sum": f.evidence.get("naive_sum"),
                    "honest total": f.calculated_value,
                }
            )
    return rows


def _mapping_fingerprint(name: str, mapping: ColumnMapping) -> tuple:
    """A hashable snapshot of the file + mapping, to invalidate stale results."""
    roles = tuple(sorted((r.value, c) for r, c in mapping.roles.items()))
    return (name, roles, mapping.counters)


def _is_mapping_key(key: str) -> bool:
    """Does this session_state key hold a mapping selection (vs. results/cache/prefs)?

    The role selectboxes use `role::{col}` and the counter multiselect uses the
    fixed key `counters`. These are the only keys that must reset when a new
    file is uploaded, so the previous file's column choices don't leak in.
    """
    return key == "counters" or key.startswith("role::")


def _clean_parse_error(exc: ParseError, tmp_path: Path) -> str:
    """Drop the temp-file name from a ParseError so the alert shows the real
    reason, not the throwaway path ingestion loaded from.

    ingestion.load_csv builds messages like "failed to parse <tmp>: <reason>"
    or "failed to decode <tmp> as any of ...: <reason>"; the <tmp> token is an
    implementation detail of _load_uploaded (a NamedTemporaryFile) and leaks a
    confusing name such as "tmpv7nr8lp1.csv" into the user-facing alert. Strip
    it; the underlying reason ("Could not determine delimiter", etc.) remains.
    """
    msg = str(exc).replace(str(tmp_path), "").replace(tmp_path.name, "")
    # collapse the leftover "failed to parse : " / "failed to decode  as ..." phrasing
    msg = msg.replace("failed to parse : ", "").replace("failed to parse :", "")
    msg = msg.replace("failed to decode  as ", "failed to decode as ")
    msg = msg.strip()
    # if stripping the path left only a dangling lead-in (e.g. "file not found:")
    # with no reason after it, the original message is clearer than the stub.
    return msg if msg and not msg.endswith(":") else str(exc)


def _fmt_seconds(s) -> str:
    """Seconds as an instrument readout: '2h 15m' / '45m' / '30s'."""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    s = float(s)
    if s < 60:
        return f"{s:.0f}s"
    if s < 3600:
        return f"{s / 60:.0f}m"
    h, m = divmod(int(s), 3600)
    return f"{h}h {m // 60:02d}m"


def _fmt_num(n) -> str:
    """Compact tabular number: '87,000' / '75' / '96.4'."""
    if n is None or (isinstance(n, float) and pd.isna(n)):
        return ""
    n = float(n)
    if abs(n) >= 1000:
        return f"{n:,.0f}"
    if n == int(n):
        return f"{int(n)}"
    return f"{n:,.1f}"


def _fmt_span(s) -> str:
    """A readout for MTBF-scale spans: '15.8h' / '6m' / '2.3d'.

    ``_fmt_seconds`` caps at hours ('16h 00m'); fault inter-arrival can be days,
    so this is days-aware for the reliability tile."""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    s = float(s)
    if s < 60:
        return f"{s:.0f}s"
    if s < 3600:
        return f"{s / 60:.0f}m"
    if s < 2 * 86400:
        return f"{s / 3600:.1f}h"
    return f"{s / 86400:.1f}d"


def _auto_roles(suggestions: dict) -> dict[CanonicalRole, str]:
    """The silent auto-map: one role per column, conflicts to the highest
    confidence (ties keep the first column in file order).

    ``schema.suggest_roles`` scores each column independently, so two columns
    can win the same role (e.g. "good" and "good_count" both scoring
    GOOD_COUNT); the auto-map must produce a conflict-free mapping or
    ``validate_mapping`` would gate Analyze on a decision the user never made
    (ADR-0010: zero required decisions).
    """
    best: dict[CanonicalRole, tuple[str, float]] = {}
    for col, (role, conf) in suggestions.items():
        if role is None:
            continue
        if role not in best or conf > best[role][1]:
            best[role] = (col, conf)
    return {role: col for role, (col, _conf) in best.items()}


def _auto_counters(profile: DatasetProfile, roles: dict[CanonicalRole, str]) -> list[str]:
    """Preselected counter columns: numeric columns the role map didn't claim.

    Role-mapped numerics (durations, counts, speeds) are measures, not
    odometers; the leftovers (e.g. a machine's Bottles_Counter) are exactly the
    cumulative-totalizer candidates the counter analysis exists for.
    """
    mapped = set(roles.values())
    return [c for c in _numeric_counter_options(profile) if c not in mapped]


def _single_machine_col(raw: pd.DataFrame, roles: dict[CanonicalRole, str]) -> str | None:
    """The machine_id column when it holds exactly one machine, else None.

    A single-machine file has nothing to pick: the role is auto-mapped and the
    selectbox is hidden from the mapping expander (ADR-0010 decision 9).
    """
    col = roles.get(CanonicalRole.MACHINE_ID)
    if col is not None and col in raw.columns and raw[col].nunique(dropna=False) == 1:
        return col
    return None


def _preview_summary(raw: pd.DataFrame, profile: DatasetProfile,
                     roles: dict[CanonicalRole, str]) -> str:
    """The plain-words auto-map summary (ADR-0010): rows, date span, machines,
    recipes, recognized roles — and what wasn't recognized, stated honestly
    rather than silently dropped."""
    parts = [f"**{profile.row_count:,} rows**"]
    start_col = roles.get(CanonicalRole.TIMESTAMP_START)
    if start_col is not None and start_col in raw.columns:
        ts = pd.to_datetime(raw[start_col], format="mixed", errors="coerce").dropna()
        if not ts.empty:
            days = (ts.max() - ts.min()).days + 1
            parts.append(f"**{ts.min():%Y-%m-%d} → {ts.max():%Y-%m-%d}** ({days} days)")
    machine_col = roles.get(CanonicalRole.MACHINE_ID)
    if machine_col is not None and machine_col in raw.columns:
        values = sorted(str(v) for v in raw[machine_col].dropna().unique())
        n = len(values)
        label = f"{n} machine" + ("s" if n != 1 else "")
        if 0 < n <= 3:
            label += f" ({', '.join(values)})"
        parts.append(f"**{label}**")
    recipe_col = roles.get(CanonicalRole.RECIPE)
    if recipe_col is not None and recipe_col in raw.columns:
        n = raw[recipe_col].nunique()
        parts.append(f"**{n} recipe" + ("s" if n != 1 else "") + "**")
    recognized = ", ".join(sorted(r.value for r in roles))
    sentence = " · ".join(parts) + f". Recognized: {recognized}."
    unrecognized = [c for c in profile.columns if c not in set(roles.values())]
    if unrecognized:
        sentence += (" Not recognized: " + ", ".join(unrecognized)
                     + " — selectable as counters below, or ignored.")
    return sentence


def _display_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """A display copy of a totals frame, safe for st.dataframe's Arrow path.

    summaries builds `scope_value` as an object column mixing None (overall),
    datetime.date (day), and str (shift). pandas-3/pyarrow cannot infer a
    common type for that mix and st.dataframe raises ArrowTypeError (logged as
    a traceback on every Analyze). Coerce scope_value to strings for display --
    dates render as ISO "YYYY-MM-DD", overall as an empty cell -- so the typed
    library contract (None/date/str) is untouched while the UI column is
    uniform. The original frame is never mutated (brief: raw & results immutable).
    """
    if "scope_value" not in frame.columns:
        return frame
    out = frame.copy()
    out["scope_value"] = out["scope_value"].map(
        lambda v: "" if v is None else v.isoformat() if hasattr(v, "isoformat") else str(v)
    )
    return out


def _pareto_series(oee) -> tuple[list[str], list[float], list[float]]:
    """Pure prep for the Pareto: causes, bottles, cumulative %, in ranked order.

    Factored out of ``_render_pareto`` so the ranking + cumulative math is unit-
    testable without plotly. ``bottles_lost`` is already sorted descending by
    bottles (M4 contract); this preserves that order and derives the running
    percentage. Returns three empty lists when there's nothing to price.
    """
    bl = oee.bottles_lost
    if not bl:
        return [], [], []
    causes = [b.cause for b in bl]
    bottles = [b.bottles for b in bl]
    total = sum(bottles)
    if total <= 0:
        return causes, bottles, []
    running = 0.0
    cum: list[float] = []
    for v in bottles:
        running += v
        cum.append(running / total * 100)
    return causes, bottles, cum


def _recovered(baseline, hypo) -> float:
    """Bottles recovered by a what-if vs the baseline (ADR-0005):

    ``recovered = Σ_c (baseline_bl[c] − hypo_bl[c])`` over all priced causes —
    exactly the freed bottles, since a cause cut by ``r`` drops its bottles-lost
    by ``r`` (linear in ``r``, additive across causes). The single source of
    truth shared by the what-if delta readout, the future-line spread, and the
    lever waterfall so they can never disagree. Pure (no UI)."""
    base_bl = {b.cause: b.bottles for b in baseline.bottles_lost}
    new_bl = {b.cause: b.bottles for b in hypo.bottles_lost}
    return sum(v - new_bl.get(c, 0.0) for c, v in base_bl.items())


def _lever_deltas(baseline, hypo, reductions: dict[str, float]) -> list[tuple[str, float]]:
    """The per-cause recovered-bottles contributions a moved slider makes
    (the lever waterfall's floating bars, node 3).

    For each cause a slider actually moved (``reductions[cause] > 0``), the Δ is
    the baseline-vs-hypo bottles-lost drop on that cause: ``base_bl[c] −
    hypo_bl[c]``. Joined-from-the-results (not re-derived as ``r·base_bl[c]``) so
    the chart never disagrees with the hypo's recomputed OEE — a fully-recovered
    cause drops out of ``hypo.bottles_lost`` and yields ``base_bl[c]``, the full
    cut. Ordered top-5 by baseline bottles (the Pareto order the sliders follow),
    only the moved causes included. Returns ``[]`` when there are no priced stops
    or nothing was moved. Pure (no UI) so the bridge sum-invariant is testable
    without the ``ui`` extra (the waterfall's verify clause, plan.md P4)."""
    if baseline is None or hypo is None:
        return []
    base_bl = {b.cause: b.bottles for b in baseline.bottles_lost}
    hypo_bl = {b.cause: b.bottles for b in hypo.bottles_lost}
    moved = [b.cause for b in baseline.bottles_lost[:_WHATIF_TOP_N]
             if reductions.get(b.cause, 0.0) > 0.0]
    deltas: list[tuple[str, float]] = []
    for cause in moved:
        d = base_bl.get(cause, 0.0) - hypo_bl.get(cause, 0.0)
        if d > 1e-9:  # a slider knob at ~0 (no real cut) draws no bar
            deltas.append((cause, d))
    return deltas


def _planned_causes(ctx) -> set[str]:
    """The stop causes marked planned in the data (Changeover, Maintenance) —
    "scheduled, not a loss" for color-by-message (ADR-0010 decision 10).
    Empty set when no planned role is mapped (every cause is then treated as
    an unplanned loss, matching compute_oee's conservative default)."""
    cause_src = ctx.mapping.source_for(CanonicalRole.STOP_CAUSE)
    planned_src = ctx.mapping.source_for(CanonicalRole.PLANNED)
    if cause_src is None or planned_src is None:
        return set()
    if cause_src not in ctx.data.columns or planned_src not in ctx.data.columns:
        return set()
    planned = ctx.data[planned_src].fillna(False).astype(bool)
    return {str(c) for c in ctx.data.loc[planned, cause_src].dropna().unique()}


def _loss_color_map(reasons, seconds, planned_causes: set[str]) -> dict[str, str]:
    """Color by message (ADR-0010 decision 10): unplanned loss causes take the
    problem-orange family, tiered by cumulative impact — the vital few
    (first 50% of the loss) in the strong shade, the middle (to 80%) in the
    base orange, the tail in the deep shade; planned causes are neutral.

    Tiers follow the Pareto split of the *unplanned* loss (planned seconds
    aren't loss and don't count toward the shares). Pure (no UI) so the
    mapping is unit-testable.
    """
    pairs = sorted(zip(reasons, seconds), key=lambda t: (-t[1], str(t[0])))
    unplanned_total = sum(s for r, s in pairs if r not in planned_causes)
    cmap: dict[str, str] = {}
    cum = 0.0
    for cause, secs in pairs:
        if cause in planned_causes:
            cmap[cause] = _INK_MUTED
            continue
        share_before = cum / unplanned_total if unplanned_total > 0 else 0.0
        tier = 0 if share_before < _LOSS_TIER_SPLITS[0] else (
            1 if share_before < _LOSS_TIER_SPLITS[1] else 2)
        cmap[cause] = _LOSS_TIERS[tier]
        cum += secs
    return cmap


def _daily_good_series(frame: pd.DataFrame):
    """The dated daily good-parts series for the forecast, or None.

    Pulled straight from ``summaries``' ``production_totals`` (scope "day",
    metric "good"), sorted by date. None when the frame has no day/good rows.
    The forecast (ADR-0006) is a function of this series only — no context.
    """
    if frame.empty or "scope" not in frame.columns:
        return None
    d = frame[(frame.scope == "day") & (frame.metric == "good")]
    if d.empty:
        return None
    d = d.sort_values("scope_value")
    return list(d["scope_value"]), list(d["value"].astype(float))


@dataclasses.dataclass(frozen=True)
class _ForecastView:
    """A technique-agnostic forecast for the future-line chart (ADR-0006/0007).

    The learned ``MLForecastResult`` (GBR median + conformal band) and the
    deterministic ``ForecastResult`` (OLS line + ±1σ band) share no base class
    and name their central series differently (``.median`` vs ``.line``). This
    view is the one place the two shapes are reconciled — a presentation concern
    of the UI layer, not a library contract, so it lives here rather than in
    ``linelens/``. Everything downstream (``_forecast_traces``, the what-if-line
    horizon slice) reads only this view, so swapping the underlying technique is
    a change to ``_resolve_forecast`` alone.
    """

    line_dates: tuple        # observed days then horizon days (one continuous axis)
    central: tuple           # central series over line_dates: .median (ML) or .line (det)
    band_dates: tuple        # last observed day then horizon days (future only)
    lower: tuple             # band lower edge, widening into the horizon
    upper: tuple             # band upper edge, widening into the horizon
    slope: float             # OLS bottles/day — the visible trend diagnostic
    r_squared: float
    technique: str           # "gradient-boosted" | "linear" — for the caption


def _to_forecast_view(fc, technique: str) -> "_ForecastView":
    """Normalize one forecast result (ML or deterministic) into a ``_ForecastView``.

    The central series is the only divergent field: read ``.median`` for the
    learned ``MLForecastResult``, ``.line`` for the deterministic ``ForecastResult``.
    The isinstance check (not ``getattr``) keeps the dispatch loud — a future
    attribute rename fails here rather than silently picking the wrong series.
    The ML type is imported lazily so this works without the ``forecast`` extra.
    """
    central = None
    try:
        from linelens.forecast_ml import MLForecastResult
        if isinstance(fc, MLForecastResult):
            central = fc.median
    except ImportError:
        pass  # sklearn absent -> the ML type is unreachable here
    if central is None:
        central = fc.line  # deterministic ForecastResult
    return _ForecastView(
        line_dates=fc.line_dates, central=tuple(central),
        band_dates=fc.band_dates, lower=fc.lower, upper=fc.upper,
        slope=fc.slope, r_squared=fc.r_squared, technique=technique,
    )


def _resolve_forecast(dates, values, horizon: int = _FORECAST_HORIZON_DAYS) -> tuple["_ForecastView | None", str]:
    """The Act-3 forecast: the learned model when there is ≥~3 months of daily
    history (ADR-0007), else the deterministic Projection (ADR-0006).

    ``horizon`` defaults to ``_FORECAST_HORIZON_DAYS`` (the Streamlit app's
    contract, unchanged); the API passes a longer display horizon.

    Returns ``(view, reason)`` where ``view`` is ``None`` exactly when no honest
    forecast can be drawn, and ``reason`` names *why* so the chart's caption can
    be specific (ADR-0002's defining edge — zero observed scatter — deserves its
    own message, not a generic "not enough"). Reasons:

    - ``"ok"`` — a forecast view was resolved (ML if ≥~3mo, else deterministic).
    - ``"too_few"`` — even the deterministic projection can't fit (``< min_days``).
    - ``"zero_scatter"`` — the deterministic fit has zero observed scatter, so its
      ±1σ band collapses onto the line and would read as a single confident
      future number (ADR-0002). Decline rather than overclaim. (Only the
      deterministic path can hit this — the ML conformal half-width is data-
      derived and never collapses on real residuals.)

    The leak guard (P2): the forecast always trains on the *full* dated series,
    never a date-scoped one. Imports ``forecast_ml`` lazily behind the
    ``forecast`` extra so ``import app`` stays light; absence of sklearn routes
    to the deterministic fallback, never a crash.
    """
    try:
        from linelens import forecast_ml
        ml = forecast_ml.forecast_ml(
            dates, values, horizon=horizon)
    except ImportError:
        ml = None  # sklearn behind the `forecast` extra — fall through
    if ml is not None:
        return _to_forecast_view(ml, technique="gradient-boosted"), "ok"
    det = forecast.forecast(
        dates, values, horizon=horizon, min_points=_FORECAST_MIN_DAYS)
    if det is None:
        return None, "too_few"
    if det.residual_std < 1e-9:
        # Zero scatter -> the statistical band collapses onto the line, which
        # would read as a single confident future number (ADR-0002). Decline.
        return None, "zero_scatter"
    return _to_forecast_view(det, technique="linear"), "ok"


def _daily_performance_series(ctx):
    """The dated daily Performance series for the degradation forecast, or None.

    Thin reshape of ``oee.performance_by_day`` (the per-day Performance ratio,
    ADR-0003) into the ``(dates, values)`` shape ``_resolve_forecast`` consumes —
    mirroring ``_daily_good_series`` so the Act-3 forecast layer is reused
    verbatim. The full (un-scoped) ctx: the forecast trains on all history
    (leakage guard, ADR-0007), never the Now-date-picker slice. None when there
    is no dated Performance series (no STATE / time basis / start timestamp /
    speeds)."""
    frame = performance_by_day(ctx)
    if frame is None or frame.empty:
        return None
    return [d.date() for d in frame["date"]], list(frame["performance"].astype(float))


def _threshold_crossing(view: "_ForecastView", threshold: float):
    """First date the forecast band's lower edge dips below ``threshold``, or
    None if it stays above across the horizon. ``band_dates[0]`` is the last
    observed day, so a crossing there means Performance is already at/below the
    concern floor today."""
    for d, lo in zip(view.band_dates, view.lower):
        if lo < threshold:
            return d
    return None


def _degradation_caption(view: "_ForecastView", crossing, horizon: int = _FORECAST_HORIZON_DAYS) -> str:
    """Technique-aware, never-confident caption for the degradation chart
    (ADR-0002/0006/0007): the band — not the line — is the forecast, plus the
    threshold-crossing read-out. No 'will be X%' phrasing. ``horizon`` is the
    display horizon the view was resolved with (7 for the Streamlit app, the
    API passes its own)."""
    if view.technique == "gradient-boosted":
        head = (f"Learned median (gradient-boosted) drawn {horizon} days "
                f"ahead inside a widening conformal band.")
    else:
        head = (f"The trend (≈ {view.slope * 100:+.2f} Performance pts/day, "
                f"r² = {view.r_squared:.2f}), drawn {horizon} days ahead "
                f"inside a widening ±1σ band.")
    floor = f"{_PERFORMANCE_CONCERN:.0%} concern floor"
    if crossing is None:
        tail = (f" The band stays above the {floor} across the "
                f"{horizon}-day horizon.")
    elif crossing == view.band_dates[0]:
        tail = f" The band is already at/below the {floor} — Performance is in the concern zone today."
    else:
        tail = (f" The band's lower edge first dips below the {floor} around "
                f"{crossing.isoformat()}.")
    return (head + " The band — not the line — is the forecast: where Performance is "
            "heading, within growing uncertainty. A projection, not a prediction of "
            "what will happen." + tail)


def _due_window_phrasing(due) -> tuple[str, str]:
    """(headline, detail) plain-words for the due window — pure, ui-free.

    The headline is always a window (two edges), never a bare date; the detail
    is the bottle countdown at the line's current pace. Three shapes: overdue
    (counter past the interval), dated (bottle edges converted at the trailing
    14-day median pace), bottles-only (a stopped line gives no honest
    bottle->date conversion — decline, don't invent; ADR-0002).
    """
    if due.remaining_late <= 0:
        return (
            "Due now",
            "The service counter has passed the learned service interval — "
            "schedule the next service.",
        )
    if due.date_early is not None and due.date_late is not None:
        if due.date_early == due.date_late:
            # The edges coincide — the single-gap case (2 service events, one
            # learned interval, no spread). A bare date would violate "always
            # a window, never a date" (ADR-0009 decision 4), so the headline
            # names the point AND the missing spread in one breath.
            head = f"{due.date_early.isoformat()} — a single point so far"
            detail = (
                f"{_fmt_num(due.remaining_early)}–{_fmt_num(due.remaining_late)} "
                "bottles to go at the line's current pace (median daily "
                "production over the last 14 days). The service rhythm is "
                "learned from a single observed interval, so the window has no "
                "spread yet — it widens as more services accumulate."
            )
        else:
            head = f"{due.date_early.isoformat()} → {due.date_late.isoformat()}"
            detail = _bottle_countdown(due)
    else:
        head = (
            f"{_fmt_num(due.remaining_early)}–{_fmt_num(due.remaining_late)} "
            "bottles from now"
        )
        detail = (
            "No production pace to convert bottles to days (the line produced "
            "nothing recently) — the window is stated in bottles only."
        )
    return head, detail


def _bottle_countdown(due) -> str:
    return (
        f"{_fmt_num(due.remaining_early)}–{_fmt_num(due.remaining_late)} "
        "bottles to go at the line's current pace (median daily production "
        "over the last 14 days). A window, not a date — the line's own "
        "service rhythm sets the width."
    )


def _date_span(ctx, start_src: str | None):
    """(lo, hi) calendar-day bounds of the data, or None when no start timestamp
    is mapped. The default/full range for the Now-charts date picker."""
    if start_src is None or start_src not in ctx.data.columns:
        return None
    days = ctx.data[start_src].dt.floor("D").dropna()
    if days.empty:
        return None
    return days.min().date(), days.max().date()


def _scoped_ctx(ctx, start_src: str | None, lo, hi):
    """ctx narrowed to events on/after lo and before hi+1day, or (ctx, False) when
    there is no window or it already spans all rows.

    The Now-charts re-aggregate from this filtered ctx (so overall == the sum of
    the visible days, and shift — which carries no date in the frames — is
    correct too). The forecast never uses it: leakage guard, ADR-0007.
    ponytail: re-runs summarize on a date-filtered ctx when narrowed — cheap
    pandas groupby on CSV-scale data, uniform across scopes. Re-aggregate
    incrementally if data grows large.
    """
    if start_src is None or lo is None or hi is None:
        return ctx, False
    ts = ctx.data[start_src]
    mask = (ts >= pd.Timestamp(lo)) & (ts < pd.Timestamp(hi) + pd.Timedelta(days=1))
    if mask.all():
        return ctx, False
    return dataclasses.replace(ctx, data=ctx.data.loc[mask]), True
