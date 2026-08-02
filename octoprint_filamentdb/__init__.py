# Copyright (C) 2026 crzykidd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Plugin entry point: the ``__plugin_*__`` contract OctoPrint's loader reads.

OWNS: plugin metadata (name, identifier, version, description, licence,
    Python compatibility), instantiating ``FilamentDBPlugin``, and wiring the
    ``octoprint.access.permissions`` hook to its declaration.
DOES NOT OWN: the mixin implementation (``plugin.py``) or the permission
    definitions themselves (also ``plugin.py`` -- see the CLAUDE.md task
    routing table). This file only registers what those provide.
"""

from ._version import __version__
from .plugin import FilamentDBPlugin, get_permissions

__plugin_name__ = "Filament DB"
__plugin_identifier__ = "filamentdb"
__plugin_version__ = __version__
__plugin_description__ = (
    "Assigns Filament DB spools to printer tools, meters actual extrusion, "
    "and writes print-history usage back to Filament DB."
)
__plugin_license__ = "AGPL-3.0-or-later"
__plugin_pythoncompat__ = ">=3.9,<4"

__plugin_implementation__ = None
__plugin_hooks__ = {}


def __plugin_load__():
    global __plugin_implementation__, __plugin_hooks__

    __plugin_implementation__ = FilamentDBPlugin()
    __plugin_hooks__ = {
        "octoprint.access.permissions": get_permissions,
    }
