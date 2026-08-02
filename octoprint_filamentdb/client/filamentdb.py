# Copyright (C) 2026 crzykidd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""``requests``-based Filament DB REST client.

OWNS: the three HTTP calls this plugin makes -- ``list_filaments()``
    (``GET /api/filaments``, the picker's list projection), ``get_spool()``
    (``GET /api/spools/{spoolId}``, the read for an *assigned* spool --
    filament + spool in one call, variant inheritance already resolved,
    C-3), and ``get_version()`` (``GET /api/openapi`` -> ``info.version``,
    the Test Connection probe -- Filament DB has no dedicated health
    endpoint). Optional bearer auth (C-7), a configurable timeout, and
    translating every failure mode (connection refused, timeout, HTTP 401,
    any other non-2xx, malformed JSON) into one of the ``FilamentDBError``
    subclasses below -- never a raw ``requests`` exception -- so a
    Filament DB outage can never escape into OctoPrint's event loop
    un-typed. Callers still must catch ``FilamentDBError`` themselves;
    this module only guarantees the exception is one they can recognize.
DOES NOT OWN: parsing JSON into dataclasses (``client/models.py``), TTL
    caching (``client/cache.py``), or anything that decides *when* to call
    this (``api.py``, ``assignment.py``).

PRD rule N-3: this package imports nothing internal. Enforced by
tests/test_import_directions.py. Unit-testable without OctoPrint or any
live network -- see tests/test_filamentdb_client.py, which injects a fake
``requests``-compatible session.
"""

import requests

from . import models

DEFAULT_TIMEOUT_SECONDS = 5


class FilamentDBError(Exception):
    """Base for every error this client raises. Catch this, not a specific
    subclass, unless the caller genuinely needs to distinguish (e.g. C-7's
    auth failure warranting a different settings-page message)."""


class ConnectionFailed(FilamentDBError):
    """The host was unreachable -- DNS failure, connection refused, etc."""


class RequestTimedOut(FilamentDBError):
    """No response within the configured timeout."""


class AuthenticationFailed(FilamentDBError):
    """HTTP 401 -- ``FILAMENT_DB_API_KEY`` is set server-side and either
    missing or wrong here (C-7)."""


class InvalidResponse(FilamentDBError):
    """A non-2xx status (other than 401) or a 2xx body that is not the
    JSON shape this client expects -- treated identically to a network
    failure by callers, since either way the data cannot be used."""


class FilamentDBClient:
    """One instance per call site is cheap -- it opens no connection until
    a method is called. ``session`` is injectable purely for tests; real
    callers should leave it as the default ``requests.Session()``."""

    def __init__(
        self,
        base_url,
        api_key=None,
        timeout=DEFAULT_TIMEOUT_SECONDS,
        session=None,
    ):
        self._base_url = (base_url or "").rstrip("/")
        self._api_key = api_key or None
        self._timeout = timeout
        self._session = session if session is not None else requests.Session()

    def _headers(self):
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _get(self, path):
        url = f"{self._base_url}{path}"
        try:
            response = self._session.get(
                url, headers=self._headers(), timeout=self._timeout
            )
        except requests.exceptions.Timeout as exc:
            raise RequestTimedOut(
                f"filamentdb.client: {path} timed out after {self._timeout}s"
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise ConnectionFailed(
                f"filamentdb.client: could not connect for {path}"
            ) from exc
        except requests.exceptions.RequestException as exc:
            # Anything else requests can raise (bad URL, too many
            # redirects, ...) -- still never let it escape un-typed.
            raise FilamentDBError(f"filamentdb.client: {path} failed: {exc}") from exc

        if response.status_code == 401:
            raise AuthenticationFailed(
                f"filamentdb.client: {path} returned 401 -- check the API key"
            )
        if not response.ok:
            raise InvalidResponse(
                f"filamentdb.client: {path} returned HTTP {response.status_code}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise InvalidResponse(
                f"filamentdb.client: {path} response body was not valid JSON"
            ) from exc

    def list_filaments(self):
        """``GET /api/filaments`` -- the whole library in one call, no
        pagination to use. Returns ``[FilamentSummary, ...]``."""
        raw = self._get("/api/filaments")
        if not isinstance(raw, list):
            raise InvalidResponse(
                "filamentdb.client: /api/filaments did not return a JSON array"
            )
        return [models.parse_filament_summary(item) for item in raw]

    def get_spool(self, spool_id):
        """``GET /api/spools/{spoolId}`` -- the read for an *assigned*
        spool (C-3). Returns a ``SpoolDetail`` with the filament's variant
        inheritance already resolved server-side, including ``diameter``
        (absent from the list projection)."""
        raw = self._get(f"/api/spools/{spool_id}")
        if not isinstance(raw, dict) or "filament" not in raw or "spool" not in raw:
            raise InvalidResponse(
                f"filamentdb.client: /api/spools/{spool_id} had an unexpected shape"
            )
        return models.parse_spool_detail(raw)

    def get_version(self):
        """``GET /api/openapi`` -> ``info.version`` -- there is no
        dedicated health endpoint, so this doubles as the Test Connection
        probe (FR-1)."""
        raw = self._get("/api/openapi")
        try:
            return raw["info"]["version"]
        except (TypeError, KeyError) as exc:
            raise InvalidResponse(
                "filamentdb.client: /api/openapi had no info.version"
            ) from exc
