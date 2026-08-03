# Copyright (C) 2026 crzykidd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Runs the Node-executed coverage for static/js/filamentdb-search.js --
the picker's actual runtime search ranking (FR-2) -- as part of the normal
`pytest` run.

OWNS: shelling out to `node` against tests/js/filamentdb_search_test.js and
    asserting it exits 0. This is the only coverage for spool search now
    that octoprint_filamentdb/search.py (a shadow module with pytest
    coverage but no runtime role) has been deleted -- see
    docs/decisions.md. If `node` is missing, this test FAILS, it never
    skips: a silent skip would leave the ranking that actually runs in the
    picker exactly as untested as before this file existed. Node is a
    dev-image dependency added to Dockerfile.dev for this reason.
DOES NOT OWN: the ranking algorithm itself
    (static/js/filamentdb-search.js) or the test cases
    (tests/js/filamentdb_search_test.js).
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
JS_TEST = REPO_ROOT / "tests" / "js" / "filamentdb_search_test.js"


def test_filamentdb_search_js_ranking():
    node = shutil.which("node")
    if node is None:
        pytest.fail(
            "node is not on PATH -- the JS search-ranking test cannot "
            "run. This must fail loudly rather than skip: it is the only "
            "coverage for the ranking code that actually runs in the "
            "picker. Dockerfile.dev installs nodejs for exactly this."
        )

    result = subprocess.run(
        [node, str(JS_TEST)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        "filamentdb-search.js ranking test failed:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
