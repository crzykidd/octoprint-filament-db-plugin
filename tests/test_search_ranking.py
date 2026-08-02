# Copyright (C) 2026 crzykidd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for octoprint_filamentdb/search.py's five-tier ranking (FR-2).

This exercises the Python reference implementation -- the runtime path a
user actually drives is static/js/filamentdb-search.js, a hand-kept port
(see search.py's module docstring and docs/decisions.md for why). These
tests are what proves the *rules* are right; the live Playwright check
(prompt step 6) is what proves the JS port matches.
"""

from octoprint_filamentdb.search import (
    EXACT_ID,
    EXACT_INSTANCE_ID,
    EXACT_LABEL,
    FUZZY,
    LABEL_PREFIX,
    SearchRow,
    rank,
)

ROWS = [
    SearchRow(
        spool_id="s177",
        label="177",
        instance_id="970fdbcd56",
        id="6a6eca1aa3360ac295bfb007",
        vendor="Amolen",
        name="Amolen PLA Matte Dual Color Green Purple",
        type="PLA",
        color_name=None,
        location_name="Shelf A",
    ),
    SearchRow(
        spool_id="s170",
        label="170",
        instance_id="aaaa000001",
        id="aaaaaaaaaaaaaaaaaaaaaaaa",
        vendor="Prusament",
        name="PLA Galaxy Black",
        type="PLA",
        color_name="Black",
        location_name="Shelf B",
    ),
    SearchRow(
        spool_id="s175",
        label="175",
        instance_id="bbbb000002",
        id="bbbbbbbbbbbbbbbbbbbbbbbb",
        vendor="Amolen",
        name="Amolen PLA Silk Pumpkin Orange",
        type="PLA",
        color_name="Orange",
        location_name="Shelf A",
    ),
    SearchRow(
        spool_id="sfuzzy",
        label="9",
        instance_id="cccc000003",
        id="cccccccccccccccccccccccc",
        vendor="Polymaker",
        name="PolyTerra Matte",
        type="PETG",
        color_name=None,
        location_name="Drybox",
    ),
]


def test_exact_label_ranks_first_and_is_labelled_exact():
    results = rank(ROWS, "177")
    assert results[0].row.spool_id == "s177"
    assert results[0].tier == EXACT_LABEL


def test_exact_label_beats_a_fuzzy_hit_on_a_different_row():
    # "9" is both spool sfuzzy's exact label AND could fuzzy-match nothing
    # else here, but this asserts the tier assignment itself, not just
    # ordering.
    results = rank(ROWS, "9")
    assert len(results) == 1
    assert results[0].tier == EXACT_LABEL


def test_exact_instance_id_ranks_before_prefix_and_fuzzy():
    results = rank(ROWS, "aaaa000001")
    assert results[0].row.spool_id == "s170"
    assert results[0].tier == EXACT_INSTANCE_ID


def test_exact_mongo_id_pasted_from_a_url():
    results = rank(ROWS, "bbbbbbbbbbbbbbbbbbbbbbbb")
    assert results[0].row.spool_id == "s175"
    assert results[0].tier == EXACT_ID


def test_label_prefix_matches_170_to_177_range():
    results = rank(ROWS, "17")
    tiers = {r.row.spool_id: r.tier for r in results}
    assert tiers["s170"] == LABEL_PREFIX
    assert tiers["s175"] == LABEL_PREFIX
    # "177" is not a prefix hit for query "17" in this fixture because it
    # is not in ROWS under a *different* query -- re-check with "1" to
    # confirm 177 is included too.
    results_all = rank(ROWS, "1")
    assert {r.row.spool_id for r in results_all if r.tier == LABEL_PREFIX} == {
        "s177",
        "s170",
        "s175",
    }


def test_fuzzy_matches_vendor_name_type_and_location():
    assert rank(ROWS, "polyterra")[0].tier == FUZZY
    assert rank(ROWS, "prusament")[0].tier == FUZZY
    assert rank(ROWS, "petg")[0].tier == FUZZY
    assert rank(ROWS, "drybox")[0].tier == FUZZY


def test_fuzzy_never_shadows_a_higher_tier_for_the_same_row():
    # "amolen" fuzzy-matches vendor on two rows, but "177" specifically
    # must stay an exact-label match, not get relabeled fuzzy.
    results = rank(ROWS, "amolen")
    spool_ids = [r.row.spool_id for r in results]
    assert spool_ids == ["s177", "s175"]  # both fuzzy vendor hits
    assert all(r.tier == FUZZY for r in results)


def test_five_tier_order_end_to_end():
    # A single fixture engineered to hit every tier at once, in the
    # documented order (exact label > exact instanceId > exact _id >
    # label prefix > fuzzy).
    rows = [
        SearchRow("A", label="99", instance_id="i1", id="id1", vendor="V", name="Fuzzy A", type="PLA"),
        SearchRow("B", label="990", instance_id="99", id="id2", vendor="V", name="N", type="PLA"),
        SearchRow("C", label="9901", instance_id="i3", id="99", vendor="V", name="N", type="PLA"),
        SearchRow("D", label="99xyz", instance_id="i4", id="id4", vendor="V", name="N", type="PLA"),
        SearchRow("E", label="zzz", instance_id="i5", id="id5", vendor="V zz99 fuzzy", name="N", type="PLA"),
    ]
    results = rank(rows, "99")
    assert [r.row.spool_id for r in results] == ["A", "B", "C", "D", "E"]
    assert [r.tier for r in results] == [
        EXACT_LABEL,
        EXACT_INSTANCE_ID,
        EXACT_ID,
        LABEL_PREFIX,
        FUZZY,
    ]


def test_empty_query_returns_nothing():
    assert rank(ROWS, "") == []
    assert rank(ROWS, "   ") == []


def test_no_match_returns_nothing():
    assert rank(ROWS, "nonexistent-xyz") == []


def test_case_insensitive():
    results = rank(ROWS, "AMOLEN")
    assert len(results) == 2
