# Copyright (C) 2026 crzykidd
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Settings key constants for the ``plugins.filamentdb.*`` settings namespace.

OWNS: every settings key name as a constant (PRD rule N-6 -- no string
    literals at call sites anywhere), the enum-shaped values those keys may
    hold, the built-in defaults, and ``get_settings_defaults()`` itself.
DOES NOT OWN: how the values are used, validated, or displayed -- consumers
    (``plugin.py``, future ``api.py``, ``static/js/filamentdb.js``,
    ``templates/*.jinja2``) own that.
"""

# -- settings keys ------------------------------------------------------
#
# See docs/prd.md FR-1, FR-2, FR-3, FR-6, FR-9b, FR-10, FR-11 for what each
# of these covers. A few (PUSH_SLOT_ASSIGNMENT, FILAMENT_DB_PRINTER_ID,
# TOOL_SLOT_MAP) are P1 seams (FR-11, 1.1) declared now so the settings
# schema does not need a breaking change later; they are not driven by any
# v1 UI.

FILAMENT_DB_URL = "filamentDbUrl"
FILAMENT_DB_API_KEY = "filamentDbApiKey"
REQUEST_TIMEOUT = "requestTimeout"
CACHE_TTL_SECONDS = "cacheTtlSeconds"
TOOL_DISPLAY_OFFSET = "toolDisplayOffset"
ON_MISSING_DENSITY = "onMissingDensity"
FALLBACK_DENSITY = "fallbackDensity"
MATERIAL_DENSITIES = "materialDensities"
SHOW_INSTANCE_ID_IN_SIDEBAR = "showInstanceIdInSidebar"
SHOW_LOT_NUMBER_IN_SIDEBAR = "showLotNumberInSidebar"
DEBUG_PANEL_ENABLED = "debugPanelEnabled"
PREFLIGHT_DIALOG_MODE = "preflightDialogMode"
PUSH_SLOT_ASSIGNMENT = "pushSlotAssignment"
FILAMENT_DB_PRINTER_ID = "filamentDbPrinterId"
TOOL_SLOT_MAP = "toolSlotMap"
SELECTED_SPOOLS = "selectedSpools"

# Every settings-key constant above. tests/test_settings_keys.py checks this
# against get_settings_defaults() for completeness and duplicates (N-6) --
# kept as an explicit tuple rather than inferred by reflection, so both the
# test and this list stay unambiguous as more keys are added.
ALL_KEYS = (
    FILAMENT_DB_URL,
    FILAMENT_DB_API_KEY,
    REQUEST_TIMEOUT,
    CACHE_TTL_SECONDS,
    TOOL_DISPLAY_OFFSET,
    ON_MISSING_DENSITY,
    FALLBACK_DENSITY,
    MATERIAL_DENSITIES,
    SHOW_INSTANCE_ID_IN_SIDEBAR,
    SHOW_LOT_NUMBER_IN_SIDEBAR,
    DEBUG_PANEL_ENABLED,
    PREFLIGHT_DIALOG_MODE,
    PUSH_SLOT_ASSIGNMENT,
    FILAMENT_DB_PRINTER_ID,
    TOOL_SLOT_MAP,
    SELECTED_SPOOLS,
)

# -- enum-shaped setting values -------------------------------------------
#
# Kept beside the key they belong to so a call site never needs to spell the
# string literal either (N-6).

ON_MISSING_DENSITY_ESTIMATE = "estimate"
ON_MISSING_DENSITY_BLOCK = "block"

PREFLIGHT_DIALOG_MODE_ALWAYS = "always"
PREFLIGHT_DIALOG_MODE_PROBLEMS = "problems"
PREFLIGHT_DIALOG_MODE_NEVER = "never"

# -- default values --------------------------------------------------------

# Per-material-type density (g/cm^3), keyed on Filament DB's `type` field.
# Step 2 of FR-6's density fallback chain -- fires only when a filament has
# no density of its own AND no parent density to inherit (C-4): rare, but
# reachable, so it is a real default, not dead code.
DEFAULT_MATERIAL_DENSITIES = {
    "PLA": 1.24,
    "PETG": 1.27,
    "ABS": 1.04,
    "ASA": 1.07,
    "TPU": 1.21,
    "PA": 1.14,
    "PC": 1.20,
}

# Step 3 of the same fallback chain -- the global backstop when even the
# material-type default doesn't apply (unknown/missing `type`).
DEFAULT_FALLBACK_DENSITY = 1.24

# FR-2: "configurable TTL (default 5 min)".
DEFAULT_CACHE_TTL_SECONDS = 300

# Not specified numerically in the PRD; chosen as a conservative default for
# a LAN service -- long enough to tolerate a slow Filament DB instance,
# short enough that a genuinely unreachable one fails within one UI action
# rather than hanging it.
DEFAULT_REQUEST_TIMEOUT_SECONDS = 5

# FR-3 / tool-numbering: "Display defaults to 1-based... via a
# toolDisplayOffset setting (default 1)".
DEFAULT_TOOL_DISPLAY_OFFSET = 1


def get_settings_defaults():
    """Return the plugin's ``SettingsPlugin.get_settings_defaults()`` dict.

    The only place the defaults dict's shape is assembled -- ``plugin.py``
    just calls this and returns it.
    """
    return {
        FILAMENT_DB_URL: "",
        FILAMENT_DB_API_KEY: "",
        REQUEST_TIMEOUT: DEFAULT_REQUEST_TIMEOUT_SECONDS,
        CACHE_TTL_SECONDS: DEFAULT_CACHE_TTL_SECONDS,
        TOOL_DISPLAY_OFFSET: DEFAULT_TOOL_DISPLAY_OFFSET,
        ON_MISSING_DENSITY: ON_MISSING_DENSITY_ESTIMATE,
        FALLBACK_DENSITY: DEFAULT_FALLBACK_DENSITY,
        MATERIAL_DENSITIES: dict(DEFAULT_MATERIAL_DENSITIES),
        SHOW_INSTANCE_ID_IN_SIDEBAR: False,
        SHOW_LOT_NUMBER_IN_SIDEBAR: False,
        DEBUG_PANEL_ENABLED: False,
        PREFLIGHT_DIALOG_MODE: PREFLIGHT_DIALOG_MODE_ALWAYS,
        # Disabled in the UI in v1 -- FR-11 seam, not a working feature yet.
        PUSH_SLOT_ASSIGNMENT: False,
        FILAMENT_DB_PRINTER_ID: "",
        TOOL_SLOT_MAP: {},
        SELECTED_SPOOLS: {},
    }
