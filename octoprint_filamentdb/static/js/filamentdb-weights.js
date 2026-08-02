// Copyright (C) 2026 crzykidd
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// OWNS: a JS port of octoprint_filamentdb/weights.py's compute_weight() --
//     the sidebar/picker's net-weight computation and its three degraded
//     paths (C-2, PRD §Weight display). Must run client-side (the sidebar
//     renders from the cached assignment record, no round trip per row),
//     while the Python original carries the pytest coverage
//     (tests/test_weights.py) since a browser cannot run it -- same
//     reasoning as filamentdb-search.js's relationship to search.py; see
//     that file and docs/decisions.md. Any change to the rounding or
//     degraded-path rules must be made in both files.
// DOES NOT OWN: fetching or caching spool data, or rendering (filamentdb.js,
//     filamentdb-picker.js).
//
// Exposes `FilamentDBWeights.compute(gross, tare, nominal)` ->
// `{ netGrams, percent, text }`, mirroring weights.WeightDisplay's three
// fields the UI actually needs (the others -- *_missing flags -- are not
// needed client-side since `text` already encodes them).

(function (global) {
    "use strict";

    function normalizeZero(value) {
        return value === 0 ? 0 : value;
    }

    function fixed1(value) {
        // Always exactly one decimal place -- the net figure is the
        // headline number (see weights.py's _fixed1 for why: it matches
        // the live #177 acceptance target, 169.37 -> "169.4 g").
        return normalizeZero(Math.round(value * 10) / 10).toFixed(1);
    }

    function trim(value) {
        // Whole numbers render without a decimal ("1000"); anything else
        // gets one decimal place ("1234.5"). Used for nominal/gross-only
        // figures (see weights.py's _trim).
        var rounded = normalizeZero(Math.round(value * 10) / 10);
        return rounded === Math.trunc(rounded)
            ? String(Math.trunc(rounded))
            : rounded.toFixed(1);
    }

    function compute(gross, tare, nominal) {
        if (gross === null || gross === undefined) {
            return { netGrams: null, percent: null, text: "not weighed" };
        }

        if (tare === null || tare === undefined) {
            // Never show gross as if it were net -- it overstates
            // remaining filament by the weight of the reel.
            return {
                netGrams: null,
                percent: null,
                text: trim(gross) + " g gross · tare not set",
            };
        }

        var net = gross - tare;

        if (nominal === null || nominal === undefined || nominal <= 0) {
            return { netGrams: net, percent: null, text: fixed1(net) + " g" };
        }

        // Net may legitimately exceed nominal on an overfilled reel;
        // clamp the bar, never the figure.
        var percent = Math.max(0, Math.min(100, (net / nominal) * 100));
        return {
            netGrams: net,
            percent: percent,
            text: fixed1(net) + " g / " + trim(nominal) + " g",
        };
    }

    global.FilamentDBWeights = {
        compute: compute,
        trim: trim,
    };
})(window);
