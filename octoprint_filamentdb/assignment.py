# Copyright (C) 2026 crzykidd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The single choke point for reading and writing which spool is loaded on
which tool.

OWNS: the shape of a stored assignment record -- ids plus cached display
    fields, self-sufficient per FR-7's later snapshot semantics -- the
    ``source`` field (``"manual"`` for now; an FR-11/FR-14 seam for a
    future NFC or slot-writeback origin), reading/writing
    ``plugins.filamentdb.selectedSpools`` in settings, and pushing a
    ``send_plugin_message`` update after every change so every open tab
    stays in sync. **Every** assign/clear in the plugin must go through
    ``set()``/``clear()`` here rather than touching settings directly --
    today that means the picker UI via ``api.py``, and it is also the one
    place a future write path (FR-11 slot writeback, FR-14 NFC) hooks in
    without duplicating this logic. Callable from any thread, not just a
    Flask request handler -- a future NFC read reaches this from a serial
    hook's thread, not a request thread, which is also why this class
    holds a lock around its own read-modify-write rather than relying on
    Flask's per-request isolation.
DOES NOT OWN: fetching a spool's detail from Filament DB (``client/``), the
    weight computation (``weights.py``), or the REST endpoints that call
    this (``api.py``).
"""

import threading
from datetime import datetime, timezone

from . import settings_keys


class AssignmentStore:
    def __init__(self, settings, plugin_manager, plugin_identifier):
        self._settings = settings
        self._plugin_manager = plugin_manager
        self._identifier = plugin_identifier
        self._lock = threading.Lock()

    def all(self):
        """The full ``{tool_index_str: record}`` map currently stored."""
        return dict(self._settings.get([settings_keys.SELECTED_SPOOLS]) or {})

    def get(self, tool_index):
        return self.all().get(str(tool_index))

    def find_tool_for_spool(self, spool_id):
        """Return the tool-index key (e.g. ``"0"``) a spool is already
        assigned to, or ``None``. Backs the picker's duplicate-assignment
        badge (FR-2) -- warn, never block: one physical spool usually
        cannot be in two slots, but declaring a printer setup impossible
        is not this plugin's place."""
        for tool_key, record in self.all().items():
            if record and record.get("spoolId") == spool_id:
                return tool_key
        return None

    def set(self, tool_index, filament, spool, source="manual"):
        """Assign ``spool`` (a ``client.models.SpoolSummary``, the spool
        half of a ``get_spool()`` result) of ``filament`` (a
        ``client.models.FilamentDetail``) to ``tool_index``. Builds and
        persists the stored record, then pushes an update. Returns the
        record written.
        """
        record = {
            "filamentId": filament.id,
            "spoolId": spool.id,
            "instanceId": spool.instance_id,
            "source": source,
            "assignedAt": datetime.now(timezone.utc).isoformat(),
            # Cached display fields -- self-sufficient for offline
            # rendering and, later, FR-7's job-time snapshot -- never
            # re-derived from a live fetch just to draw the sidebar.
            "display": {
                "vendor": filament.vendor,
                "name": filament.name,
                "type": filament.type,
                "color": filament.color,
                "label": spool.label,
                "totalWeight": spool.total_weight,
                "spoolWeight": filament.spool_weight,
                "netFilamentWeight": filament.net_filament_weight,
                "density": filament.density,
                "diameter": filament.diameter,
            },
        }
        with self._lock:
            current = self.all()
            current[str(tool_index)] = record
            self._settings.set([settings_keys.SELECTED_SPOOLS], current)
            self._settings.save()
        self._push()
        return record

    def clear(self, tool_index):
        """Remove the assignment for ``tool_index``, if any. Returns
        ``True`` if something was actually cleared."""
        with self._lock:
            current = self.all()
            removed = current.pop(str(tool_index), None)
            if removed is None:
                return False
            self._settings.set([settings_keys.SELECTED_SPOOLS], current)
            self._settings.save()
        self._push()
        return True

    def _push(self):
        if self._plugin_manager is None:
            return
        self._plugin_manager.send_plugin_message(
            self._identifier,
            {"type": "assignment", "selectedSpools": self.all()},
        )
