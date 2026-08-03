# Copyright (C) 2026 crzykidd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-tool extrusion accumulator -- the odometer.

OWNS: the E-move state machine -- ``M82``/``M83`` and ``G90``/``G91``
    extrusion-mode tracking, ``G92`` origin resets, ``T<n>`` tool-change
    routing, and net (not absolute) accumulation of ``G0``/``G1``/``G2``/
    ``G3`` ``E`` deltas into a ``{tool_index: millimetres}`` total. Pure:
    G-code strings in, per-tool millimetre totals out (PRD N-3, N-4).
DOES NOT OWN: mm->gram conversion (``metering/convert.py``, later step),
    what to do with the totals once a print ends (``job.py``, later step),
    filtering to "only while actually printing" (``plugin.py`` -- this
    module has no notion of print state at all), or any OctoPrint/network
    concern whatsoever. No OctoPrint imports, no I/O, no settings object.

Extrusion-mode resolution (PRD FR-5: "track both [M82/M83 and G90/G91] and
resolve per firmware convention, defaulting to Marlin behaviour"): stock
Marlin keeps a single relative/absolute flag per axis including E, so
``G90``/``G91`` set *all* axes -- including E -- together, while ``M82``/
``M83`` override *only* E independently of X/Y/Z. A later ``G90``/``G91``
therefore resets E mode back in step with position mode, discarding any
standing ``M82``/``M83`` override. That is the behaviour implemented here.
In practice, slicers issue ``M83`` once near the top of a file and never
reissue ``G90``/``G91`` mid-print, so this rarely matters -- but it is the
literal Marlin semantics rather than a simplification, and the PRD calls
the interaction out by name.
"""

import re

_LINE_NUMBER_RE = re.compile(r"^[Nn]\d+\s*")
_CHECKSUM_RE = re.compile(r"\*\d+\s*$")
_TOOL_RE = re.compile(r"^[Tt](\d+)$")
_E_PARAM_RE = re.compile(r"^[Ee](-?\d*\.?\d+)$")

_LINEAR_MOVES = {"G0", "G1", "G2", "G3"}


def _clean(line):
    """Strip an inline comment, a leading ``N<n>`` line number, and a
    trailing ``*<checksum>`` -- so the parser below works identically
    whether it is fed a bare command (what the real ``gcode.sent`` hook
    passes -- see docs/decisions.md) or a raw serial capture line (what
    the MMU3 fixture provides for tests).
    """
    line = line.split(";", 1)[0].strip()
    line = _CHECKSUM_RE.sub("", line).strip()
    line = _LINE_NUMBER_RE.sub("", line).strip()
    return line


class Odometer:
    """A per-tool extrusion accumulator. Feed it G-code lines one at a
    time (as they are actually sent to the printer); read back net
    millimetres extruded per tool index at any point.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        """Reinitialize all state -- current tool, extrusion mode, last
        absolute E position per tool, and every tool's accumulated total.
        Called by the print-lifecycle wiring on ``PrintStarted`` (job.py,
        later step); exposed here so tests and callers never need to
        throw away and reconstruct an instance to start a new print.
        """
        self._tool = 0
        self._relative_e = False  # Marlin default: absolute until told otherwise.
        self._last_absolute_e = {}  # tool_index -> last absolute E position seen.
        self._totals = {}  # tool_index -> accumulated net millimetres.

    def feed(self, line):
        """Process one G-code line as it is sent to the printer."""
        command = _clean(line)
        if not command:
            return

        tokens = command.split()
        word = tokens[0].upper()

        tool_match = _TOOL_RE.match(tokens[0])
        if tool_match:
            self._tool = int(tool_match.group(1))
            return

        if word in ("G90", "G91"):
            # Marlin: G90/G91 set ALL axes -- including E -- together,
            # overriding any standing M82/M83.
            self._relative_e = word == "G91"
            return

        if word == "M82":
            self._relative_e = False
            return

        if word == "M83":
            self._relative_e = True
            return

        if word == "G92":
            e_value = self._extract_e(tokens[1:])
            if e_value is not None:
                self._last_absolute_e[self._tool] = e_value
            return

        if word in _LINEAR_MOVES:
            e_value = self._extract_e(tokens[1:])
            if e_value is None:
                return
            if self._relative_e:
                delta = e_value
            else:
                previous = self._last_absolute_e.get(self._tool, 0.0)
                delta = e_value - previous
                self._last_absolute_e[self._tool] = e_value
            self._totals[self._tool] = self._totals.get(self._tool, 0.0) + delta
            return

        # Everything else (M-codes, comments-only lines already stripped,
        # unrecognized commands) carries no extrusion and is ignored.
        # Unsupported-command warnings (M200, G10/G11, M221) are a later
        # step (see prompts/2026-08-02-live-mm-readout.md scope).

    def feed_lines(self, lines):
        """Convenience: feed an iterable of lines in order."""
        for line in lines:
            self.feed(line)

    @property
    def totals(self):
        """Current ``{tool_index: millimetres}`` snapshot. A copy, so
        callers cannot mutate accumulator state through it.
        """
        return dict(self._totals)

    @staticmethod
    def _extract_e(param_tokens):
        for token in param_tokens:
            match = _E_PARAM_RE.match(token)
            if match:
                return float(match.group(1))
        return None


def accumulate(lines):
    """Pure convenience wrapper: a list of G-code strings in, a
    ``{tool_index: millimetres}`` dict out. Matches the "G-code strings
    in, dict out" framing this module is specified by -- the stateful
    ``Odometer`` class above is what the live hook wiring in ``plugin.py``
    actually uses, feeding one line at a time as the printer sends it.
    """
    odometer = Odometer()
    odometer.feed_lines(lines)
    return odometer.totals
