# Copyright (C) 2026 crzykidd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reference implementation of the picker's five-tier spool search ranking
(FR-2).

OWNS: the ranking algorithm's rules, as a plain-data spec, so it can carry
    automated pytest coverage. **This is a reference implementation, not
    the runtime path** -- FR-2 requires the picker's search to run
    client-side over the cache with no request per keystroke, so the
    actual search a user drives lives in
    ``static/js/filamentdb-search.js``, a deliberate JS port of the exact
    same five tiers kept in sync by hand (see docs/decisions.md for why:
    Python can exercise the algorithm offline the way the "offline-diff
    method" lesson recommends, but a browser cannot run a Python test, and
    adding a JS runtime to the test toolchain was judged out of scope for
    this step). Any change to the tier order or matching rule must be made
    in both files.
DOES NOT OWN: fetching or caching the spool list (``client/``), or
    rendering results (the JS file above).

Ranking, in order (first match wins -- a spool is placed in the highest
tier it qualifies for, never duplicated across tiers):

1. exact ``label``
2. exact ``instanceId``
3. exact ``_id``
4. ``label`` prefix
5. fuzzy over vendor / name / type / colour name / location name
"""

from dataclasses import dataclass
from typing import List, Optional

EXACT_LABEL = "exact_label"
EXACT_INSTANCE_ID = "exact_instance_id"
EXACT_ID = "exact_id"
LABEL_PREFIX = "label_prefix"
FUZZY = "fuzzy"

# Tier order -- lower index sorts first. A row's tier is entirely
# determined by the first rule (in this order) it satisfies.
_TIER_ORDER = (EXACT_LABEL, EXACT_INSTANCE_ID, EXACT_ID, LABEL_PREFIX, FUZZY)


@dataclass(frozen=True)
class SearchRow:
    """The minimal shape the ranking needs from a picker row -- a
    subset of the flattened filament+spool fields the frontend builds
    from the cached list (client/models.FilamentSummary + SpoolSummary)."""

    spool_id: str
    label: str
    instance_id: Optional[str]
    id: str  # the spool's Mongo _id
    vendor: str
    name: str
    type: str
    color_name: Optional[str] = None
    location_name: Optional[str] = None


@dataclass(frozen=True)
class SearchResult:
    row: SearchRow
    tier: str  # one of the module-level constants above


def _fuzzy_hit(query, row):
    haystacks = (row.vendor, row.name, row.type, row.color_name, row.location_name)
    return any(h and query in h.lower() for h in haystacks)


def rank(rows: List[SearchRow], query: str) -> List[SearchResult]:
    """Rank ``rows`` against ``query``. Returns only matching rows, most
    relevant first; ties within a tier keep the input order (callers sort
    the unfiltered list by label ascending first -- see job.py's
    TODO(FR-9b) sort site -- so a stable rank here preserves that)."""
    query = (query or "").strip().lower()
    if not query:
        return []

    tiers = {tier: [] for tier in _TIER_ORDER}
    for row in rows:
        label = (row.label or "").lower()
        instance_id = (row.instance_id or "").lower()
        row_id = (row.id or "").lower()

        if label == query:
            tiers[EXACT_LABEL].append(row)
        elif instance_id and instance_id == query:
            tiers[EXACT_INSTANCE_ID].append(row)
        elif row_id and row_id == query:
            tiers[EXACT_ID].append(row)
        elif label and label.startswith(query):
            tiers[LABEL_PREFIX].append(row)
        elif _fuzzy_hit(query, row):
            tiers[FUZZY].append(row)

    results = []
    for tier in _TIER_ORDER:
        results.extend(SearchResult(row=row, tier=tier) for row in tiers[tier])
    return results
