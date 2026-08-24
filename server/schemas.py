"""Pydantic request/response schemas for the LineLens API (server.app).

Requests only — responses are plain dicts built by ``server.serialize`` (the
payloads mirror dataclasses the frontend reads field-by-field; locking them
into response models adds no validation value for a local single-user app).
"""
from __future__ import annotations

import datetime

from pydantic import BaseModel, Field


class MappingIn(BaseModel):
    """A column mapping as the frontend sends it.

    ``roles`` maps canonical role *names* (``CanonicalRole.value`` strings such
    as ``"timestamp_start"``) to source column names; ``counters`` lists the
    source columns to analyze as counters. Mirrors how app.py's Analyze button
    assembles ``schema.build_mapping(roles, counters=counters)``.
    """

    roles: dict[str, str] = Field(default_factory=dict)
    counters: list[str] = Field(default_factory=list)


class AnalyzeRequest(BaseModel):
    mapping: MappingIn


class ScopeRequest(BaseModel):
    """Now-charts date scoping. Either bound optional: a missing bound falls
    back to the dataset's own date-span edge (the picker's default window)."""

    mapping: MappingIn
    start: datetime.date | None = None
    end: datetime.date | None = None


class WhatIfRequest(BaseModel):
    """What-if re-pricing. ``reductions`` maps a stop cause to the fraction of
    its unplanned downtime to cut, in [0, 1] — the same scale app.py's sliders
    produce (0–100% ÷ 100) and ``whatif.whatif_from_context`` consumes."""

    mapping: MappingIn
    reductions: dict[str, float] = Field(default_factory=dict)
