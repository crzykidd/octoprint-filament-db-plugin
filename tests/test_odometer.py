# Copyright (C) 2026 crzykidd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the extrusion odometer (PRD FR-5, N-7: mirrors
``octoprint_filamentdb/metering/odometer.py``).

OWNS: verifying the E-move state machine -- relative/absolute mode via
    M82/M83 and G90/G91, G92 origin resets, T<n> tool routing, G2/G3 arc
    extrusion, and retraction netting -- including the one assertion that
    matters most: agreement with real firmware output, not invented
    numbers (tests/fixtures/serial/mmu3-filament-change-runout.md).
DOES NOT OWN: mm->gram conversion, print-lifecycle wiring, or anything
    OctoPrint-facing.
"""

import pytest

from octoprint_filamentdb.metering.odometer import Odometer, accumulate

# The exact "Send:" lines between N2386 (G92 E0.0) and N2406 (M114) from
# tests/fixtures/serial/mmu3-filament-change-runout.md, captured from real
# Prusa MK3-class + MMU3 firmware. The file's header confirms relative
# extrusion (M83) is already active by this point, and the firmware's own
# M114 reply at N2406 reports E:4.05 -- the fixture's table works this out
# to 4.05109mm exactly. This is real hardware ground truth, not invented
# data (see docs/prd.md FR-5 and CLAUDE.md "no copied source, cite prior
# art" -- this is our own captured fixture, not anyone else's code).
MMU3_FIXTURE_LINES = [
    "N2386 G92 E0.0*102",
    "N2387 G1 E-.7 F2700*36",
    "N2388 G1 X109.069 Y126.235 Z1.8 F21000*22",
    "N2389 G1 X107.258 Y126.581 Z2 F6676.326*47",
    "N2390 G1 X107.258 Y126.581 F21000*68",
    "N2391 G1 Z2 F720*10",
    "N2392 G1 E.7 F1500*12",
    "N2393 M204 P6000*104",
    "N2394 G1 F3567*117",
    "N2395 G1 X107.258 Y98.659 E.94513*87",
    "N2396 G1 X135.179 Y98.659 E.94509*94",
    "N2397 G1 X135.179 Y126.581 E.94513*102",
    "N2398 G1 X107.318 Y126.581 E.94306*111",
    "N2399 M204 P3000*103",
    "N2400 G1 X106.851 Y126.988 F21000*77",
    "N2401 M204 P6000*100",
    "N2402 G1 F10200*73",
    "N2403 G1 X106.851 Y98.252 E.97268*90",
    "N2404 G1 E-0.70000 F2100.000*0",
    "N2405 M400*20",
    "N2406 M114*23",
]


def test_matches_real_mmu3_firmware_e_readout():
    """The required assertion (see the handoff prompt): sums to
    4.05109mm, matching the firmware's own M114 E:4.05 reply exactly.
    Covers M83, a G92 reset, and a retract/prime pair netting to zero in
    one real-hardware sequence.
    """
    odometer = Odometer()
    odometer.feed("M83")  # relative extrusion mode, established earlier in the file
    odometer.feed_lines(MMU3_FIXTURE_LINES)
    assert odometer.totals[0] == pytest.approx(4.05109, abs=1e-5)


def test_absolute_mode_m82_computes_deltas_from_last_position():
    lines = [
        "M82",
        "G1 X10 E1.5",
        "G1 X20 E3.0",
        "G1 X30 E2.0",  # retract: absolute E goes backwards
    ]
    totals = accumulate(lines)
    assert totals[0] == pytest.approx(1.5 + 1.5 - 1.0)


def test_default_mode_is_absolute_until_declared():
    # No M82/M83 seen at all -- Marlin default is absolute.
    totals = accumulate(["G1 X10 E5", "G1 X20 E5"])
    # First move: delta from implicit origin 0 -> 5. Second move: already
    # at E5, so no further extrusion -- NOT a phantom +5.
    assert totals[0] == pytest.approx(5.0)


def test_g92_resets_origin_mid_stream_in_absolute_mode():
    lines = [
        "M82",
        "G1 E5",  # 0 -> 5, delta 5
        "G92 E0",  # reset origin to 0, no extrusion
        "G1 E2",  # 0 -> 2, delta 2
    ]
    totals = accumulate(lines)
    assert totals[0] == pytest.approx(7.0)


def test_g92_in_relative_mode_has_no_accumulation_effect():
    lines = [
        "M83",
        "G1 E1.0",
        "G92 E0",  # bookkeeping only; relative deltas don't depend on origin
        "G1 E1.0",
    ]
    totals = accumulate(lines)
    assert totals[0] == pytest.approx(2.0)


def test_arc_moves_g2_g3_contribute_e():
    lines = [
        "M83",
        "G2 X10 Y10 I5 J5 E1.0",
        "G3 X0 Y0 I-5 J-5 E1.0",
    ]
    totals = accumulate(lines)
    assert totals[0] == pytest.approx(2.0)


def test_tool_change_routes_extrusion_to_new_index():
    lines = [
        "M83",
        "G1 E1.0",  # T0 implicit
        "T1",
        "G1 E2.0",
        "T0",
        "G1 E0.5",
    ]
    totals = accumulate(lines)
    assert totals[0] == pytest.approx(1.5)
    assert totals[1] == pytest.approx(2.0)


def test_retraction_prime_pair_nets_to_zero():
    lines = [
        "M83",
        "G1 E-0.8",
        "G1 E0.8",
    ]
    totals = accumulate(lines)
    assert totals[0] == pytest.approx(0.0)


def test_g90_g91_govern_e_when_no_explicit_m82_m83_override():
    # Marlin: G90/G91 set E mode too, absent a later M82/M83 override.
    lines = [
        "G91",
        "G1 E1.0",  # relative: delta 1.0
        "G90",
        "G1 E1.0",  # absolute: last position was implicitly 0 -> delta 1.0
        "G1 E1.0",  # absolute: already at 1.0 -> delta 0.0
    ]
    totals = accumulate(lines)
    assert totals[0] == pytest.approx(2.0)


def test_reset_clears_all_state():
    odometer = Odometer()
    odometer.feed("M83")
    odometer.feed("G1 E5.0")
    assert odometer.totals[0] == pytest.approx(5.0)

    odometer.reset()
    assert odometer.totals == {}
    # Mode reverts to the Marlin default (absolute) too.
    odometer.feed("G1 E5.0")
    assert odometer.totals[0] == pytest.approx(5.0)


def test_lowercase_and_whitespace_tolerant():
    lines = ["m83", "g1 e1.5", "t1", "g1 e0.5"]
    totals = accumulate(lines)
    assert totals[0] == pytest.approx(1.5)
    assert totals[1] == pytest.approx(0.5)


def test_non_extrusion_commands_are_ignored():
    lines = ["M83", "G1 X10 Y10 F3000", "M204 P3000", "G28"]
    totals = accumulate(lines)
    assert totals == {}
