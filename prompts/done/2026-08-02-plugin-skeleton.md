---
name: 2026-08-02-plugin-skeleton
status: completed        # pending | completed | failed
created: 2026-08-02
model: sonnet            # coding — the design is settled, this is execution
completed: 2026-08-02
result: >
  Plugin skeleton built and verified end-to-end in the dev container: installs editable,
  appears enabled in Plugin Manager, sidebar and settings panels render and bind cleanly
  (a real Knockout binding bug was caught and fixed via a Playwright-driven browser check),
  clean startup log, 6/6 pytest tests pass, octoscanner reports zero findings.
---

# Task: Build the plugin skeleton — first code in the repo

Create the installable OctoPrint 2.0 plugin package: packaging, the mixin class, settings,
permissions, and empty sidebar/settings templates. **No features.** The goal is a plugin that
installs cleanly, loads without warnings, and renders its own (empty) panels — the harness
everything else lands into.

This is step 1 of the UI-first implementation order in `prompts/startnewsession.md`. Step 2 (the
live raw-millimetre readout) is a separate prompt and is **out of scope here**.

## Before you start

Read, in this order:

1. **`CLAUDE.md`** — operational rules, the task→file routing table, and the code-shape rules.
2. **`docs/prd.md`** §Architecture, §Codebase design constraints (N-1…N-10),
   §OctoPrint UI framework, and FR-1 / FR-10.
3. **`docs/decisions.md`** — skim; do not re-derive anything already settled there.

Key constraints that bite in this task specifically:

- **OctoPrint 2.0 only** (C-6). `pyproject.toml`, **not** `setup.py`. Blueprints are CSRF-protected
  by default. `admin_permission` no longer exists — declare explicit permissions. Access APIs are
  snake_case. `get_plugin_data_folder()` comes from `OctoPrintPlugin`.
- **`plugin.py` is wiring only** (N-5). The moment a method makes a decision, it belongs in a module
  the tests can reach without booting OctoPrint.
- **500-line hard cap per module** (N-1); OWNS / DOES NOT OWN docstring on every module (N-2).
- **No hardcoded colours** in CSS. Use Bootstrap 2 / OctoPrint classes so theme plugins restyle us
  (PRD §OctoPrint UI framework).
- **All code original.** Prior art may be read and cited, never copied — not `octoprint-spoolman`,
  not OctoPrint's vendored `gcodeInterpreter`. AGPLv3 header on every new source file.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files this plan needs
to modify. If any have uncommitted changes, list them and ask before touching them. Surface
unrelated dirty files once as awareness; don't block. This prompt file is exempt.

You should be on the **`dev`** branch. `main` is protected and rejects direct pushes.

## What to do

### 1. Packaging

- `pyproject.toml` with build isolation. Plugin identifier **`filamentdb`**, package
  **`octoprint_filamentdb`**, licence **AGPL-3.0-or-later** with the matching classifier.
  `requires-python = ">=3.9"`. Declare `OctoPrint>=2.0.0rc4` and `requests`.
- Standard OctoPrint plugin metadata (`__plugin_name__`, `__plugin_version__`,
  `__plugin_identifier__`, `__plugin_description__`, `__plugin_pythoncompat__ = ">=3.9,<4"`,
  `__plugin_implementation__`, `__plugin_hooks__`).
- **Version `0.0.1`, stored bare** — no `v` prefix anywhere in code (`release-prep-and-cut` rule in
  `CLAUDE.md`). One source of truth for the version; reference it from `pyproject.toml`.

### 2. `octoprint_filamentdb/settings_keys.py`

Every settings key as a constant — **no string literals at call sites anywhere** (N-6). Cover the
v1 settings named in the PRD, including ones not yet used:

`filamentDbUrl`, `filamentDbApiKey`, `requestTimeout`, `cacheTtlSeconds`,
`toolDisplayOffset` (default `1`), `onMissingDensity` (`estimate`|`block`, default `estimate`),
`fallbackDensity` (default `1.24`), `materialDensities` (the per-type map from FR-6),
`showInstanceIdInSidebar`, `showLotNumberInSidebar`, `debugPanelEnabled` (default `false`),
`preflightDialogMode` (`always`|`problems`|`never`, default `always`),
`pushSlotAssignment` (default `false`, **disabled in the UI — FR-11 seam**),
`filamentDbPrinterId`, `toolSlotMap`, `selectedSpools`.

### 3. `octoprint_filamentdb/plugin.py`

The mixin class — **wiring only**. Mixins: `SettingsPlugin`, `AssetPlugin`, `TemplatePlugin`,
`StartupPlugin`, `EventHandlerPlugin` (registered, handler empty for now).

- `get_settings_defaults()` from `settings_keys.py`.
- `get_settings_restricted_paths()` must include the **API key** so it never reaches a non-admin or
  a support bundle (FR-1).
- `get_template_configs()` for `sidebar` and `settings`, with `custom_bindings=True` and an `icon`.
- `get_assets()` for js + css.
- `on_after_startup()` — log the version and that the plugin loaded. **No network calls.**

### 4. Permissions (FR-10)

`octoprint.access.permissions` hook declaring:

- `FILAMENTDB_SELECT` — view spools, assign them, view the journal, retry a failed write.
  Default: Operator.
- `FILAMENTDB_ADMIN` — change settings, discard journal entries. Default: Admin.

### 5. Templates + assets

- `templates/filamentdb_sidebar.jinja2` — **content only, no wrapper**; OctoPrint wraps it in an
  `accordion-group`. A placeholder line is fine ("No spools loaded").
- `templates/filamentdb_settings.jinja2` — Filament DB URL, API key (password field), request
  timeout. Bootstrap 2 form markup, bound to the settings viewmodel.
- `static/js/filamentdb.js` — one Knockout viewmodel registered against `settingsViewModel` and
  `printerStateViewModel`, bound to `#sidebar_plugin_filamentdb` and `#settings_plugin_filamentdb`.
  It may be nearly empty; it must bind without console errors.
- `static/css/filamentdb.css` — minimal, **no colour literals**.

### 6. Tests

- `tests/test_import_directions.py` — the N-3 enforcement test. Assert `metering/` and `client/`
  import nothing internal, and that `metering/` never imports `client/`. Those packages do not exist
  yet: create them with `__init__.py` and an OWNS/DOES NOT OWN docstring so the test is meaningful
  now and does not need revisiting later.
- `tests/test_settings_keys.py` — assert every key in `get_settings_defaults()` has a constant, and
  no duplicates.
- Tests mirror source paths 1:1 (N-7). Wire `pytest` config into `pyproject.toml`.

### 7. Install and verify in the dev container

The dev stack is already running (`docker compose -f docker-compose.dev.yml`), OctoPrint 2.0.0rc4,
single extruder, no third-party plugins. **Verify, do not assume:**

1. Uncomment the editable-install line in `Dockerfile.dev` (it is commented out pending
   `pyproject.toml` — that blocker is now gone), rebuild, and bring the stack up.
2. `docker exec octoprint-fdb-dev pip show OctoPrint-FilamentDB` (or the resolved dist name)
   confirms it is installed.
3. The plugin appears in **Settings → Plugin Manager**, enabled.
4. The **sidebar panel renders** and the **settings panel opens**.
5. `docker exec octoprint-fdb-dev sh -c 'grep -i "filamentdb" /octoprint/octoprint/logs/octoprint.log'`
   shows the startup line and **no errors or deprecation warnings**.
6. Browser console shows **no Knockout binding errors**.
7. Run `pytest`.
8. Run [`octoscanner`](https://github.com/jacopotediosi/octoscanner) against the package and report
   the output. If it flags anything, fix it or explain why it is a false positive.

**If any verification step fails, fix it — do not report success with a caveat.** If something is
genuinely blocked, stop and report what and why.

## Conventions to honor

- Conventional-commit prefix; this is `feat:`. No `Co-authored-by:` trailers.
- Docs ship with the code: if you add or change a module, update the **task→file routing table in
  `CLAUDE.md`** in the same change (N-8).
- Do not touch `docs/prd.md` requirements. If you find the PRD is *wrong*, stop and report it rather
  than silently diverging — that has happened several times on this project and the correction
  belongs in the decision log.
- Nothing goes in `private_data/` expecting to be committed; it is gitignored in full.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure). Create the
   subdir if needed.
3. Record any non-obvious decisions in `docs/decisions.md`.
4. **You are a spawned agent: do NOT commit.** Prepare the working tree, then report back:
   - the file list
   - a proposed one-line commit message (`feat:` prefix)
   - the verification results from step 7 above, including the `octoscanner` output
   - anything you had to decide that the PRD did not cover

   The orchestrating session surfaces the `y/n` to the user. Never `git add -A`, never push.
