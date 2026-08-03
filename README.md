# octoprint-filament-db-plugin

[![CI](https://github.com/crzykidd/octoprint-filament-db-plugin/actions/workflows/ci.yml/badge.svg)](https://github.com/crzykidd/octoprint-filament-db-plugin/actions/workflows/ci.yml)
[![CodeQL](https://github.com/crzykidd/octoprint-filament-db-plugin/actions/workflows/codeql.yml/badge.svg)](https://github.com/crzykidd/octoprint-filament-db-plugin/actions/workflows/codeql.yml)

An [OctoPrint](https://octoprint.org/) plugin that tracks filament usage directly in
[Filament DB](https://github.com/hyiger/filament-db).

Assign a Filament DB spool to each of your printer's tools, and the plugin meters what is actually
extruded during the print. When the job ends — finished, failed, or cancelled — it writes a single
print-history record back to Filament DB with the job name and the grams consumed per spool.

---

> ## ⚠️ Unreleased — early development
>
> **This project is in early development and has not been released.** The plugin now installs on
> OctoPrint 2.0, meters extrusion live, and assigns Filament DB spools to tools — but it **does not
> yet write anything back to Filament DB**, which is its entire purpose. Do not point it at a
> Filament DB instance you care about.
>
> There is no release and no entry in the OctoPrint Plugin Repository yet. See
> [`CHANGELOG.md`](CHANGELOG.md) for what has landed and what is still missing. Please don't file
> usage issues; design feedback is very welcome.

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

## Development environment

A Docker-based OctoPrint 2.0 instance with a virtual printer, so you can develop and test
without tying up a real printer.

### Why we build our own image

**There is no official Docker image that ships OctoPrint 2.0.** Verified 2026-08-01: the
`octoprint/octoprint` tags `latest` and `edge` both pin `octoprint_ref=1.11.8`, and `canary`
tracks the `maintenance` branch — still the 1.x line. The 2.0 release candidates *are* published
on PyPI, so [`Dockerfile.dev`](Dockerfile.dev) layers the RC on top of the official image and
asserts at build time that the upgrade actually took.

### Start it

```bash
git clone https://github.com/crzykidd/octoprint-filament-db-plugin.git
cd octoprint-filament-db-plugin
mkdir -p private_data/octoprint

docker compose -f docker-compose.dev.yml up -d --build
```

OctoPrint comes up on **http://localhost:5000**. Override with `OCTOPRINT_PORT` in a `.env` file
(gitignored) if 5000 is taken.

### First-run setup

1. Walk the OctoPrint setup wizard and create your user account.
2. **Connect to the `VIRTUAL` port** — the virtual printer is enabled on first start
   (`plugins.virtual_printer` in `private_data/octoprint/octoprint/config.yaml`), configured as
   **single-extruder** for phase 1.
3. In the plugin's settings, point **Filament DB URL** at your instance and add an API key if it
   sets `FILAMENTDB_API_KEY`.
4. **Install no other plugins.** Phase 1 is deliberately a clean instance — a third-party plugin
   touching the G-code stream is exactly the variable phase 4 exists to introduce.

For phase 3, switch the printer profile to *Virtual MMU (5 tools, shared nozzle)* and set
`plugins.virtual_printer.numExtruders: 5`. Getting the profile right matters more than it looks:
OctoPrint does **not** detect an MMU's tool count, and neither does the PrusaMMU plugin — see FR-3
for why getting it wrong silently mis-attributes filament.

To re-seed steps 2–3 from scratch, delete `private_data/octoprint/` and bring the stack back up.

### Never let the dev container self-update

OctoPrint's Software Update plugin treats **2.0.0rc4 as a prerelease and 1.11.8 as the latest
stable**, so it offers an "update" that is really a **downgrade** — straight off the version this
plugin targets. Accepting it silently breaks the dev environment.

The bundled updater is therefore **disabled** in the dev container
(`plugins._disabled: [softwareupdate]`), with `prerelease_channel: rc/devel` set as a second line
of defence in case it is ever switched back on. **Leave it disabled.**

The image is the single source of truth for the OctoPrint version, and it should stay that way:
an in-container `pip install` writes to `site-packages`, which is *not* in the mounted volume, so
it silently vanishes the next time the container is recreated. To move to a newer RC, bump the
version and rebuild:

```bash
# docker-compose.dev.yml → services.octoprint.build.args.OCTOPRINT_VERSION
docker compose -f docker-compose.dev.yml up -d --build
```

The build asserts the installed version starts with `2.`, so a bad bump fails loudly instead of
leaving you on 1.x.

### `private_data/` — local only

Everything mutable lives in `private_data/`, which is **gitignored in full**: the OctoPrint volume
(config, uploads, logs, the plugin's journal DB), scratch G-code, keys, and notes. Nothing in there
is needed to build or run from a fresh clone — the container recreates it on first start.

Committed test data belongs in `tests/fixtures/` instead. That includes the real MMU3 serial
capture at `tests/fixtures/serial/`, which is worth reading before touching the metering code.

### Testing workflow

**Add one variable at a time.** Each phase below introduces exactly one new source of complexity, so
when something breaks it is obvious what caused it. Do not skip ahead — most of the hard-won findings
in [`docs/decisions.md`](docs/decisions.md) came from later phases, and debugging them against an
unproven core would have been miserable.

| Phase | Setup | Proves |
|---|---|---|
| **1. Core loop** ← *current* | Docker, OctoPrint 2.0, **no third-party plugins**, **single-extruder** virtual printer | assign a spool → print → meter → convert → commit → journal. The whole v1 happy path with one tool and one spool. |
| **2. Real hardware, single tool** | a Prusa printer, still no other plugins | real timing, real serial behaviour, real cancel/failure — things the virtual printer cannot fake |
| **3. Multi-tool / MMU** | the `mmu5` profile, then the real Core One + MMU | per-tool attribution, tool changes, FR-3's slot-count union, runout and jam handling |
| **4. Plugin coexistence** | add `Octoprint-PrusaMMU` | tool remapping, `Tx` interception, the overlapping "which spool is in slot N" question (PRD §Known plugin interactions) |

Most of the documented risk — MMU tool attribution, command remapping, `echo:MMU2:` parsing — lives
in phases 3 and 4. **The phase-1 core loop is genuinely simple**: one tool, one spool, one
accumulator. Getting it solid first keeps that complexity off the critical path, and single-extruder
is the majority case for real users anyway.

The dev container ships configured for phase 1. An `mmu5` printer profile
(*Virtual MMU, 5 tools, shared nozzle*) is already on disk for phase 3 — switch to it in OctoPrint's
printer-profile settings when you get there.

Beyond the phases, testing happens in two places, and it is worth being explicit about which one
proves what.

**1. Docker + virtual printer — logic.** Everything that is pure computation is tested here and in
unit tests: the extrusion odometer, mm→gram conversion, slicer-metadata parsing, commit-payload
construction, the write journal and its retry states. This covers most of the plugin and needs no
hardware.

**2. A real Prusa printer — behaviour the virtual printer cannot fake.** Anything involving how a
printer *actually behaves* is validated against real hardware: firmware-initiated pauses, MMU
tool changes, runout and jam recovery, commands another plugin suppresses before they reach the
odometer, and the timing of everything above.

#### Primary test target: the Prusa ecosystem

This is the maintainer's hardware, so it is where real-hardware verification happens:

- **Printer:** Prusa MK-series with **MMU3**
- **Slicer:** PrusaSlicer (including the `hyiger` Filament Edition fork)
- **Reference capture:** [`tests/fixtures/serial/`](tests/fixtures/serial/) holds a real MMU3
  runout/jam serial log. It is the source of truth for filament-change detection and has already
  overturned two design assumptions — prefer it over invented test data.

#### Other printers and slicers: untested, not unsupported

**The core logic is deliberately printer-agnostic.** Extrusion is metered by counting E-moves as
they are sent, which is a property of G-code rather than of any vendor. Marlin, Klipper, RepRap and
others should work identically. The same goes for the Filament DB side, which knows nothing about
printers at all.

What is genuinely Prusa- or slicer-specific, and what happens elsewhere:

| Area | Prusa / PrusaSlicer | Elsewhere |
|---|---|---|
| Extrusion metering | tested | should be identical — it is just G-code |
| Material-type + sufficiency checks | tested (PrusaSlicer config block) | works for OrcaSlicer and Bambu Studio (same block); **Cura emits no material type**, so that one check is skipped and says so |
| Multi-tool / MMU | tested (MMU3) | tool-change logic is generic `T<n>`; other multi-tool systems untested |
| `echo:MMU2:` change detection | tested | Prusa-only — **which is why the primary detection signal is a vendor-neutral stall watchdog, not message parsing** |
| Firmware-initiated pause | tested | varies by firmware; the stall watchdog is the fallback that needs no vendor knowledge |

If you run something else, reports are welcome — especially a serial capture of a filament change,
which is the single most useful thing to send. Non-Prusa hardware will not block a release, but it
also will not be claimed as tested.

**This holds until the advanced G-code work.** Volumetric extrusion (`M200`), firmware retraction
(`G10`/`G11`), and extruder-multiplier compensation (`M221`) are explicit v1 non-goals. Those are
where firmware differences start to matter for real, and each will need its own verification per
platform rather than an assumption that Prusa behaviour generalises.

### Useful commands

```bash
docker compose -f docker-compose.dev.yml logs -f octoprint   # follow logs
docker compose -f docker-compose.dev.yml restart octoprint   # pick up Python changes
docker compose -f docker-compose.dev.yml up -d --build       # rebuild after an RC bump
docker compose -f docker-compose.dev.yml down                # stop (keeps private_data/)
```

Static JS/CSS changes need only a browser reload. Python changes need a container restart, since
the plugin is installed editable.

## Documentation

- **[`docs/prd.md`](docs/prd.md)** — the v1 design: requirements, constraints, and architecture.
- **[`docs/decisions.md`](docs/decisions.md)** — why things are the way they are.

## Status

**Pre-alpha, phase 1.** Design is complete and all open questions are resolved. Three
implementation steps have landed: the plugin skeleton, live extrusion metering, and the Filament DB
client with the spool picker.

Still to build: mm→gram conversion, slicer metadata parsing, pre-print checks, the durable write
journal, and the print-history commit that closes the loop.

[`CHANGELOG.md`](CHANGELOG.md) tracks what has landed and its known limitations.

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
