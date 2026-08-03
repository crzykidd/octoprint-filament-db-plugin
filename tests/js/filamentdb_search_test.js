// Copyright (C) 2026 crzykidd
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Node-run coverage for static/js/filamentdb-search.js -- the picker's
// actual runtime search ranking (FR-2). Ported case-for-case from the
// deleted tests/test_search_ranking.py, which tested a Python shadow
// module (octoprint_filamentdb/search.py) that nothing called at runtime
// -- see docs/decisions.md for why that module was removed. This is now
// the only coverage for the ranking algorithm, and it exercises the code
// a keystroke in the picker actually runs.
//
// Not a general test framework -- just enough of one to run under Node 12
// (Debian bullseye's `apt` package, added to Dockerfile.dev for this) with
// no npm dependencies, no network access, and no package.json. Invoked by
// tests/test_search_ranking_js.py via `node`, so `pytest` remains the one
// command that runs the whole suite.

"use strict";

var assert = require("assert");
var path = require("path");

// filamentdb-search.js is a browser IIFE that hangs its export off a
// `window` global -- Node has no such global by default, so provide one
// before loading it (see that file's own `(function (global) {...})(window)`
// wrapper).
global.window = global;
require(
    path.join(__dirname, "..", "..", "octoprint_filamentdb", "static", "js", "filamentdb-search.js")
);

var rank = FilamentDBSearch.rank;
var EXACT_LABEL = FilamentDBSearch.TIER_EXACT_LABEL;
var EXACT_INSTANCE_ID = FilamentDBSearch.TIER_EXACT_INSTANCE_ID;
var EXACT_ID = FilamentDBSearch.TIER_EXACT_ID;
var LABEL_PREFIX = FilamentDBSearch.TIER_LABEL_PREFIX;
var FUZZY = FilamentDBSearch.TIER_FUZZY;

// Same fixture as the deleted Python test, translated to the JS row shape
// (camelCase field names -- label/instanceId/id/vendor/name/type/
// colorName/locationName, see filamentdb-search.js's docstring).
var ROWS = [
    {
        spoolId: "s177",
        label: "177",
        instanceId: "970fdbcd56",
        id: "6a6eca1aa3360ac295bfb007",
        vendor: "Amolen",
        name: "Amolen PLA Matte Dual Color Green Purple",
        type: "PLA",
        colorName: null,
        locationName: "Shelf A",
    },
    {
        spoolId: "s170",
        label: "170",
        instanceId: "aaaa000001",
        id: "aaaaaaaaaaaaaaaaaaaaaaaa",
        vendor: "Prusament",
        name: "PLA Galaxy Black",
        type: "PLA",
        colorName: "Black",
        locationName: "Shelf B",
    },
    {
        spoolId: "s175",
        label: "175",
        instanceId: "bbbb000002",
        id: "bbbbbbbbbbbbbbbbbbbbbbbb",
        vendor: "Amolen",
        name: "Amolen PLA Silk Pumpkin Orange",
        type: "PLA",
        colorName: "Orange",
        locationName: "Shelf A",
    },
    {
        spoolId: "sfuzzy",
        label: "9",
        instanceId: "cccc000003",
        id: "cccccccccccccccccccccccc",
        vendor: "Polymaker",
        name: "PolyTerra Matte",
        type: "PETG",
        colorName: null,
        locationName: "Drybox",
    },
];

var tests = [];
function test(name, fn) {
    tests.push({ name: name, fn: fn });
}

test("exact label ranks first and is labelled exact", function () {
    var results = rank(ROWS, "177");
    assert.strictEqual(results[0].row.spoolId, "s177");
    assert.strictEqual(results[0].tier, EXACT_LABEL);
});

test("exact label beats a fuzzy hit on a different row", function () {
    // "9" is spool sfuzzy's exact label -- assert the tier assignment
    // itself, not just ordering.
    var results = rank(ROWS, "9");
    assert.strictEqual(results.length, 1);
    assert.strictEqual(results[0].tier, EXACT_LABEL);
});

test("exact instance id ranks before prefix and fuzzy", function () {
    var results = rank(ROWS, "aaaa000001");
    assert.strictEqual(results[0].row.spoolId, "s170");
    assert.strictEqual(results[0].tier, EXACT_INSTANCE_ID);
});

test("exact mongo id pasted from a url", function () {
    var results = rank(ROWS, "bbbbbbbbbbbbbbbbbbbbbbbb");
    assert.strictEqual(results[0].row.spoolId, "s175");
    assert.strictEqual(results[0].tier, EXACT_ID);
});

test("label prefix matches 170 to 177 range", function () {
    var results = rank(ROWS, "17");
    var tiers = {};
    results.forEach(function (r) {
        tiers[r.row.spoolId] = r.tier;
    });
    assert.strictEqual(tiers.s170, LABEL_PREFIX);
    assert.strictEqual(tiers.s175, LABEL_PREFIX);

    var resultsAll = rank(ROWS, "1");
    var prefixIds = resultsAll
        .filter(function (r) {
            return r.tier === LABEL_PREFIX;
        })
        .map(function (r) {
            return r.row.spoolId;
        })
        .sort();
    assert.deepStrictEqual(prefixIds, ["s170", "s175", "s177"]);
});

test("fuzzy matches vendor, name, type, and location", function () {
    assert.strictEqual(rank(ROWS, "polyterra")[0].tier, FUZZY);
    assert.strictEqual(rank(ROWS, "prusament")[0].tier, FUZZY);
    assert.strictEqual(rank(ROWS, "petg")[0].tier, FUZZY);
    assert.strictEqual(rank(ROWS, "drybox")[0].tier, FUZZY);
});

test("fuzzy never shadows a higher tier for the same row", function () {
    // "amolen" fuzzy-matches vendor on two rows; neither is an exact/
    // prefix match on anything else in this fixture, so both stay fuzzy.
    var results = rank(ROWS, "amolen");
    var spoolIds = results.map(function (r) {
        return r.row.spoolId;
    });
    assert.deepStrictEqual(spoolIds, ["s177", "s175"]);
    assert.ok(
        results.every(function (r) {
            return r.tier === FUZZY;
        })
    );
});

test("five tier order end to end", function () {
    // A single fixture engineered to hit every tier at once, in the
    // documented order (exact label > exact instanceId > exact _id >
    // label prefix > fuzzy).
    var rows = [
        { spoolId: "A", label: "99", instanceId: "i1", id: "id1", vendor: "V", name: "Fuzzy A", type: "PLA" },
        { spoolId: "B", label: "990", instanceId: "99", id: "id2", vendor: "V", name: "N", type: "PLA" },
        { spoolId: "C", label: "9901", instanceId: "i3", id: "99", vendor: "V", name: "N", type: "PLA" },
        { spoolId: "D", label: "99xyz", instanceId: "i4", id: "id4", vendor: "V", name: "N", type: "PLA" },
        { spoolId: "E", label: "zzz", instanceId: "i5", id: "id5", vendor: "V zz99 fuzzy", name: "N", type: "PLA" },
    ];
    var results = rank(rows, "99");
    assert.deepStrictEqual(
        results.map(function (r) {
            return r.row.spoolId;
        }),
        ["A", "B", "C", "D", "E"]
    );
    assert.deepStrictEqual(
        results.map(function (r) {
            return r.tier;
        }),
        [EXACT_LABEL, EXACT_INSTANCE_ID, EXACT_ID, LABEL_PREFIX, FUZZY]
    );
});

test("empty query returns nothing", function () {
    assert.deepStrictEqual(rank(ROWS, ""), []);
    assert.deepStrictEqual(rank(ROWS, "   "), []);
});

test("no match returns nothing", function () {
    assert.deepStrictEqual(rank(ROWS, "nonexistent-xyz"), []);
});

test("case insensitive", function () {
    assert.strictEqual(rank(ROWS, "AMOLEN").length, 2);
});

var failures = [];
tests.forEach(function (t) {
    try {
        t.fn();
        console.log("ok - " + t.name);
    } catch (err) {
        failures.push({ name: t.name, err: err });
        console.log("FAIL - " + t.name);
        console.log("  " + (err && err.message ? err.message : err));
    }
});

console.log((tests.length - failures.length) + "/" + tests.length + " passed");
if (failures.length > 0) {
    process.exit(1);
}
