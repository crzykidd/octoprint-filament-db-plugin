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
var INSTANCE_ID_PREFIX = FilamentDBSearch.TIER_INSTANCE_ID_PREFIX;
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

test("exact label beats an instanceId-prefix hit on a different row", function () {
    // "9" is spool sfuzzy's exact label -- assert the tier assignment
    // itself, not just ordering. It also happens to prefix-match s177's
    // instanceId ("970fdbcd56"), which is fine: that's the instanceId
    // prefix tier doing its job, just ranked below the exact label.
    var results = rank(ROWS, "9");
    assert.strictEqual(results[0].row.spoolId, "sfuzzy");
    assert.strictEqual(results[0].tier, EXACT_LABEL);
    assert.strictEqual(results[1].row.spoolId, "s177");
    assert.strictEqual(results[1].tier, INSTANCE_ID_PREFIX);
    assert.strictEqual(results.length, 2);
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

test("instanceId prefix matches without needing the full 10 hex chars", function () {
    // Confirmed-by-bug case (2026-08-02 picker UI fixes, fix 3): "970fdb"
    // used to return no match at all -- instanceId was only ever checked
    // for a full exact hit, and fuzzyHit() doesn't look at it either.
    var results = rank(ROWS, "970fdb");
    assert.strictEqual(results.length, 1);
    assert.strictEqual(results[0].row.spoolId, "s177");
    assert.strictEqual(results[0].tier, INSTANCE_ID_PREFIX);
});

test("instanceId prefix ranks below label prefix but above fuzzy", function () {
    var rows = [
        { spoolId: "A", label: "99", instanceId: "zzzzzzzzzz", id: "id1", vendor: "V", name: "N", type: "PLA" },
        { spoolId: "B", label: "1", instanceId: "99aaaaaaaa", id: "id2", vendor: "V", name: "N", type: "PLA" },
        { spoolId: "C", label: "1", instanceId: "zzzzzzzzzz", id: "id3", vendor: "99 fuzzy vendor", name: "N", type: "PLA" },
    ];
    var results = rank(rows, "99");
    assert.deepStrictEqual(
        results.map(function (r) {
            return r.row.spoolId;
        }),
        ["A", "B", "C"]
    );
    assert.deepStrictEqual(
        results.map(function (r) {
            return r.tier;
        }),
        [EXACT_LABEL, INSTANCE_ID_PREFIX, FUZZY]
    );
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

test("six tier order end to end", function () {
    // A single fixture engineered to hit every tier at once, in the
    // documented order (exact label > exact instanceId > exact _id >
    // label prefix > instanceId prefix > fuzzy).
    var rows = [
        { spoolId: "A", label: "99", instanceId: "i1", id: "id1", vendor: "V", name: "Fuzzy A", type: "PLA" },
        { spoolId: "B", label: "990", instanceId: "99", id: "id2", vendor: "V", name: "N", type: "PLA" },
        { spoolId: "C", label: "9901", instanceId: "i3", id: "99", vendor: "V", name: "N", type: "PLA" },
        { spoolId: "D", label: "99xyz", instanceId: "i4", id: "id4", vendor: "V", name: "N", type: "PLA" },
        { spoolId: "E", label: "zzz", instanceId: "99abcdef", id: "id5", vendor: "V", name: "N", type: "PLA" },
        { spoolId: "F", label: "zzz2", instanceId: "i6", id: "id6", vendor: "V zz99 fuzzy", name: "N", type: "PLA" },
    ];
    var results = rank(rows, "99");
    assert.deepStrictEqual(
        results.map(function (r) {
            return r.row.spoolId;
        }),
        ["A", "B", "C", "D", "E", "F"]
    );
    assert.deepStrictEqual(
        results.map(function (r) {
            return r.tier;
        }),
        [EXACT_LABEL, EXACT_INSTANCE_ID, EXACT_ID, LABEL_PREFIX, INSTANCE_ID_PREFIX, FUZZY]
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
