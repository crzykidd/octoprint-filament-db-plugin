# octoprint-filament-db-plugin

An [OctoPrint](https://octoprint.org/) plugin that tracks filament usage directly in
[Filament DB](https://github.com/hyiger/filament-db).

Assign a Filament DB spool to each of your printer's tools, and the plugin meters what is actually
extruded during the print. When the job ends — finished, failed, or cancelled — it writes a single
print-history record back to Filament DB with the job name and the grams consumed per spool.

---

> ## ⚠️ Unreleased — early development
>
> **This project is in early development and has not been released.** There is currently **no
> installable plugin** — the repository contains design documentation only. Nothing here is ready
> to point at a Filament DB instance you care about.
>
> There is no version, no release, and no entry in the OctoPrint Plugin Repository yet. Please
> don't file usage issues; design feedback is very welcome.

> ## ⚠️ Requires OctoPrint 2.0 — will not work on 1.x
>
> This plugin targets **OctoPrint 2.0 only** (2.0.0rc4 and later). It **will not install or run on
> OctoPrint 1.11 or any earlier 1.x release**, and there are no plans to backport it.
>
> OctoPrint 2.0 removed a large amount of long-deprecated API surface. The plugin is written
> against the post-2.0 APIs — explicit access permissions, CSRF-protected blueprints, snake_case
> access methods — and supporting 1.x would mean a compatibility shim at every one of those points.
> See the [OctoPrint 2.0 migration guide](https://docs.octoprint.org/en/dev/plugins/migration_2_0_0.html)
> for background.

---

## What it will do

- **Pick a spool per tool** from your Filament DB library, with search and filtering. Multi-tool
  and MMU setups get one slot per tool.
- **Check before printing** — warn when no spool is assigned, when the loaded material doesn't
  match what the G-code was sliced for, or when the spool doesn't hold enough filament.
- **Meter what is actually extruded**, by counting E-moves as they are sent to the printer. This is
  slicer-independent, and it means a print cancelled at 40% records roughly 40% of the filament —
  not nothing, and not the full slicer estimate.
- **Write one print-history record per job** back to Filament DB, with per-spool grams. Filament DB
  debits the spools and keeps the audit trail.
- **Show you exactly what it did.** Every write attempt — successful or not — is recorded in a
  history view with its outcome, the failure reason if any, and retry and discard actions. A
  tracker that fails silently is worse than no tracker, so this one doesn't.

It talks to Filament DB **natively**. It does not require, use, or sync through
[Spoolman](https://github.com/Donkie/Spoolman).

## Requirements

| | |
|---|---|
| OctoPrint | **2.0.0rc4 or later** (1.x is not supported) |
| Python | 3.9+ |
| Filament DB | a reachable instance; an API key if yours sets `FILAMENTDB_API_KEY` |

## Documentation

- **[`docs/prd.md`](docs/prd.md)** — the v1 design: requirements, constraints, and architecture.
- **[`docs/decisions.md`](docs/decisions.md)** — why things are the way they are.

## Status

Design complete, implementation not started. See the PRD for the v1 scope and the open questions
still to be resolved against a live OctoPrint 2.0 instance.

## Prior art

[`mdziekon/octoprint-spoolman`](https://github.com/mdziekon/octoprint-spoolman) solves the
equivalent problem for [Spoolman](https://github.com/Donkie/Spoolman) and was studied as prior art
while designing this plugin — its UX shape (a sidebar of loaded spools, a tab with a picker,
pre-print checks) is a good one and informed the design here.

**No code is reused from it.** This is a fresh implementation. Filament DB's data model and write
path differ fundamentally from Spoolman's — grams versus millimetres, a gross weight model, spools
embedded on filaments, and a single transactional print-history write that debits weight itself —
so there is little that would transfer even if it were desirable. Where behaviour is deliberately
similar it is described in the [PRD](docs/prd.md) and arrived at independently.

## License

[GNU Affero General Public License v3.0](LICENSE) — the same license OctoPrint itself uses.

Copyright (C) 2026 crzykidd
