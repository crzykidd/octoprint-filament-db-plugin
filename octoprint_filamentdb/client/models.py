# Copyright (C) 2026 crzykidd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Dataclasses for the Filament DB response shapes this plugin reads.

OWNS: ``SpoolSummary``/``FilamentSummary`` (the ``GET /api/filaments`` list
    projection -- ``diameter`` absent, C-4), ``FilamentDetail``/``SpoolDetail``
    (the ``GET /api/spools/{spoolId}`` detail projection -- variant
    inheritance already resolved server-side, ``diameter`` present),
    ``Location`` (the ``GET /api/locations`` projection -- ``_id``/``name``
    only, added 2026-08-02 to resolve a spool's ``locationId`` to a display
    name; see C-3b), and the ``parse_*`` functions that turn raw JSON dicts
    into them. Fields are exactly PRD C-3b's seven plus the two weight
    fields C-2's net computation needs (``spoolWeight``,
    ``netFilamentWeight`` -- see docs/decisions.md: C-3b's field count
    predates the Weight display section and is a floor, not a ceiling).
    Nothing else on any of these documents is read.
DOES NOT OWN: the HTTP calls themselves (``client/filamentdb.py``), TTL
    caching (``client/cache.py``), or any weight arithmetic (``weights.py``
    -- these are plain data carriers only).

PRD rule N-3: this package imports nothing internal. Enforced by
tests/test_import_directions.py.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class SpoolSummary:
    """A spool subdocument -- identical shape whether it arrives embedded
    in the list projection or as the ``spool`` half of
    ``GET /api/spools/{id}``."""

    id: str
    instance_id: Optional[str]
    label: str
    total_weight: Optional[float]  # gross grams; None = never weighed
    retired: bool
    location_id: Optional[str]


@dataclass(frozen=True)
class FilamentSummary:
    """A filament as returned in the ``GET /api/filaments`` list
    projection. ``diameter`` is deliberately absent -- it is not part of
    this projection (C-4); use ``FilamentDetail`` for an assigned spool."""

    id: str
    name: str
    vendor: str
    type: str
    color: Optional[str]
    density: Optional[float]  # already own??parent resolved server-side (C-4)
    spool_weight: Optional[float]  # tare, filament-level, inherited
    net_filament_weight: Optional[float]  # nominal, filament-level, inherited
    parent_id: Optional[str]
    spools: List[SpoolSummary] = field(default_factory=list)


@dataclass(frozen=True)
class FilamentDetail:
    """A filament as returned by ``GET /api/spools/{spoolId}`` (equally
    ``GET /api/filaments/{id}``) -- variant inheritance already resolved
    server-side (C-4), and ``diameter`` is present here (absent from the
    list projection)."""

    id: str
    name: str
    vendor: str
    type: str
    color: Optional[str]
    density: Optional[float]
    diameter: float
    spool_weight: Optional[float]
    net_filament_weight: Optional[float]
    parent_id: Optional[str]


@dataclass(frozen=True)
class Location:
    """A location document from ``GET /api/locations`` -- used only to
    resolve a spool's ``locationId`` to a display name (picker filter
    dropdown and search, C-3b). Nothing else on the document (address,
    notes, ...) is read; this plugin does no location management."""

    id: str
    name: str


@dataclass(frozen=True)
class SpoolDetail:
    """``GET /api/spools/{spoolId}``'s ``{filament, spool}`` shape -- the
    read for an assigned spool (C-3): one request returns everything the
    conversion and display layers need, inheritance already resolved."""

    filament: FilamentDetail
    spool: SpoolSummary


def parse_spool_summary(raw):
    return SpoolSummary(
        id=raw["_id"],
        instance_id=raw.get("instanceId"),
        label=raw.get("label") or "",
        total_weight=raw.get("totalWeight"),
        retired=bool(raw.get("retired", False)),
        location_id=raw.get("locationId"),
    )


def parse_filament_summary(raw):
    return FilamentSummary(
        id=raw["_id"],
        name=raw.get("name") or "",
        vendor=raw.get("vendor") or "",
        type=raw.get("type") or "",
        color=raw.get("color"),
        density=raw.get("density"),
        spool_weight=raw.get("spoolWeight"),
        net_filament_weight=raw.get("netFilamentWeight"),
        parent_id=raw.get("parentId"),
        spools=[parse_spool_summary(s) for s in raw.get("spools") or []],
    )


def parse_filament_detail(raw):
    return FilamentDetail(
        id=raw["_id"],
        name=raw.get("name") or "",
        vendor=raw.get("vendor") or "",
        type=raw.get("type") or "",
        color=raw.get("color"),
        density=raw.get("density"),
        # Schema default (C-4) -- always present in practice, but guard
        # against a malformed/legacy record rather than raise KeyError.
        diameter=raw.get("diameter", 1.75),
        spool_weight=raw.get("spoolWeight"),
        net_filament_weight=raw.get("netFilamentWeight"),
        parent_id=raw.get("parentId"),
    )


def parse_spool_detail(raw):
    return SpoolDetail(
        filament=parse_filament_detail(raw["filament"]),
        spool=parse_spool_summary(raw["spool"]),
    )


def parse_location(raw):
    return Location(id=raw["_id"], name=raw.get("name") or "")
