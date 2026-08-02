# Copyright (C) 2026 crzykidd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""G-code parsing and extrusion arithmetic.

OWNS: nothing yet. This package is the seam for the per-tool extrusion
    accumulator (``metering/odometer.py``), mm-to-gram conversion
    (``metering/convert.py``), and the slicer config-block parser
    (``metering/gcode_meta.py``), per docs/prd.md Architecture.
DOES NOT OWN: HTTP or Filament DB shapes (``client/``), settings, the write
    journal, or any OctoPrint-facing wiring (``plugin.py``).

PRD rule N-3: this package imports nothing internal, and must never import
``client/``. Enforced by tests/test_import_directions.py.
"""
