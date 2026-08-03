# Copyright (C) 2026 crzykidd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Plugin REST endpoints for the frontend: list/search spools, assign,
clear, test connection, force refresh.

OWNS: the ``SimpleApiPlugin`` surface at ``/api/plugin/filamentdb`` -- GET
    returns the cached, flattened spool library, the location list (added
    2026-08-02, C-3b -- resolves a spool's ``locationId`` to a display
    name; a location-fetch failure logs and degrades to an empty list
    rather than failing the whole GET, since it's display-only and the
    filament library is the essential payload) plus current assignments
    (search itself runs client-side over this, FR-2); POST commands
    ``assign``, ``clear``, ``test_connection``, ``refresh``. Permission
    enforcement per FR-10: ``FILAMENTDB_SELECT`` to view/assign/clear/
    refresh, ``FILAMENTDB_ADMIN`` for ``test_connection`` (a settings-page
    action). Builds a ``FilamentDBClient`` from the plugin's current
    settings on every call (cheap -- no connection opens until a request
    is made) and owns the ``FilamentCache`` instance's lifetime. Never
    returns the API key.
DOES NOT OWN: the HTTP client itself (``client/filamentdb.py``), the
    assignment choke point (``assignment.py`` -- this module calls it,
    never writes settings directly, and that module does its own weight
    annotation on everything it returns), or weight arithmetic
    (``weights.py`` -- called here only to annotate each spool in the
    library listing (both the sidebar's ``weightText`` and the picker's
    own compact ``weightPickerText``) and the assign response, not
    stored).
"""

import flask
from octoprint.access.permissions import Permissions
from octoprint.plugin import SimpleApiPlugin

from . import settings_keys, weights
from .assignment import AssignmentStore
from .client.cache import FilamentCache
from .client.filamentdb import FilamentDBClient, FilamentDBError


def _serialize_spool(spool, filament):
    # Each spool is decorated with its computed weight here -- the picker
    # (the list/search endpoint's consumer) renders `weightText`/
    # `weightPickerText` directly rather than recomputing client-side (C-2;
    # weights.py is the sole implementation, see its module docstring).
    weight = weights.compute_weight(
        spool.total_weight, filament.spool_weight, filament.net_filament_weight
    )
    return {
        "id": spool.id,
        "instanceId": spool.instance_id,
        "label": spool.label,
        "totalWeight": spool.total_weight,
        "retired": spool.retired,
        "locationId": spool.location_id,
        "weightText": weight.text,
        "weightPercent": weight.percent,
        # The picker column's own compact format ("169.4 / 359.4 g", no
        # nominal) -- see weights.py's WeightDisplay.picker_text docstring.
        # The sidebar keeps using weightText unchanged.
        "weightPickerText": weight.picker_text,
    }


def _serialize_location(location):
    return {"id": location.id, "name": location.name}


def _serialize_filament(filament):
    return {
        "id": filament.id,
        "name": filament.name,
        "vendor": filament.vendor,
        "type": filament.type,
        "color": filament.color,
        "density": filament.density,
        "spoolWeight": filament.spool_weight,
        "netFilamentWeight": filament.net_filament_weight,
        "parentId": filament.parent_id,
        "spools": [_serialize_spool(s, filament) for s in filament.spools],
    }


class FilamentDBApiMixin(SimpleApiPlugin):
    """Mixed into ``FilamentDBPlugin`` (``plugin.py``). Relies on
    ``self._settings``, ``self._plugin_manager``, ``self._identifier`` and
    ``self._logger``, all injected by OctoPrint's plugin loader onto any
    concrete ``Plugin`` subclass -- *after* construction, which is why the
    cache and assignment store below are built lazily rather than in
    ``__init__`` (none of those attributes exist yet at that point)."""

    _cache = None
    _assignment_store_instance = None

    def _filament_cache(self):
        if self._cache is None:
            self._cache = FilamentCache()
        return self._cache

    def _assignment_store(self):
        if self._assignment_store_instance is None:
            self._assignment_store_instance = AssignmentStore(
                self._settings, self._plugin_manager, self._identifier
            )
        return self._assignment_store_instance

    def _client(self):
        return FilamentDBClient(
            base_url=self._settings.get([settings_keys.FILAMENT_DB_URL]),
            api_key=self._settings.get([settings_keys.FILAMENT_DB_API_KEY]),
            timeout=self._settings.get_int([settings_keys.REQUEST_TIMEOUT]),
        )

    # -- SimpleApiPlugin --------------------------------------------------

    def is_api_protected(self):
        # Require a logged-in user before OctoPrint even forwards a
        # request here (added in OctoPrint 1.11.2 -- overriding is
        # mandatory or a startup warning is logged). The permission
        # checks below are still what actually enforce FR-10; this is a
        # coarser first gate.
        return True

    def get_api_commands(self):
        return {
            "assign": ["toolIndex", "spoolId"],
            "clear": ["toolIndex"],
            "test_connection": [],
            "refresh": [],
        }

    def on_api_get(self, request):
        if not Permissions.PLUGIN_FILAMENTDB_SELECT.can():
            flask.abort(403)
        ttl = self._settings.get_int([settings_keys.CACHE_TTL_SECONDS])
        try:
            filaments = self._filament_cache().get(self._client(), ttl)
        except FilamentDBError as exc:
            self._logger.warning("api.py: list_filaments failed: %s", exc)
            return flask.jsonify(error=str(exc)), 502
        try:
            locations = self._filament_cache().get_locations(self._client(), ttl)
        except FilamentDBError as exc:
            # Display-only (C-3b) -- unlike the filament list above, a
            # failure here must not blank the whole picker. Degrade to no
            # names; locationId -> name resolution just falls back to
            # showing nothing (never a raw GUID, never "undefined").
            self._logger.warning("api.py: get_locations failed: %s", exc)
            locations = []
        return flask.jsonify(
            filaments=[_serialize_filament(f) for f in filaments],
            locations=[_serialize_location(loc) for loc in locations],
            selectedSpools=self._assignment_store().all(),
        )

    def on_api_command(self, command, data):
        if command == "test_connection":
            if not Permissions.PLUGIN_FILAMENTDB_ADMIN.can():
                flask.abort(403)
            return self._handle_test_connection()

        if not Permissions.PLUGIN_FILAMENTDB_SELECT.can():
            flask.abort(403)

        if command == "assign":
            return self._handle_assign(data)
        if command == "clear":
            return self._handle_clear(data)
        if command == "refresh":
            return self._handle_refresh()

        flask.abort(400)

    def _handle_test_connection(self):
        try:
            version = self._client().get_version()
        except FilamentDBError as exc:
            self._logger.warning("api.py: test_connection failed: %s", exc)
            return flask.jsonify(connected=False, error=str(exc)), 502
        return flask.jsonify(connected=True, version=version)

    def _handle_refresh(self):
        ttl = self._settings.get_int([settings_keys.CACHE_TTL_SECONDS])
        client = self._client()
        try:
            self._filament_cache().get(client, ttl, force_refresh=True)
        except FilamentDBError as exc:
            self._logger.warning("api.py: refresh failed: %s", exc)
            return flask.jsonify(error=str(exc)), 502
        try:
            # Locations are cached "alongside the filament list" (C-3b) --
            # a manual refresh refreshes both, but a locations-only failure
            # still isn't fatal to the refresh action itself.
            self._filament_cache().get_locations(client, ttl, force_refresh=True)
        except FilamentDBError as exc:
            self._logger.warning("api.py: refresh (locations) failed: %s", exc)
        return flask.jsonify(success=True)

    def _handle_assign(self, data):
        tool_index = data.get("toolIndex")
        spool_id = data.get("spoolId")
        if tool_index is None or not spool_id:
            flask.abort(400)

        try:
            detail = self._client().get_spool(spool_id)
        except FilamentDBError as exc:
            self._logger.warning("api.py: get_spool(%s) failed: %s", spool_id, exc)
            return flask.jsonify(error=str(exc)), 502

        already_assigned_to = self._assignment_store().find_tool_for_spool(spool_id)
        record = self._assignment_store().set(tool_index, detail.filament, detail.spool)
        weight = weights.compute_weight(
            detail.spool.total_weight,
            detail.filament.spool_weight,
            detail.filament.net_filament_weight,
        )
        return flask.jsonify(
            record=record,
            weightText=weight.text,
            weightPercent=weight.percent,
            # Warn at assignment time if the filament has no density (FR-2
            # / FR-6) -- needs only the spool just fetched, no file.
            densityWarning=detail.filament.density is None,
            alreadyAssignedTo=already_assigned_to,
        )

    def _handle_clear(self, data):
        tool_index = data.get("toolIndex")
        if tool_index is None:
            flask.abort(400)
        self._assignment_store().clear(tool_index)
        return flask.jsonify(success=True)
