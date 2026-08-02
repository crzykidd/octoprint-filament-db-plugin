# Copyright (C) 2026 crzykidd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import-direction guard (PRD rule N-3).

OWNS: asserting that ``octoprint_filamentdb.client`` and
    ``octoprint_filamentdb.metering`` import nothing internal, and that
    ``metering`` never imports ``client``. This is what turns N-3 from a
    guideline into a guarantee: a metering bug genuinely cannot require
    reading the API client, because this test would fail if it could.
DOES NOT OWN: any other structural rule (module size, docstrings, ...).
"""

import ast
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "octoprint_filamentdb"
INTERNAL_PREFIX = "octoprint_filamentdb"


def _py_files(subpackage):
    return sorted((PACKAGE_ROOT / subpackage).rglob("*.py"))


def _external_reach_violations(py_file, subpackage):
    """Imports in ``py_file`` (which lives under ``subpackage``) that reach
    outside ``octoprint_filamentdb.<subpackage>`` -- i.e. any other internal
    module. Stdlib and third-party imports are always allowed and never
    appear here.
    """
    tree = ast.parse(py_file.read_text(), filename=str(py_file))
    own_prefix = f"{INTERNAL_PREFIX}.{subpackage}"
    violations = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name == INTERNAL_PREFIX or name.startswith(f"{INTERNAL_PREFIX}."):
                    if not (name == own_prefix or name.startswith(f"{own_prefix}.")):
                        violations.append(name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level >= 2:
                # "from .. import x" (or deeper) from inside
                # octoprint_filamentdb/<subpackage>/ leaves the subpackage.
                violations.append("." * node.level + (node.module or ""))
            elif node.level == 0 and node.module:
                name = node.module
                if name == INTERNAL_PREFIX or name.startswith(f"{INTERNAL_PREFIX}."):
                    if not (name == own_prefix or name.startswith(f"{own_prefix}.")):
                        violations.append(name)
            # level == 1 ("from . import x") stays inside the subpackage --
            # allowed.

    return violations


def test_client_imports_nothing_internal():
    py_files = _py_files("client")
    assert py_files, "expected at least client/__init__.py to exist"
    for py_file in py_files:
        violations = _external_reach_violations(py_file, "client")
        assert not violations, f"{py_file} imports internal modules: {violations}"


def test_metering_imports_nothing_internal():
    py_files = _py_files("metering")
    assert py_files, "expected at least metering/__init__.py to exist"
    for py_file in py_files:
        violations = _external_reach_violations(py_file, "metering")
        assert not violations, f"{py_file} imports internal modules: {violations}"


def test_metering_never_imports_client():
    # Subsumed by test_metering_imports_nothing_internal() today (client is
    # simply another internal package), but asserted explicitly because
    # this is the one direction the PRD calls out by name (N-3) and it
    # should keep failing loudly even if the "nothing internal" rule is
    # ever relaxed for metering/ in some other direction.
    for py_file in _py_files("metering"):
        violations = _external_reach_violations(py_file, "metering")
        client_violations = [v for v in violations if "client" in v]
        assert not client_violations, (
            f"{py_file} must never import client/ (N-3): {client_violations}"
        )
