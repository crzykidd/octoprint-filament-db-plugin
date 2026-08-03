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

    Every record handed back to a caller (``all()``, ``get()``, and the
    ``set()``/``clear()`` return value, which is what the websocket
    ``assignment`` push also carries) has its ``display`` dict annotated
    with ``weightText``/``weightPercent`` and the ``grossText``/
    ``tareText`` hover figures, computed fresh from the record's own
    cached ``totalWeight``/``spoolWeight``/``netFilamentWeight`` -- no
    live fetch, so the "self-sufficient for offline rendering" property
    above still holds, just computed server-side instead of by the
    (deleted) JS weights port. The persisted settings record itself stays
    undecorated; annotation happens only on read, so there is nothing to
    migrate for records written before this existed.
DOES NOT OWN: fetching a spool's detail from Filament DB (``client/``), the
    weight computation itself (``weights.py`` -- called here only to
    annotate what this module returns, same relationship ``api.py`` has
    with it), or the REST endpoints that call this (``api.py``).
"""

import threading
from datetime import datetime, timezone

from . import settings_keys, weights


class AssignmentStore:
    def __init__(self, settings, plugin_manager, plugin_identifier):
        self._settings = settings
        self._plugin_manager = plugin_manager
        self._identifier = plugin_identifier
        self._lock = threading.Lock()

    def _raw_all(self):
        """The full ``{tool_index_str: record}`` map exactly as stored --
        undecorated. Internal use only (read-modify-write and lookups that
        don't need the weight annotation); external callers want
        ``all()``."""
        return dict(self._settings.get([settings_keys.SELECTED_SPOOLS]) or {})

    @staticmethod
    def _decorate(record):
        """Return a copy of ``record`` with its ``display`` dict annotated
        with the weight fields the frontend renders -- computed fresh from
        the record's own cached gross/tare/nominal, no live fetch (see the
        module docstring)."""
        if record is None:
            return None
        display = dict(record.get("display") or {})
        weight = weights.compute_weight(
            display.get("totalWeight"),
            display.get("spoolWeight"),
            display.get("netFilamentWeight"),
        )
        display["weightText"] = weight.text
        display["weightPercent"] = weight.percent
        gross_text = weights.format_grams(display.get("totalWeight"))
        tare_text = weights.format_grams(display.get("spoolWeight"))
        display["grossText"] = f"{gross_text} g" if gross_text is not None else None
        display["tareText"] = f"{tare_text} g" if tare_text is not None else None
        decorated = dict(record)
        decorated["display"] = display
        return decorated

    def all(self):
        """The full ``{tool_index_str: record}`` map currently stored, each
        record's ``display`` annotated with computed weight fields (see
        the module docstring)."""
        return {
            tool_key: self._decorate(record)
            for tool_key, record in self._raw_all().items()
        }

    def get(self, tool_index):
        return self.all().get(str(tool_index))

    def find_tool_for_spool(self, spool_id):
        """Return the tool-index key (e.g. ``"0"``) a spool is already
        assigned to, or ``None``. Backs the picker's duplicate-assignment
        badge (FR-2) -- warn, never block: one physical spool usually
        cannot be in two slots, but declaring a printer setup impossible
        is not this plugin's place."""
        for tool_key, record in self._raw_all().items():
            if record and record.get("spoolId") == spool_id:
                return tool_key
        return None

    def set(self, tool_index, filament, spool, source="manual"):
        """Assign ``spool`` (a ``client.models.SpoolSummary``, the spool
        half of a ``get_spool()`` result) of ``filament`` (a
        ``client.models.FilamentDetail``) to ``tool_index``. Builds and
        persists the stored record, then pushes an update. Returns the
        record written, weight-decorated like ``all()``/``get()``.
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
            current = self._raw_all()
            current[str(tool_index)] = record
            self._settings.set([settings_keys.SELECTED_SPOOLS], current)
            self._settings.save()
        self._push()
        return self._decorate(record)

    def clear(self, tool_index):
        """Remove the assignment for ``tool_index``, if any. Returns
        ``True`` if something was actually cleared."""
        with self._lock:
            current = self._raw_all()
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
