# Copyright (C) 2026 crzykidd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""In-memory TTL cache in front of ``FilamentDBClient.list_filaments()`` and
``FilamentDBClient.get_locations()``.

OWNS: memoizing the two requests that rarely change -- the whole spool
    library and the location list (added 2026-08-02, C-3b: "cache them
    alongside the filament list; they change rarely") -- a configurable
    TTL (FR-2, default 5 min -- ``settings_keys.
    DEFAULT_CACHE_TTL_SECONDS``, reused for both), and manual
    force-refresh. Takes the client and TTL as call arguments rather than
    holding its own reference to either, so it stays agnostic of where
    settings live and needs no OctoPrint import.
DOES NOT OWN: the HTTP calls themselves (``client/filamentdb.py``), parsing
    (``client/models.py``), or anything about *why* a refresh was
    requested (``api.py``'s "refresh" command, a settings change, ...).

PRD rule N-3: this package imports nothing internal beyond its own sibling
module. Enforced by tests/test_import_directions.py.
"""

import threading
import time


class FilamentCache:
    """One instance lives for the plugin's lifetime (owned by the
    ``SimpleApiPlugin`` mixin in ``api.py``). Thread-safe: a request
    thread and a future background refresh could race otherwise. Caches
    two independent entries (filaments, locations) behind one shared
    lock -- both are small, infrequent, whole-list reads, so there is no
    real concurrency cost to sharing it, and it avoids two near-identical
    TTL implementations."""

    def __init__(self):
        self._entries = {}  # key -> {"value": ..., "fetched_monotonic": ...}
        self._lock = threading.Lock()

    def _get_cached(self, key, fetch_fn, ttl_seconds, force_refresh, now):
        if now is None:
            now = time.monotonic()

        with self._lock:
            entry = self._entries.get(key)
            stale = (
                entry is None
                or force_refresh
                or (now - entry["fetched_monotonic"]) >= ttl_seconds
            )
            if not stale:
                return entry["value"]

        # Fetch outside the lock -- this is a network call, and holding
        # the lock across it would block every other reader for the
        # request's full duration for no benefit (a second concurrent
        # miss just fetches twice; both results are equally fresh).
        value = fetch_fn()

        with self._lock:
            self._entries[key] = {"value": value, "fetched_monotonic": now}
        return value

    def get(self, client, ttl_seconds, force_refresh=False, now=None):
        """Return the cached ``[FilamentSummary, ...]`` list, fetching via
        ``client.list_filaments()`` if there is no cached value yet, the
        TTL has elapsed, or ``force_refresh`` is set. Raises whatever
        ``client.list_filaments()`` raises (a ``FilamentDBError``
        subclass) on a fetch, leaving any previously cached value intact
        so a transient outage doesn't blank an already-loaded picker.
        """
        return self._get_cached(
            "filaments", client.list_filaments, ttl_seconds, force_refresh, now
        )

    def get_locations(self, client, ttl_seconds, force_refresh=False, now=None):
        """Return the cached ``[Location, ...]`` list, same staleness rules
        as ``get()`` but tracked independently -- a filament-library
        refresh does not force a location refetch and vice versa. Raises
        whatever ``client.get_locations()`` raises, same "keep the stale
        value on a transient outage" behaviour as ``get()``.
        """
        return self._get_cached(
            "locations", client.get_locations, ttl_seconds, force_refresh, now
        )
