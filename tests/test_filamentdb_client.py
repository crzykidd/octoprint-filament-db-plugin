# Copyright (C) 2026 crzykidd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for octoprint_filamentdb/client/filamentdb.py -- mocked HTTP only.
No live network, no OctoPrint. A fake requests-compatible session is
injected via the client's ``session=`` constructor argument (real callers
never pass one)."""

import json

import pytest
import requests

from octoprint_filamentdb.client.filamentdb import (
    AuthenticationFailed,
    ConnectionFailed,
    FilamentDBClient,
    InvalidResponse,
    RequestTimedOut,
)


class FakeResponse:
    def __init__(self, status_code=200, json_body=None, raw_body=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._json_body = json_body
        self._raw_body = raw_body

    def json(self):
        if self._raw_body is not None:
            # Mimic requests: invalid JSON raises a ValueError subclass.
            return json.loads(self._raw_body)
        return self._json_body


class FakeSession:
    """Records the last request made and returns a scripted response (or
    raises a scripted exception) instead of touching the network."""

    def __init__(self, response=None, exception=None):
        self._response = response
        self._exception = exception
        self.last_url = None
        self.last_headers = None
        self.last_timeout = None

    def get(self, url, headers=None, timeout=None):
        self.last_url = url
        self.last_headers = headers
        self.last_timeout = timeout
        if self._exception is not None:
            raise self._exception
        return self._response


FILAMENTS_LIST = [
    {
        "_id": "6a6eca19a3360ac295bfafd9",
        "name": "Amolen PLA Matte Dual Color Green Purple",
        "vendor": "Amolen",
        "type": "PLA",
        "color": None,
        "density": 1.24,
        "spoolWeight": 190,
        "netFilamentWeight": 1000,
        "parentId": "6a6eca19a3360ac295bfafca",
        "spools": [
            {
                "_id": "6a6eca1aa3360ac295bfb007",
                "instanceId": "970fdbcd56",
                "label": "177",
                "totalWeight": 359.37,
                "retired": False,
                "locationId": "6a6eca1aa3360ac295bfafec",
            }
        ],
    }
]

LOCATIONS_LIST = [
    {"_id": "6a385c81a66ab307b7f9b5d3", "name": "Bin 1 - PLA"},
    {"_id": "6a385c81a66ab307b7f9b5d4", "name": "Bin 2 - PETG"},
]

SPOOL_DETAIL = {
    "filament": {
        "_id": "6a6eca19a3360ac295bfafd9",
        "name": "Amolen PLA Matte Dual Color Green Purple",
        "vendor": "Amolen",
        "type": "PLA",
        "color": None,
        "density": 1.24,
        "diameter": 1.75,
        "spoolWeight": 190,
        "netFilamentWeight": 1000,
        "parentId": "6a6eca19a3360ac295bfafca",
    },
    "spool": {
        "_id": "6a6eca1aa3360ac295bfb007",
        "instanceId": "970fdbcd56",
        "label": "177",
        "totalWeight": 359.37,
        "retired": False,
        "locationId": "6a6eca1aa3360ac295bfafec",
    },
}


# -- auth ---------------------------------------------------------------


def test_bearer_auth_applied_when_api_key_set():
    session = FakeSession(response=FakeResponse(200, FILAMENTS_LIST))
    client = FilamentDBClient(
        "http://fdb.local:3000", api_key="secret123", session=session
    )
    client.list_filaments()
    assert session.last_headers["Authorization"] == "Bearer secret123"


def test_no_authorization_header_when_no_api_key():
    session = FakeSession(response=FakeResponse(200, FILAMENTS_LIST))
    client = FilamentDBClient("http://fdb.local:3000", api_key=None, session=session)
    client.list_filaments()
    assert "Authorization" not in session.last_headers


def test_401_raises_authentication_failed():
    session = FakeSession(response=FakeResponse(401))
    client = FilamentDBClient("http://fdb.local:3000", session=session)
    with pytest.raises(AuthenticationFailed):
        client.list_filaments()


# -- network failure modes ------------------------------------------------


def test_timeout_raises_request_timed_out():
    session = FakeSession(exception=requests.exceptions.Timeout())
    client = FilamentDBClient("http://fdb.local:3000", session=session)
    with pytest.raises(RequestTimedOut):
        client.list_filaments()


def test_connection_refused_raises_connection_failed():
    session = FakeSession(exception=requests.exceptions.ConnectionError())
    client = FilamentDBClient("http://fdb.local:3000", session=session)
    with pytest.raises(ConnectionFailed):
        client.list_filaments()


def test_malformed_json_raises_invalid_response():
    session = FakeSession(response=FakeResponse(200, raw_body="not json{{{"))
    client = FilamentDBClient("http://fdb.local:3000", session=session)
    with pytest.raises(InvalidResponse):
        client.list_filaments()


def test_non_401_error_status_raises_invalid_response():
    session = FakeSession(response=FakeResponse(500, {"error": "boom"}))
    client = FilamentDBClient("http://fdb.local:3000", session=session)
    with pytest.raises(InvalidResponse):
        client.list_filaments()


def test_unexpected_json_shape_raises_invalid_response():
    session = FakeSession(response=FakeResponse(200, {"not": "a list"}))
    client = FilamentDBClient("http://fdb.local:3000", session=session)
    with pytest.raises(InvalidResponse):
        client.list_filaments()


# -- timeout is configurable and actually passed through ------------------


def test_configured_timeout_is_passed_to_requests():
    session = FakeSession(response=FakeResponse(200, FILAMENTS_LIST))
    client = FilamentDBClient("http://fdb.local:3000", timeout=17, session=session)
    client.list_filaments()
    assert session.last_timeout == 17


# -- list_filaments() parses into models -----------------------------------


def test_list_filaments_parses_embedded_spools():
    session = FakeSession(response=FakeResponse(200, FILAMENTS_LIST))
    client = FilamentDBClient("http://fdb.local:3000", session=session)
    filaments = client.list_filaments()
    assert len(filaments) == 1
    f = filaments[0]
    assert f.id == "6a6eca19a3360ac295bfafd9"
    assert f.density == 1.24
    assert f.spool_weight == 190
    assert f.net_filament_weight == 1000
    assert len(f.spools) == 1
    assert f.spools[0].label == "177"
    assert f.spools[0].instance_id == "970fdbcd56"
    assert f.spools[0].total_weight == 359.37


def test_list_filaments_url_and_path():
    session = FakeSession(response=FakeResponse(200, FILAMENTS_LIST))
    client = FilamentDBClient("http://fdb.local:3000/", session=session)
    client.list_filaments()
    assert session.last_url == "http://fdb.local:3000/api/filaments"


# -- get_spool() -- the read for an assigned spool (C-3) -------------------


def test_get_spool_returns_inheritance_resolved_filament_and_spool():
    session = FakeSession(response=FakeResponse(200, SPOOL_DETAIL))
    client = FilamentDBClient("http://fdb.local:3000", session=session)
    detail = client.get_spool("6a6eca1aa3360ac295bfb007")
    assert detail.filament.diameter == 1.75  # absent from the list projection
    assert detail.filament.density == 1.24
    assert detail.spool.label == "177"
    assert session.last_url == (
        "http://fdb.local:3000/api/spools/6a6eca1aa3360ac295bfb007"
    )


def test_get_spool_missing_filament_or_spool_key_is_invalid_response():
    session = FakeSession(response=FakeResponse(200, {"filament": {}}))
    client = FilamentDBClient("http://fdb.local:3000", session=session)
    with pytest.raises(InvalidResponse):
        client.get_spool("whatever")


# -- get_locations() -- resolves locationId -> name (C-3b) -----------------


def test_get_locations_parses_id_and_name():
    session = FakeSession(response=FakeResponse(200, LOCATIONS_LIST))
    client = FilamentDBClient("http://fdb.local:3000", session=session)
    locations = client.get_locations()
    assert len(locations) == 2
    assert locations[0].id == "6a385c81a66ab307b7f9b5d3"
    assert locations[0].name == "Bin 1 - PLA"
    assert session.last_url == "http://fdb.local:3000/api/locations"


def test_get_locations_unexpected_json_shape_raises_invalid_response():
    session = FakeSession(response=FakeResponse(200, {"not": "a list"}))
    client = FilamentDBClient("http://fdb.local:3000", session=session)
    with pytest.raises(InvalidResponse):
        client.get_locations()


# -- get_version() -- the Test Connection probe (FR-1) ----------------------


def test_get_version_reads_openapi_info_version():
    session = FakeSession(
        response=FakeResponse(
            200, {"openapi": "3.0.3", "info": {"title": "x", "version": "1.68.1"}}
        )
    )
    client = FilamentDBClient("http://fdb.local:3000", session=session)
    assert client.get_version() == "1.68.1"
    assert session.last_url == "http://fdb.local:3000/api/openapi"


def test_get_version_missing_info_is_invalid_response():
    session = FakeSession(response=FakeResponse(200, {"openapi": "3.0.3"}))
    client = FilamentDBClient("http://fdb.local:3000", session=session)
    with pytest.raises(InvalidResponse):
        client.get_version()
