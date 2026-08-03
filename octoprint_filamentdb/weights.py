# Copyright (C) 2026 crzykidd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Spool remaining-weight computation and display formatting (C-2 / PRD
§"Weight display").

OWNS: the gross-to-net weight computation for an assigned spool --
    ``net = spool.totalWeight - filament.spoolWeight`` over
    ``filament.netFilamentWeight`` -- and the three degraded paths when
    tare, nominal, or gross itself is missing (never show gross as if it
    were net), plus the progress-bar clamp when net exceeds nominal on an
    overfilled reel. Pure: plain numbers in, a small immutable result out.
    **This is the sole implementation** -- there is no JS port. The
    frontend (``static/js/filamentdb.js``, ``filamentdb-picker.js``)
    consumes the ``weightText``/``weightPercent`` fields ``api.py`` and
    ``assignment.py`` compute by calling into this module server-side; it
    contains no weight arithmetic of its own (see docs/decisions.md for
    why the earlier hand-synced JS port was removed). Also computes
    ``picker_text`` -- the picker column's own compact "net / gross"
    format (2026-08-02 picker UI fixes), distinct from ``text`` because the
    picker's narrow Weight column drops the nominal (every filament in the
    library has the same 1000 g one, so it carries no information) in
    favour of the number you'd actually read off a scale. The sidebar
    keeps using ``text`` unchanged -- it has room for the full ratio and a
    different job.
DOES NOT OWN: fetching those numbers from Filament DB (``client/``), where
    an assignment is stored (``assignment.py`` -- calls this module to
    annotate what it returns, but doesn't own the computation), the mm->gram
    *extrusion* conversion during a print (``metering/convert.py``, a later
    step and a different computation entirely -- a live meter reading of
    filament consumed, not a spool's static remaining stock), or deciding
    which endpoints attach a weight (``api.py``).
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class WeightDisplay:
    """Everything the sidebar/picker needs to render one spool's weight."""

    net_grams: Optional[float]  # None only when gross itself is unknown
    nominal_grams: Optional[float]
    gross_grams: Optional[float]
    tare_missing: bool
    nominal_missing: bool
    gross_missing: bool
    percent: Optional[float]  # 0-100, clamped; None when there is no bar
    text: str  # the string to render, e.g. "169.4 g / 1000 g"
    picker_text: str  # the picker column's own format, e.g. "169.4 / 359.4 g"
    # -- degraded paths share `text` verbatim (no scale figure can be
    # invented without both gross and tare); otherwise "{net} / {gross} g".


def _normalize_zero(value):
    # Guard against -0.0 serializing/printing as "-0.0" (PRD FR-6 rounding
    # rule; applies here too since this is the same "never show a negative
    # zero" concern for any grams figure).
    return 0.0 if value == 0 else value


def _fixed1(value):
    """Always exactly one decimal place -- used for the net figure, which
    is the headline number and, per the live #177 acceptance target
    (169.37 -> "169.4 g"), is rounded to and always shown with 1 dp even
    when that decimal is a trailing zero (matches the PRD sidebar mock's
    "842.0 g")."""
    return f"{_normalize_zero(round(value, 1)):.1f}"


def _trim(value):
    """Whole numbers render without a decimal ("1000"); anything else gets
    one decimal place ("1234.5"). Used for the nominal and gross-only
    figures, which are typically round manufacturer numbers -- contrast
    with `_fixed1`, used for the always-computed net figure."""
    rounded = _normalize_zero(round(value, 1))
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.1f}"


def format_grams(value):
    """Trim-format a bare grams figure the same way the nominal/gross-only
    weight text does (see ``_trim``) -- exposed publicly for callers that
    need a formatted number outside a full ``compute_weight()`` result,
    e.g. the sidebar's gross/tare hover tooltip, which shows both figures
    unconditionally regardless of which (if any) degraded path applies.
    Returns ``None`` for ``None`` input so the caller supplies its own
    "unknown"/"not set" copy rather than this module inventing UI text for
    a context it doesn't otherwise own.
    """
    return None if value is None else _trim(value)


def compute_weight(gross, tare, nominal):
    """``gross`` = ``spool.totalWeight``, ``tare`` = ``filament.spoolWeight``,
    ``nominal`` = ``filament.netFilamentWeight``. Any of the three may be
    ``None`` -- every real spool in the dev library has all three
    populated, but the degraded paths are reachable (PRD §Weight display)
    and must never present gross as if it were net.
    """
    if gross is None:
        # The spool exists but has never been weighed -- nothing to show,
        # tare/nominal are moot. No scale figure is computable either.
        return WeightDisplay(
            net_grams=None,
            nominal_grams=nominal,
            gross_grams=None,
            tare_missing=tare is None,
            nominal_missing=nominal is None,
            gross_missing=True,
            percent=None,
            text="not weighed",
            picker_text="not weighed",
        )

    if tare is None:
        # Never show gross as if it were net -- it overstates remaining
        # filament by the weight of the reel (~200 g). Label it explicitly.
        # Still no scale figure: net is unknown without a tare.
        degraded_text = f"{_trim(gross)} g gross · tare not set"
        return WeightDisplay(
            net_grams=None,
            nominal_grams=nominal,
            gross_grams=gross,
            tare_missing=True,
            nominal_missing=nominal is None,
            gross_missing=False,
            percent=None,
            text=degraded_text,
            picker_text=degraded_text,
        )

    net = gross - tare
    # Gross and net are both known from here on regardless of whether
    # nominal is -- the picker's scale figure never depends on the
    # nominal, only on gross/tare, so it's the same in both branches below.
    picker_text = f"{_fixed1(net)} / {_trim(gross)} g"

    if nominal is None or nominal <= 0:
        # A ratio needs both halves -- bare figure, no denominator, no bar.
        return WeightDisplay(
            net_grams=net,
            nominal_grams=nominal,
            gross_grams=gross,
            tare_missing=False,
            nominal_missing=True,
            gross_missing=False,
            percent=None,
            text=f"{_fixed1(net)} g",
            picker_text=picker_text,
        )

    # Net may legitimately exceed nominal on an overfilled reel. Clamp the
    # bar at 100% but always show the true figure -- never clamp the
    # number itself.
    percent = max(0.0, min(100.0, (net / nominal) * 100.0))
    return WeightDisplay(
        net_grams=net,
        nominal_grams=nominal,
        gross_grams=gross,
        tare_missing=False,
        nominal_missing=False,
        gross_missing=False,
        percent=percent,
        text=f"{_fixed1(net)} g / {_trim(nominal)} g",
        picker_text=picker_text,
    )
