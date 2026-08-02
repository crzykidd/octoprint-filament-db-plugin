# Copyright (C) 2026 crzykidd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for octoprint_filamentdb/weights.py -- the net-weight computation
and its degraded paths (C-2, PRD §Weight display).

Case values are taken from the live #177 acceptance target
(prompts/2026-08-02-spool-picker.md) plus the degraded-path spec table so
regressions there are caught the same way a live check would catch them.
"""

import pytest

from octoprint_filamentdb import weights


def test_happy_path_matches_live_spool_177():
    # gross 359.37, tare 190, nominal 1000 -> net 169.37, displayed 169.4.
    result = weights.compute_weight(gross=359.37, tare=190, nominal=1000)
    assert round(result.net_grams, 2) == 169.37
    assert result.text == "169.4 g / 1000 g"
    assert result.tare_missing is False
    assert result.nominal_missing is False
    assert result.gross_missing is False
    assert result.percent == pytest.approx(16.937, rel=1e-3)


def test_happy_path_pretty_round_numbers():
    # PRD sidebar mock: "842.0 g / 1000 g ... 84%".
    result = weights.compute_weight(gross=1032.0, tare=190, nominal=1000)
    assert result.text == "842.0 g / 1000 g"
    assert round(result.percent, 1) == 84.2


def test_tare_missing_never_shown_as_net():
    result = weights.compute_weight(gross=1042, tare=None, nominal=1000)
    assert result.text == "1042 g gross · tare not set"
    assert result.tare_missing is True
    assert result.net_grams is None
    assert result.percent is None


def test_tare_missing_with_fractional_gross():
    result = weights.compute_weight(gross=1042.5, tare=None, nominal=1000)
    assert result.text == "1042.5 g gross · tare not set"


def test_nominal_missing_bare_figure_no_bar():
    result = weights.compute_weight(gross=814, tare=190, nominal=None)
    assert result.net_grams == 624
    assert result.text == "624.0 g"
    assert result.nominal_missing is True
    assert result.percent is None


def test_gross_missing_not_weighed():
    result = weights.compute_weight(gross=None, tare=190, nominal=1000)
    assert result.text == "not weighed"
    assert result.gross_missing is True
    assert result.net_grams is None
    assert result.percent is None


def test_gross_missing_takes_priority_over_missing_tare_and_nominal():
    result = weights.compute_weight(gross=None, tare=None, nominal=None)
    assert result.text == "not weighed"


def test_net_exceeds_nominal_bar_clamps_figure_does_not():
    # Overfilled reel: a "1kg" spool that actually holds 1050g.
    result = weights.compute_weight(gross=1240, tare=190, nominal=1000)
    assert result.net_grams == 1050
    assert result.text == "1050.0 g / 1000 g"
    assert result.percent == 100.0


def test_zero_net_does_not_render_negative_zero():
    result = weights.compute_weight(gross=190, tare=190, nominal=1000)
    assert result.text == "0.0 g / 1000 g"


def test_negative_net_clamped_to_zero_percent_not_hidden():
    # Pathological (over-tared) data -- never crash, never go negative on
    # the bar; the figure itself is still shown honestly.
    result = weights.compute_weight(gross=100, tare=190, nominal=1000)
    assert result.net_grams == -90
    assert result.percent == 0.0
    assert result.text == "-90.0 g / 1000 g"
