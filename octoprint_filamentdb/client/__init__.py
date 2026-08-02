# Copyright (C) 2026 crzykidd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""HTTP client and Filament DB response shapes.

OWNS: nothing yet. This package is the seam for the requests-based Filament
    DB REST client (``client/filamentdb.py``) and the dataclasses for the
    Filament DB shapes the plugin reads (``client/models.py``), per
    docs/prd.md Architecture.
DOES NOT OWN: G-code parsing or arithmetic (``metering/``), settings, the
    write journal, or any OctoPrint-facing wiring (``plugin.py``).

PRD rule N-3: this package imports nothing internal. Enforced by
tests/test_import_directions.py.
"""
