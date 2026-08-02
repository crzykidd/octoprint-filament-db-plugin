# Copyright (C) 2026 crzykidd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Plugin entry point: the ``__plugin_*__`` contract OctoPrint's loader reads.

OWNS: plugin metadata (name, identifier, version, description, licence,
    Python compatibility), instantiating ``FilamentDBPlugin``, and wiring
    the ``octoprint.access.permissions`` and ``octoprint.comm.protocol.
    gcode.sent`` hooks to their handlers.
DOES NOT OWN: the mixin implementation (``plugin.py``) or the permission
    definitions themselves (also ``plugin.py`` -- see the CLAUDE.md task
    routing table). This file only registers what those provide.

The ``.plugin`` import is deliberately deferred into ``__plugin_load__()``
rather than sitting at module top level -- see docs/decisions.md. Importing
*any* submodule of this package (e.g. ``octoprint_filamentdb.client.
filamentdb`` or ``octoprint_filamentdb.metering.odometer``, both meant to
be importable standalone per N-4) runs this file first, since Python always
imports a package's ``__init__.py`` before its submodules. A top-level
``from .plugin import ...`` here would therefore pull in ``octoprint``
itself on *every* standalone import of ``client/`` or ``metering/``, even
though neither of those packages imports ``octoprint`` -- defeating the
whole point of keeping them import-clean. ``__plugin_load__()`` is only
ever called by a running OctoPrint process, where ``octoprint`` is
guaranteed importable, so deferring the import there is free.
"""

from ._version import __version__

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

    from .plugin import FilamentDBPlugin, get_permissions

    __plugin_implementation__ = FilamentDBPlugin()
    __plugin_hooks__ = {
        "octoprint.access.permissions": get_permissions,
        "octoprint.comm.protocol.gcode.sent": __plugin_implementation__.on_gcode_sent,
    }
