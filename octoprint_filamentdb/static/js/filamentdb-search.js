// Copyright (C) 2026 crzykidd
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// OWNS: the picker's five-tier spool search ranking (FR-2) -- the runtime
//     path a user actually drives, since the picker must search
//     client-side over the cache with no request per keystroke. This is a
//     hand-kept port of octoprint_filamentdb/search.py's identical rules;
//     that Python module carries the pytest coverage (a browser cannot run
//     a Python test) -- see its docstring and docs/decisions.md for why the
//     two are separate files kept in sync by hand rather than one shared
//     source. Any change to the tier order or matching rule must be made
//     in both.
// DOES NOT OWN: fetching or caching the spool list (the FilamentDBViewModel
//     in filamentdb.js), or rendering results (the picker modal template).
//
// Exposes a single global, `FilamentDBSearch`, with one function:
// `FilamentDBSearch.rank(rows, query)` -> ranked array of
// `{ row, tier }`, most relevant first. `rows` items need only the fields
// referenced below (label, instanceId, id, vendor, name, type, colorName,
// locationName) -- extra fields are ignored.

(function (global) {
    "use strict";

    var TIER_EXACT_LABEL = "exact_label";
    var TIER_EXACT_INSTANCE_ID = "exact_instance_id";
    var TIER_EXACT_ID = "exact_id";
    var TIER_LABEL_PREFIX = "label_prefix";
    var TIER_FUZZY = "fuzzy";

    var TIER_ORDER = [
        TIER_EXACT_LABEL,
        TIER_EXACT_INSTANCE_ID,
        TIER_EXACT_ID,
        TIER_LABEL_PREFIX,
        TIER_FUZZY,
    ];

    function lower(value) {
        return (value || "").toString().toLowerCase();
    }

    function fuzzyHit(query, row) {
        var haystacks = [row.vendor, row.name, row.type, row.colorName, row.locationName];
        for (var i = 0; i < haystacks.length; i++) {
            var h = lower(haystacks[i]);
            if (h && h.indexOf(query) !== -1) {
                return true;
            }
        }
        return false;
    }

    function rank(rows, query) {
        query = lower(query).trim();
        if (!query) {
            return [];
        }

        var tiers = {};
        TIER_ORDER.forEach(function (tier) {
            tiers[tier] = [];
        });

        (rows || []).forEach(function (row) {
            var label = lower(row.label);
            var instanceId = lower(row.instanceId);
            var id = lower(row.id);

            if (label === query) {
                tiers[TIER_EXACT_LABEL].push(row);
            } else if (instanceId && instanceId === query) {
                tiers[TIER_EXACT_INSTANCE_ID].push(row);
            } else if (id && id === query) {
                tiers[TIER_EXACT_ID].push(row);
            } else if (label && label.indexOf(query) === 0) {
                tiers[TIER_LABEL_PREFIX].push(row);
            } else if (fuzzyHit(query, row)) {
                tiers[TIER_FUZZY].push(row);
            }
        });

        var results = [];
        TIER_ORDER.forEach(function (tier) {
            tiers[tier].forEach(function (row) {
                results.push({ row: row, tier: tier });
            });
        });
        return results;
    }

    global.FilamentDBSearch = {
        TIER_EXACT_LABEL: TIER_EXACT_LABEL,
        TIER_EXACT_INSTANCE_ID: TIER_EXACT_INSTANCE_ID,
        TIER_EXACT_ID: TIER_EXACT_ID,
        TIER_LABEL_PREFIX: TIER_LABEL_PREFIX,
        TIER_FUZZY: TIER_FUZZY,
        rank: rank,
    };
})(window);
