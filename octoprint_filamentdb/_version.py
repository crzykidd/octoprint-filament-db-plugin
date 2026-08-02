# Copyright (C) 2026 crzykidd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Single source of truth for the plugin's version number.

OWNS: the version string, stored bare -- no "v" prefix anywhere (see the
    release-prep-and-cut rule in CLAUDE.md). ``pyproject.toml`` reads this
    value via ``[tool.setuptools.dynamic]``, and ``__init__.py`` reads it for
    ``__plugin_version__``, so neither declares its own copy.
DOES NOT OWN: anything else.
"""

__version__ = "0.0.1"
