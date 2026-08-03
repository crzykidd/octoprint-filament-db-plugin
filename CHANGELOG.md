# Changelog

All notable changes to this project are recorded here. This file is the **single source of truth
for release notes** — the `dev → main` PR description and the GitHub release body reuse the
relevant section verbatim, per the `release-prep-and-cut` standard (see [`standards.md`](standards.md)).

Versions are stored **bare** (no `v` prefix) in `octoprint_filamentdb/_version.py`. The `v` appears
in exactly one place: the git tag and the matching GitHub release name.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

**Nothing has been released yet.** The plugin installs and runs, but does not yet write anything
back to Filament DB, which is its entire purpose — so there is no version worth cutting. The first
release will be the one that closes the loop (FR-7, `POST /api/print-history`).

### Added

- **Plugin skeleton** — installable on OctoPrint 2.0 (`pyproject.toml`, not `setup.py`), with
  settings, two explicit permissions (`FILAMENTDB_SELECT` / `FILAMENTDB_ADMIN`), and sidebar +
  settings panels.
- **Live extrusion metering** — a per-tool odometer fed by `octoprint.comm.protocol.gcode.sent`,
  showing running millimetres in the sidebar. Handles `G0`–`G3` (arcs carry `E` too), `M82`/`M83`,
  `G90`/`G91`, `G92` resets, `T<n>` tool changes, and retraction netting.
  Measured **exact** against a real PrusaSlicer file: 2667.31 mm, matching an independent
  parse of the same file to the hundredth of a millimetre.
- **Partial usage on cancellation** — cancelling a print retains the metered total rather than
  resetting it. This is the behaviour that distinguishes the plugin from committing only on
  completion.
- **Filament DB connection** — REST client with optional bearer auth, a TTL cache, a manual
  refresh, and a Test Connection probe reporting the Filament DB version.
- **Spool picker** — assign a Filament DB spool per tool. One search box ranked across six tiers
  (exact label → exact tag id → exact `_id` → label prefix → tag-id prefix → fuzzy), each result
  showing why it matched. Filters for material type, location and retired spools.
- **Computed remaining weight** — Filament DB stores *gross* on the spool with tare and nominal on
  the filament, so remaining is derived (`gross − tare`). The sidebar shows
  `169.4 g / 1000 g`; the picker shows `169.4 / 359.4 g` under a `Remaining / Scale` header, the
  second figure being what a scale would read.
- **Graceful degradation for incomplete inventory data** — a spool with no tare renders
  `1042 g gross · tare not set` rather than presenting gross as if it were net (which would
  overstate remaining filament by the weight of the reel); no nominal drops the denominator;
  an unweighed spool reads `not weighed`; an overfilled reel shows its true figure with the
  progress bar clamped.
- **Assignment-time density warning** — flags a filament with no density when the spool is loaded,
  since usage on it will have to be estimated.
- **Spool-precise deep links** — `Open in Filament DB` jumps to the filament page with that spool
  highlighted (`?spool=<id>`), not just the parent record.

### Fixed

- Filament DB's tag id was effectively unsearchable — it matched only on a full 10-character exact
  hit, so typing a prefix returned nothing.
- The location filter listed raw database GUIDs instead of names. This also fixed a silent second
  bug: location text search had never matched anything, because the field it searched was never
  populated.
- The picker's "Match" column was empty on every row when not searching, which read as broken.
- Long filament names wrapped to six lines in the picker.

### Known limitations

- **Nothing is written back to Filament DB yet.** The metering and assignment are real; the commit
  path is not built.
- **A resent G-code command is counted twice.** OctoPrint re-fires the `sent` phase for resends, so
  the odometer double-counts them. Measured at +0.79 mm on 2667 mm (0.03%) with a healthy serial
  link; worse on a flaky one.
- **Tested only against a virtual printer**, single-extruder, with no other plugins installed.
  MMU and plugin coexistence are later phases.
