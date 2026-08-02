# Copyright (C) 2026 crzykidd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""OctoPrint plugin wiring: mixin composition and lifecycle only.

OWNS: the ``FilamentDBPlugin`` mixin class -- the settings/template/asset
    declarations OctoPrint calls directly, startup logging, and the
    ``octoprint.access.permissions`` hook (FR-10; see the CLAUDE.md task
    routing table).
DOES NOT OWN: any decision logic. This is the file PRD rule N-5 is about --
    the moment a method here does more than call into another module or
    return a fixed shape, it has outgrown this file. Print-lifecycle
    handling lands in job.py, not in on_event() below.
"""

from octoprint.access import ADMIN_GROUP, USER_GROUP
from octoprint.plugin import (
    AssetPlugin,
    EventHandlerPlugin,
    SettingsPlugin,
    StartupPlugin,
    TemplatePlugin,
)

from . import settings_keys
from ._version import __version__


def get_permissions():
    """``octoprint.access.permissions`` hook: declare this plugin's permissions.

    Two permissions (FR-10), replacing the ``admin_permission`` blanket check
    removed in OctoPrint 2.0 (C-6):

    - ``PLUGIN_FILAMENTDB_SELECT`` -- view spools, assign them to tools, view
      the write journal, retry a failed write. Granted to Operator
      (``USER_GROUP``) by default.
    - ``PLUGIN_FILAMENTDB_ADMIN`` -- change plugin settings, discard or
      bulk-modify journal entries. Admin only by default: destroying the
      record of consumed filament is an admin action.
    """
    return [
        {
            "key": "SELECT",
            "name": "Select spools",
            "description": (
                "View spools, assign them to tools, view the write "
                "journal, and retry a failed write."
            ),
            "roles": ["select"],
            "dangerous": False,
            "default_groups": [USER_GROUP],
        },
        {
            "key": "ADMIN",
            "name": "Administer Filament DB settings",
            "description": (
                "Change plugin settings (URL, API key, check modes), and "
                "discard or bulk-modify journal entries."
            ),
            "roles": ["admin"],
            "dangerous": True,
            "default_groups": [ADMIN_GROUP],
        },
    ]


class FilamentDBPlugin(
    SettingsPlugin,
    AssetPlugin,
    TemplatePlugin,
    StartupPlugin,
    EventHandlerPlugin,
):
    """Mixin composition root for the ``filamentdb`` plugin. Wiring only (N-5)."""

    # -- SettingsPlugin -------------------------------------------------

    def get_settings_defaults(self):
        return settings_keys.get_settings_defaults()

    def get_settings_restricted_paths(self):
        # The API key must never be returned to a non-admin viewer or land
        # in a support bundle (FR-1).
        return {"admin": [[settings_keys.FILAMENT_DB_API_KEY]]}

    def get_settings_version(self):
        return 1

    # -- TemplatePlugin -------------------------------------------------

    def get_template_configs(self):
        return [
            {
                "type": "sidebar",
                "template": "filamentdb_sidebar.jinja2",
                "custom_bindings": True,
                "icon": "cube",
            },
            {
                "type": "settings",
                "template": "filamentdb_settings.jinja2",
                "custom_bindings": True,
                "icon": "cube",
            },
        ]

    # -- AssetPlugin ------------------------------------------------------

    def get_assets(self):
        return {
            "js": ["js/filamentdb.js"],
            "css": ["css/filamentdb.css"],
        }

    def is_template_autoescaped(self):
        # Opt in to Jinja autoescaping now rather than waiting for OctoPrint
        # 2.1.0 to force it. Our templates never push raw HTML through a
        # variable, so this costs nothing.
        return True

    # -- StartupPlugin ----------------------------------------------------

    def on_after_startup(self):
        # No network calls here -- the connectivity probe (FR-1) is a
        # separate, later concern; this method stays wiring-only (N-5).
        self._logger.info("FilamentDB plugin v%s loaded", __version__)

    # -- EventHandlerPlugin -----------------------------------------------

    def on_event(self, event, payload):
        # Registered now so the print-lifecycle hook exists; the actual
        # start/pause/resume/terminal handling lands in job.py (not yet
        # written -- see prompts/startnewsession.md for sequencing) and gets
        # delegated to from here.
        pass
