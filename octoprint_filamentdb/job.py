# Copyright (C) 2026 crzykidd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Print-lifecycle metering session.

OWNS: when the odometer accumulates -- ``PrintStarted`` resets it and
    starts accumulation, the terminal events (``PrintDone``/``PrintFailed``/
    ``PrintCancelled``) stop accumulation, idempotently, so OctoPrint's
    cancel-then-fail double-fire (``PrintCancelled`` immediately followed
    by ``PrintFailed`` for the same job) is handled exactly once rather
    than being treated as two stops; filtering ``gcode.sent`` lines to
    "only while actually printing" (manual jogs and warm-up commands sent
    outside a job must never count -- FR-5); and the push-throttle
    decision (~1/second) for the live sidebar readout. Delegates all
    G-code arithmetic to ``metering/odometer.py`` and owns no OctoPrint
    hook registration or template/asset wiring itself (``plugin.py``).
DOES NOT OWN: the E-move state machine (``metering/odometer.py``), mm->gram
    conversion, the write journal, retry policy, or the Filament DB commit
    itself -- all later steps (see prompts/2026-08-02-live-mm-readout.md
    scope; this file will grow into the full print-lifecycle orchestrator
    the PRD Architecture describes once those land).
"""

import time

from octoprint.events import Events

from .metering.odometer import Odometer

# PRD §User interface: "throttle the push -- roughly 1/second, not per
# command." A print sends thousands of gcode.sent calls a second; the
# sidebar only needs about one update a second.
PUSH_INTERVAL_SECONDS = 1.0

_TERMINAL_EVENTS = frozenset(
    {Events.PRINT_DONE, Events.PRINT_FAILED, Events.PRINT_CANCELLED}
)


class MeteringSession:
    """Owns the odometer for the currently active (or most recently
    finished) print job, plus the start/stop decisions and push-throttle
    state around it. One instance lives for the lifetime of the plugin.
    """

    def __init__(self):
        self._odometer = Odometer()
        self._accumulating = False
        self._last_push_monotonic = None

    def handle_event(self, event):
        """React to an OctoPrint print-lifecycle event.

        Returns ``True`` if this call changed metering state (started or
        stopped accumulation) so the caller can push an immediate update
        instead of waiting for the next throttle tick; ``False`` if the
        event was ignored (including an idempotent no-op second terminal
        event from the cancel-then-fail double-fire).
        """
        if event == Events.PRINT_STARTED:
            self._odometer.reset()
            self._accumulating = True
            return True

        if event in _TERMINAL_EVENTS:
            if not self._accumulating:
                # Already stopped -- e.g. the PrintFailed that follows
                # every PrintCancelled for the same job. Do not re-stop,
                # and do not touch the odometer: the final total must
                # stay exactly as it was, not be reset or recomputed.
                return False
            self._accumulating = False
            return True

        return False

    def feed(self, line):
        """Feed one already-sent G-code line to the odometer, but only
        while a print is actually in progress -- filtering on tracked
        print state, not merely on receiving the hook, so manual jogs and
        warm-up commands sent outside a job never count (FR-5).
        """
        if self._accumulating:
            self._odometer.feed(line)

    @property
    def accumulating(self):
        return self._accumulating

    @property
    def totals(self):
        """Current ``{tool_index: millimetres}`` snapshot."""
        return self._odometer.totals

    def should_push(self, now=None):
        """Throttle gate for the live sidebar push: ``True`` at most once
        per ``PUSH_INTERVAL_SECONDS``. Callers that already know a push is
        warranted (``handle_event`` returned ``True``) should not consult
        this -- it exists to rate-limit the otherwise-per-command
        ``gcode.sent`` volume, not to gate lifecycle transitions.
        """
        if now is None:
            now = time.monotonic()
        if (
            self._last_push_monotonic is None
            or (now - self._last_push_monotonic) >= PUSH_INTERVAL_SECONDS
        ):
            self._last_push_monotonic = now
            return True
        return False
