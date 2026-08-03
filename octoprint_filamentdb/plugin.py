# Copyright (C) 2026 crzykidd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""OctoPrint plugin wiring: mixin composition and lifecycle only.

OWNS: the ``FilamentDBPlugin`` mixin class -- the settings/template/asset
    declarations OctoPrint calls directly, startup logging, the
    ``octoprint.access.permissions`` hook (FR-10; see the CLAUDE.md task
    routing table), forwarding the ``gcode.sent`` hook / print-lifecycle
    events to ``job.MeteringSession``, and composing in the plugin REST API
    (``api.FilamentDBApiMixin``) -- plus the one presentation step of
    formatting metering state into a ``send_plugin_message`` payload for
    the live sidebar readout.
DOES NOT OWN: any decision logic. This is the file PRD rule N-5 is about --
    the moment a method here does more than call into another module or
    return a fixed shape, it has outgrown this file. Every decision about
    *when* the odometer runs, resets, or is due for a throttled push lives
    in ``job.MeteringSession``; every decision about spool data, caching,
    or assignment lives in ``api.py``/``assignment.py``/``client/`` -- none
    of it here.
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
from .api import FilamentDBApiMixin
from .job import MeteringSession


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
    FilamentDBApiMixin,
):
    """Mixin composition root for the ``filamentdb`` plugin. Wiring only (N-5)."""

    def __init__(self):
        super().__init__()
        # One session for the plugin's lifetime; job.py owns everything
        # about when it resets, accumulates, and is due for a push.
        self._lifecycle = MeteringSession()

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
            # Order doesn't affect correctness (every OCTOPRINT_VIEWMODELS
            # constructor runs after all plugin assets have loaded), but
            # is kept dependency-first for readability: the search ranking
            # helper (the sole implementation -- FR-2 needs it client-side,
            # no round trip per keystroke), then the picker (which uses
            # it), then the main viewmodel (which uses both via
            # FilamentDBPicker.attach(self) -- see that file's docstring
            # for why the picker is a separate module at all: keeping
            # filamentdb.js under the 500-line module cap, N-1). Weight
            # computation has no JS port -- it is server-side only
            # (weights.py via api.py/assignment.py); the frontend just
            # renders the `weightText`/`weightPercent` fields it receives.
            "js": [
                "js/filamentdb-search.js",
                "js/filamentdb-picker.js",
                "js/filamentdb.js",
            ],
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
        # job.py decides whether this event starts, stops, or is
        # irrelevant to metering (including collapsing the
        # PrintCancelled-then-PrintFailed double-fire into a single
        # stop). An immediate push on a real transition means the sidebar
        # shows "reset to zero" / "stopped, final total" right away
        # rather than waiting for the next throttle tick.
        if self._lifecycle.handle_event(event):
            self._push_odometer_state()

    # -- gcode.sent hook (the odometer feed) -------------------------------

    def on_gcode_sent(
        self, comm_instance, phase, cmd, cmd_type, gcode, subcode=None, tags=None
    ):
        # job.py decides whether this line counts (only while a print is
        # actually in progress) and whether a throttled push is due.
        # Never returns a replacement -- this hook only observes.
        self._lifecycle.feed(cmd)
        if self._lifecycle.accumulating and self._lifecycle.should_push():
            self._push_odometer_state()

    def _push_odometer_state(self):
        # SockJS push to the frontend (PRD §"Being consumable by
        # dashboards and other plugins", channel 3); the JS side receives
        # this via onDataUpdaterPluginMessage. Formatting a fixed-shape
        # dict from already-decided state is presentation, not a
        # decision, so it stays here rather than in job.py.
        self._plugin_manager.send_plugin_message(
            self._identifier,
            {
                "type": "odometer",
                "printing": self._lifecycle.accumulating,
                "totals": self._lifecycle.totals,
            },
        )
