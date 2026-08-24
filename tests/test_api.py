"""End-to-end API tests (server.app via FastAPI's TestClient).

Drives the real upload -> analyze -> scope/whatif/export flow against the
sample CSVs, mirroring how the React frontend will call the API. Runs in the
default ``uv run pytest`` env (fastapi/httpx are in the dev group).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.app import create_app

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MONTH = _REPO_ROOT / "sample_data" / "fictional_month.csv"
_SIX_MONTH = _REPO_ROOT / "sample_data" / "fictional_6month.csv"
_EMPTY = _REPO_ROOT / "sample_data" / "empty.csv"
_HEADER_ONLY = _REPO_ROOT / "sample_data" / "header_only.csv"
_TWO_DAY = _REPO_ROOT / "sample_data" / "golden" / "two_day.csv"

_SEV_RANK = {"error": 0, "warning": 1, "info": 2}


@pytest.fixture()
def client():
    # one app (one store) per test: dataset ids never leak across tests
    return TestClient(create_app())


def _upload(client: TestClient, path: Path) -> dict:
    with open(path, "rb") as f:
        r = client.post("/api/upload", files={"file": (path.name, f, "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()


def _auto_mapping(upload: dict) -> dict:
    """The mapping body the frontend would send from the upload suggestions."""
    return {"roles": dict(upload["auto_roles"]), "counters": list(upload["auto_counters"])}


def _analyze(client: TestClient, dataset_id: str, mapping: dict) -> dict:
    r = client.post(f"/api/datasets/{dataset_id}/analyze", json={"mapping": mapping})
    assert r.status_code == 200, r.text
    return r.json()


# --- happy path: upload -> analyze -> full deck --------------------------------


def test_upload_returns_suggestions_and_preview(client):
    up = _upload(client, _MONTH)
    assert up["dataset_id"]
    assert up["profile"]["row_count"] > 0
    assert up["preview"] and len(up["preview"]) == 10
    # the auto-map found the canonical roles; counters are suggested too
    roles = up["auto_roles"]
    for role in ("timestamp_start", "state", "good_count", "reject_count"):
        assert role in roles
    assert "suggested_roles" in up and "confidence" in next(iter(up["suggested_roles"].values()))
    assert isinstance(up["auto_counters"], list)
    assert isinstance(up["numeric_counter_options"], list)
    assert up["capabilities"]["Production totals"] is True
    # every preview value is JSON-safe (no NaN/Timestamp leakage)
    json.dumps(up)


def test_analyze_returns_the_full_deck(client):
    up = _upload(client, _MONTH)
    deck = _analyze(client, up["dataset_id"], _auto_mapping(up))

    for key in (
        "fingerprint", "findings", "severity_counts", "report", "oee",
        "maintenance", "contrast_rows", "planned_causes", "pareto",
        "daily_good", "forecast", "daily_performance", "performance_forecast",
        "performance_concern", "performance_crossing", "mtbf", "date_span",
        "state_timeline", "capabilities",
    ):
        assert key in deck, key

    # findings sorted as app.py renders: error < warning < info, stable
    ranks = [_SEV_RANK[f["severity"]] for f in deck["findings"]]
    assert ranks == sorted(ranks)

    # scope_value is always null (overall) or a string (ISO day / shift label)
    for frame_key in ("state_totals", "production_totals", "downtime_by_reason"):
        for row in deck["report"][frame_key]:
            sv = row["scope_value"]
            assert sv is None or isinstance(sv, str), (frame_key, sv)

    # forecast view carries an explicit reason; the month resolves deterministically
    assert deck["forecast"]["reason"] in {"ok", "too_few", "zero_scatter", "no_series"}
    assert deck["forecast"]["reason"] == "ok"
    view = deck["forecast"]["view"]
    assert view["technique"] in {"linear", "gradient-boosted"}
    # the API resolves a 14-day display horizon (the Streamlit app keeps 7)
    assert len(view["line_dates"]) == len(deck["daily_good"]["dates"]) + 14
    assert len(view["band_dates"]) == 15  # last observed day + 14 horizon days

    # bottles_lost sorted descending by bottles (M4 contract, preserved)
    bottles = [b["bottles"] for b in deck["oee"]["bottles_lost"]]
    assert bottles == sorted(bottles, reverse=True)
    assert deck["pareto"]["causes"] == [b["cause"] for b in deck["oee"]["bottles_lost"]]

    # planned causes (the month fixture's only planned cause is Changeover;
    # the 6-month file also carries planned Maintenance)
    assert deck["planned_causes"] == ["Changeover"]
    # the month spans more than TIMELINE_MAX_GANTT_DAYS, so the server sends
    # the composition the chart actually draws, not every interval
    tl = deck["state_timeline"]
    assert tl["mode"] == "composition"
    # a month is past the gantt threshold but still readable one bar per day
    assert tl["grain"] == "day"
    assert len(tl["days"]) > 14
    assert tl["states"]
    assert len(tl["grid"]) == len(tl["states"])
    assert all(len(row) == len(tl["days"]) for row in tl["grid"])
    assert deck["date_span"] and all(isinstance(d, str) for d in deck["date_span"])
    # the whole deck is JSON-safe
    json.dumps(deck)


def test_short_window_still_gets_the_per_interval_gantt(client):
    """A window inside TIMELINE_MAX_GANTT_DAYS keeps every interval.

    Bucketing wide windows must not cost short files the detailed view, which
    is the whole point of the gantt: each stop individually visible.
    """
    up = _upload(client, _TWO_DAY)
    deck = _analyze(client, up["dataset_id"], _auto_mapping(up))

    tl = deck["state_timeline"]
    assert tl["mode"] == "gantt"
    assert tl["intervals"]
    first = tl["intervals"][0]
    assert "T" in first["start"] and "T" in first["end"]


def test_wide_window_does_not_ship_per_interval_records(client):
    """Regression guard: the six-month deck must stay small.

    The six-month file holds about 9,300 intervals. Serializing them all cost
    924 KB, roughly 87% of the payload, which the browser spent about 35
    seconds parsing before collapsing them into 180 daily bars and discarding
    the rest. The server buckets instead, so the payload must stay far below
    the row count it was built from.
    """
    up = _upload(client, _SIX_MONTH)
    deck = _analyze(client, up["dataset_id"], _auto_mapping(up))

    tl = deck["state_timeline"]
    assert tl["mode"] == "composition"
    assert "intervals" not in tl

    # six months buckets to weeks, so the axis stays readable: ~26 bars, not
    # 180 and certainly not one per row
    assert tl["grain"] == "week"
    assert 20 < len(tl["days"]) < 40
    assert len(tl["grid"]) == len(tl["states"])
    assert all(len(row) == len(tl["days"]) for row in tl["grid"])

    # the timeline is now a small fraction of the deck rather than most of it
    timeline_bytes = len(json.dumps(tl))
    deck_bytes = len(json.dumps(deck))
    assert timeline_bytes < deck_bytes * 0.25, (
        f"timeline is {timeline_bytes / deck_bytes:.0%} of the payload"
    )

    # the totals survive the bucketing: every state keeps non-negative seconds
    assert all(v >= 0 for row in tl["grid"] for v in row)
    assert sum(sum(row) for row in tl["grid"]) > 0


def test_analyze_six_month_resolves_ml_or_linear(client):
    up = _upload(client, _SIX_MONTH)
    deck = _analyze(client, up["dataset_id"], _auto_mapping(up))
    assert deck["forecast"]["reason"] == "ok"
    assert deck["forecast"]["view"]["technique"] in {"linear", "gradient-boosted"}
    assert deck["maintenance"] is not None
    assert deck["maintenance"]["n_service_events"] >= 2
    due = deck["maintenance"]["due"]
    assert due is not None
    assert due["date_early"] is None or isinstance(due["date_early"], str)


# --- error paths -----------------------------------------------------------------


def test_upload_garbage_csv_is_422_with_scrubbed_message(client):
    with open(_EMPTY, "rb") as f:
        r = client.post("/api/upload", files={"file": (_EMPTY.name, f, "text/csv")})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, str) and detail
    # the temp-file shim name must never leak into the message
    assert "tmp" not in detail.lower()
    assert ".csv" not in detail


def test_analyze_missing_required_role_is_422_with_problems(client):
    up = _upload(client, _MONTH)
    r = client.post(
        f"/api/datasets/{up['dataset_id']}/analyze",
        json={"mapping": {"roles": {"state": "state"}, "counters": []}},
    )
    assert r.status_code == 422
    problems = r.json()["detail"]["problems"]
    assert any("timestamp_start" in p for p in problems)


def test_analyze_unknown_role_name_is_422(client):
    up = _upload(client, _MONTH)
    r = client.post(
        f"/api/datasets/{up['dataset_id']}/analyze",
        json={"mapping": {"roles": {"not_a_role": "state"}, "counters": []}},
    )
    assert r.status_code == 422


def test_unknown_dataset_is_404(client):
    for method, url in (
        ("post", "/api/datasets/nope/analyze"),
        ("post", "/api/datasets/nope/scope"),
        ("post", "/api/datasets/nope/whatif"),
    ):
        body = {"mapping": {"roles": {}, "counters": []}}
        if url.endswith("whatif"):
            body["reductions"] = {}
        r = getattr(client, method)(url, json=body)
        assert r.status_code == 404, url
    r = client.get("/api/datasets/nope/export/cleaned.csv", params={"fingerprint": "x"})
    assert r.status_code == 404


def test_whatif_uncomputable_oee_is_422(client):
    # header_only.csv: timestamp_start + state but no end/duration -> no time
    # basis -> oee_from_context is None -> an honest 422, never a bare 0%.
    up = _upload(client, _HEADER_ONLY)
    mapping = {
        "roles": {
            "machine_id": "machine_id",
            "timestamp_start": "timestamp_start",
            "state": "state",
        },
        "counters": [],
    }
    r = client.post(
        f"/api/datasets/{up['dataset_id']}/whatif",
        json={"mapping": mapping, "reductions": {}},
    )
    assert r.status_code == 422


# --- whatif invariants -------------------------------------------------------------


def test_whatif_empty_reductions_reproduces_baseline(client):
    up = _upload(client, _MONTH)
    mapping = _auto_mapping(up)
    deck = _analyze(client, up["dataset_id"], mapping)
    r = client.post(
        f"/api/datasets/{up['dataset_id']}/whatif",
        json={"mapping": mapping, "reductions": {}},
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["hypo"]["oee"] == deck["oee"]["oee"]
    assert payload["recovered"] == 0.0
    assert payload["lever_deltas"] == []


def test_whatif_full_cut_recovers_that_causes_bottles(client):
    up = _upload(client, _MONTH)
    mapping = _auto_mapping(up)
    deck = _analyze(client, up["dataset_id"], mapping)
    top = deck["oee"]["bottles_lost"][0]
    r = client.post(
        f"/api/datasets/{up['dataset_id']}/whatif",
        json={"mapping": mapping, "reductions": {top["cause"]: 1.0}},
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["lever_deltas"] == [{"cause": top["cause"], "bottles": pytest.approx(top["bottles"])}]
    assert payload["recovered"] == pytest.approx(top["bottles"])
    assert payload["hypo"]["oee"] > payload["baseline"]["oee"]


def test_whatif_lifts_the_forecast_horizon(client):
    """The what-if path: the production forecast's horizon, lifted by the
    recovered bottles via whatif.spread_recovered — it must sum to the
    baseline horizon plus exactly the recovered bottles."""
    up = _upload(client, _MONTH)
    mapping = _auto_mapping(up)
    deck = _analyze(client, up["dataset_id"], mapping)
    top = deck["oee"]["bottles_lost"][0]
    r = client.post(
        f"/api/datasets/{up['dataset_id']}/whatif",
        json={"mapping": mapping, "reductions": {top["cause"]: 1.0}},
    )
    assert r.status_code == 200, r.text
    lift = r.json()["forecast_lift"]
    assert lift is not None
    assert len(lift["dates"]) == len(lift["values"]) == 15  # anchor + 14 horizon days
    base_central = deck["forecast"]["view"]["central"]
    gained = sum(lift["values"][1:]) - sum(base_central[-14:])
    assert gained == pytest.approx(r.json()["recovered"], abs=1e-6)
    # ...and every lifted day sits at/above the baseline path
    assert all(v >= b - 1e-9 for v, b in zip(lift["values"][1:], base_central[-14:]))


def test_whatif_no_lift_without_moved_lever(client):
    up = _upload(client, _MONTH)
    mapping = _auto_mapping(up)
    _analyze(client, up["dataset_id"], mapping)
    r = client.post(
        f"/api/datasets/{up['dataset_id']}/whatif",
        json={"mapping": mapping, "reductions": {}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["forecast_lift"] is None


def test_whatif_reduction_out_of_range_is_422(client):
    up = _upload(client, _MONTH)
    r = client.post(
        f"/api/datasets/{up['dataset_id']}/whatif",
        json={"mapping": _auto_mapping(up), "reductions": {"Starvation": 50}},
    )
    assert r.status_code == 422


# --- scope -------------------------------------------------------------------------


def _day_rows(report: dict) -> list:
    return [r for r in report["production_totals"] if r["scope"] == "day"]


def test_scope_narrower_range_returns_fewer_day_rows(client):
    up = _upload(client, _MONTH)
    mapping = _auto_mapping(up)
    deck = _analyze(client, up["dataset_id"], mapping)
    full_days = _day_rows(deck["report"])
    assert len(full_days) >= 7

    span = deck["date_span"]
    r = client.post(
        f"/api/datasets/{up['dataset_id']}/scope",
        json={"mapping": mapping, "start": span[0], "end": span[0]},
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["narrowed"] is True
    scoped_days = _day_rows(payload["report"])
    assert 0 < len(scoped_days) < len(full_days)
    # the scoped timeline comes along, in the mode the scoped window earns
    assert payload["state_timeline"]["mode"] in {"gantt", "composition", "empty"}
    # leakage guard: the scope response never carries a forecast
    assert "forecast" not in payload


def test_scope_full_range_is_not_narrowed(client):
    up = _upload(client, _MONTH)
    mapping = _auto_mapping(up)
    deck = _analyze(client, up["dataset_id"], mapping)
    span = deck["date_span"]
    r = client.post(
        f"/api/datasets/{up['dataset_id']}/scope",
        json={"mapping": mapping, "start": span[0], "end": span[1]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["narrowed"] is False


# --- exports ------------------------------------------------------------------------


def test_export_endpoints_after_analyze(client):
    up = _upload(client, _MONTH)
    deck = _analyze(client, up["dataset_id"], _auto_mapping(up))
    fp = deck["fingerprint"]
    base = f"/api/datasets/{up['dataset_id']}/export"

    r = client.get(f"{base}/cleaned.csv", params={"fingerprint": fp})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "linelens_cleaned.csv" in r.headers["content-disposition"]
    assert "timestamp_start" in r.text.splitlines()[0]

    r = client.get(f"{base}/findings.json", params={"fingerprint": fp})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert "linelens_findings.json" in r.headers["content-disposition"]
    blob = r.json()
    assert blob["schema_version"] == "1.0"
    assert isinstance(blob["findings"], list)

    r = client.get(f"{base}/findings.csv", params={"fingerprint": fp})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "linelens_findings.csv" in r.headers["content-disposition"]
    assert r.text.splitlines()[0].startswith("rule_id")


def test_export_unknown_fingerprint_is_409(client):
    up = _upload(client, _MONTH)
    r = client.get(
        f"/api/datasets/{up['dataset_id']}/export/cleaned.csv",
        params={"fingerprint": "never-analyzed"},
    )
    assert r.status_code == 409


# --- the claims the README and the landing page make ---------------------------


def test_documented_test_count_matches_reality():
    """The README and the landing page both print a test count.

    A number in a README is a claim, and this project exists to catch claims
    that stopped matching the data. Two tests were added to this file once,
    and three documents kept saying 117. This fails the moment that drifts
    again, which is cheaper than a reader counting for themselves.
    """
    import re
    import subprocess

    root = Path(__file__).resolve().parents[1]
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=root, capture_output=True, text=True,
    ).stdout
    collected = int(re.search(r"(\d+) tests? collected", out).group(1))

    # Every place a document prints the count. The landing page states it
    # twice, in the hero note and in the stat row, so both are listed.
    claims = [
        ("README.md", r"\*\*(\d+) tests pass"),
        ("CONTRIBUTING.md", r"# (\d+) tests, all must pass"),
        ("landing/index.html", r'<span class="n">(\d+)</span><span class="k">Tests, all passing'),
        ("landing/index.html", r"MIT licensed, (\d+) tests"),
    ]
    for name, pattern in claims:
        text = (root / name).read_text(encoding="utf-8")
        found = re.search(pattern, text)
        assert found, f"{name} no longer states a test count matching {pattern!r}"
        assert int(found.group(1)) == collected, (
            f"{name} claims {found.group(1)} tests, but {collected} are collected"
        )


def test_missing_frontend_build_explains_itself(tmp_path, monkeypatch):
    """With no web/dist, / must say how to build it, not return a bare 404.

    The launcher opens a browser the moment the server binds. Before this, a
    first-time user with no frontend build saw {"detail":"Not Found"} as raw
    JSON and had nothing to act on, even though one npm command fixes it.
    """
    import importlib

    import api as api_module

    monkeypatch.setattr(api_module, "_DIST", tmp_path / "does-not-exist")
    app = api_module.build_app()

    with TestClient(app) as c:
        r = c.get("/")

    assert r.status_code == 503, "a missing UI is unavailable, not absent"
    body = r.text
    assert "npm --prefix web ci" in body
    assert "npm --prefix web run build" in body
    assert "text/html" in r.headers["content-type"]

    importlib.reload(api_module)
