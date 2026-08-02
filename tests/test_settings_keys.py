# Copyright (C) 2026 crzykidd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Settings-key completeness guard (PRD rule N-6).

OWNS: asserting every key returned by ``get_settings_defaults()`` has a
    matching constant in ``settings_keys.ALL_KEYS``, and that those
    constants contain no duplicates.
DOES NOT OWN: the settings values or defaults themselves, or how they are
    consumed.
"""

from octoprint_filamentdb import settings_keys


def test_every_default_key_has_a_constant():
    defaults = settings_keys.get_settings_defaults()
    assert set(defaults.keys()) == set(settings_keys.ALL_KEYS)


def test_all_keys_has_no_duplicates():
    assert len(settings_keys.ALL_KEYS) == len(set(settings_keys.ALL_KEYS))


def test_all_keys_are_non_empty_strings():
    for key in settings_keys.ALL_KEYS:
        assert isinstance(key, str) and key
