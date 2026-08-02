# Copyright (C) 2026 crzykidd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""In-memory TTL cache in front of ``FilamentDBClient.list_filaments()``.

OWNS: memoizing the one request that fetches the whole spool library, a
    configurable TTL (FR-2, default 5 min -- ``settings_keys.
    DEFAULT_CACHE_TTL_SECONDS``), and manual force-refresh. Takes the
    client and TTL as call arguments rather than holding its own
    reference to either, so it stays agnostic of where settings live and
    needs no OctoPrint import.
DOES NOT OWN: the HTTP call itself (``client/filamentdb.py``), parsing
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
    thread and a future background refresh could race otherwise."""

    def __init__(self):
        self._filaments = None
        self._fetched_monotonic = None
        self._lock = threading.Lock()

    def get(self, client, ttl_seconds, force_refresh=False, now=None):
        """Return the cached ``[FilamentSummary, ...]`` list, fetching via
        ``client.list_filaments()`` if there is no cached value yet, the
        TTL has elapsed, or ``force_refresh`` is set. Raises whatever
        ``client.list_filaments()`` raises (a ``FilamentDBError``
        subclass) on a fetch, leaving any previously cached value intact
        so a transient outage doesn't blank an already-loaded picker.
        """
        if now is None:
            now = time.monotonic()

        with self._lock:
            stale = (
                self._filaments is None
                or force_refresh
                or self._fetched_monotonic is None
                or (now - self._fetched_monotonic) >= ttl_seconds
            )
            if not stale:
                return self._filaments

        # Fetch outside the lock -- this is a network call, and holding
        # the lock across it would block every other reader for the
        # request's full duration for no benefit (a second concurrent
        # miss just fetches twice; both results are equally fresh).
        filaments = client.list_filaments()

        with self._lock:
            self._filaments = filaments
            self._fetched_monotonic = now
        return filaments
