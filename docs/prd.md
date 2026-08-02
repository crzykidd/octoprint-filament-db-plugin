# Product Requirements Document: octoprint-filament-db-plugin

**Status:** v1 design — pre-alpha, no code yet
**Target:** OctoPrint 2.0 (2.0.0rc4+ / 2.0 GA)
**Date:** 2026-08-01

---

## Problem statement

[Filament DB](https://github.com/hyiger/filament-db) is the source-of-truth store for filament
inventory, material profiles, calibrations and print history. OctoPrint is where prints actually
run and where filament is actually consumed. Today nothing connects them: a user prints, filament
is spent, and Filament DB's spool weights drift from reality until someone weighs a spool and
edits it by hand.

A partial path exists — Spoolman's OctoPrint plugin decrements Spoolman, and a separate sync
service propagates those decrements into Filament DB as usage entries. That works, but it requires
running Spoolman purely as a relay for the print-side path, and it loses fidelity: the sync sees a
weight delta, not a print job.

## Solution

An OctoPrint plugin that talks to **Filament DB natively**. The user assigns a Filament DB spool
to each of the printer's tools; the plugin meters actual extrusion during the print and, when the
job reaches a terminal state, writes a single **print history record** back to Filament DB with the
job name and per-spool grams consumed — including partial usage on a cancelled or failed print.

No Spoolman. No bridge dependency on the write-back path.

## Users

Self-hosters running OctoPrint against a LAN Filament DB instance, on single-tool printers,
multi-tool printers, and MMU setups. Primary user is the author; the plugin is intended for the
public [OctoPrint Plugin Repository](https://plugins.octoprint.org/).

## Prior art

[`mdziekon/octoprint-spoolman`](https://github.com/mdziekon/octoprint-spoolman) is the closest
analogue and the model for the UX (sidebar of loaded spools, tab with a picker, pre-print checks).
Its metering approach — a vendored `gcodeInterpreter` driven as a coroutine off the gcode-sent
hook, committed on `PRINT_DONE` / `PRINT_FAILED` / `PRINT_CANCELLED` with a `lastPrintCancelled`
flag to dedupe the cancel→fail event pair — is sound, and the *event-handling shape* is arrived at
independently here for the same reasons (the cancel→fail duplicate is a real OctoPrint behaviour
anyone must handle).

**This is a clean-room implementation — no code is copied from it.** The licences are compatible
(both AGPLv3), so this is a deliberate engineering choice rather than a legal constraint:

- Everything below the metering layer would have to be rewritten anyway. Filament DB works in
  **grams** where Spoolman works in millimetres, uses a **gross** weight model, embeds spools on
  filaments, and exposes a single transactional print-history write that debits weight itself
  (C-1, C-2, C-3). Almost nothing transfers.
- The odometer specifically must be original. `octoprint-spoolman` vendors OctoPrint's own
  `gcodeInterpreter`, which is built for static file analysis; this plugin needs a live,
  per-tool, pause-aware accumulator that handles `G2`/`G3` arcs (FR-5) — the very gap raised in
  [filament-db#1039](https://github.com/hyiger/filament-db/issues/1039).

Referencing its behaviour to understand a problem is fine and is cited where done. Copying its
source is not.

---

## Naming & repo

| Thing | Value |
|---|---|
| GitHub repo | `crzykidd/octoprint-filament-db-plugin` |
| Python package | `octoprint_filamentdb` |
| Plugin identifier | `filamentdb` |
| Settings namespace | `plugins.filamentdb.*` |
| Plugin API prefix | `/api/plugin/filamentdb` |

The OctoPrint cookiecutter's `OctoPrint-<Name>` repo form is a **convention, not a requirement** —
the plugin repository lists plugins by their manifest, not their repo name, and the closest
reference plugin ([`mdziekon/octoprint-spoolman`](https://github.com/mdziekon/octoprint-spoolman))
is lowercase-hyphenated too.

The **package name and plugin identifier are not free** — `octoprint_filamentdb` must be a valid
importable Python package, and `filamentdb` is baked into the settings path
(`plugins.filamentdb.*`), the API prefix (`/api/plugin/filamentdb`), template and asset names, and
the plugin manifest. Those follow OctoPrint's rules regardless of what the repo is called.

---

## Critical design constraints

These are findings from reading the Filament DB and OctoPrint sources, not assumptions. They drive
the architecture and every one of them would be an expensive mistake to discover during
implementation.

### C-1: `POST /api/print-history` debits spool weight itself

`src/app/api/print-history/route.ts` does all of the following inside one MongoDB transaction, with
rollback on failure:

- decrements `spool.totalWeight` by `grams`, clamped at 0
- appends a `usageHistory` entry tagged `source: "job"` so analytics knows it is already
  represented by a print-history record
- creates the `PrintHistory` document

**Therefore the plugin calls `POST /api/print-history` and nothing else.** It must *never* also
call `POST /api/filaments/:id/spools/:spoolId/usage` for the same print — that would double-debit
every job. The per-spool usage endpoint is for manual weight corrections and is out of scope.

This also gives deletion semantics for free: `DELETE /api/print-history/:id` refunds the spool
weight atomically, so a user who mis-assigns a spool can undo the whole job from the Filament DB UI.

### C-2: Filament DB is a **gross** weight model, measured in grams

`spool.totalWeight` is gross (filament + reel). The filament-level `spoolWeight` (tare) and
`netFilamentWeight` are shared across all spools of that filament. The API accepts and returns
**grams** — there is no length-based endpoint. Spoolman's `PUT /spool/:id/use` takes millimetres
and does the conversion server-side; **Filament DB does not.** The plugin owns the mm→g conversion.

**The number a user sees as "remaining" is net, and it is derived, not stored:**

```
remainingWeight = spool.totalWeight − filament.spoolWeight     // gross − tare
```

Two consequences the plugin must respect. First, `spoolWeight` is **nullable and inherited** —
variants typically store `null` and take the parent's value — so computing net locally is a trap;
use `GET /api/filaments/:id/spool-check` (FR-4), which resolves inheritance and the null guards
already. Second, **writes debit the gross while checks read the net**, which is what makes the
over-usage case in FR-7 behave the way it does.

### C-3: Spools are embedded subdocuments — but there *are* spool-level read endpoints

Spools live in `spools[]` on the filament document, and every **write** is addressed as
`(filamentId, spoolId)`. But Filament DB does expose spool-level and identifier-level **reads**,
which an earlier draft of this document wrongly denied:

| Endpoint | Returns | Use |
|---|---|---|
| `GET /api/filaments` | list projection, embedded spools | build the picker — one call (FR-2) |
| **`GET /api/spools/{spoolId}`** | `{filament, spool}`, **filament inheritance-resolved** | **the read for an assigned spool** — one call gets everything the conversion needs |
| **`GET /api/filaments/match?instanceId=&name=&vendor=&type=`** | `{match, candidates, matchedSpool}` | resolve a scanned identifier; tier order is `instanceId → name → vendor+type → vendor` |
| **`POST /api/nfc/decode`** | `{decoded, match, candidates}` | decode raw OpenPrintTag / Bambu / OpenTag3D bytes *and* attach the DB match |

**`GET /api/spools/{spoolId}` is the right read for an assigned spool** and replaces the
fetch-the-parent-filament approach: it returns the spool and its filament in one request, with
variant inheritance already resolved (same as `GET /api/filaments/{id}`). Verified live.

The `match` and `nfc/decode` routes are deliberately **not** behind Filament DB's same-origin guard
— their docstrings name the mobile scanner app and the PrusaSlicer/OrcaSlicer integrations as
intended cross-origin callers. An OctoPrint plugin is the same class of client. When
`FILAMENTDB_API_KEY` is set, the bearer key gates them like every other `/api` route (C-7).

Still true: there is no full-text spool *search*, so the picker filters client-side over the
cached list.

### C-3b: The fields this plugin reads — and only these

Filament DB's filament document has ~40 fields. **The plugin reads seven of them.** Anything else
is out of scope; do not audit, sync, display, or file upstream issues about fields the plugin does
not use.

| Field | Used for |
|---|---|
| `_id` | identity, deep links |
| `density` | mm→g conversion (FR-6) |
| `diameter` | mm→g conversion (FR-6) |
| `type` | material-mismatch check (FR-4) |
| `vendor`, `name` | picker + sidebar display |
| `color` | picker + sidebar swatch |
| `spools[]` → `_id`, `label`, `totalWeight`, `retired`, `locationId` | picker, assignment, commit |

Net remaining and tare are **never computed locally** — `GET /api/filaments/:id/spool-check` does
that server-side (FR-4). Everything else on the document — cost, temperatures, calibrations,
presets, drying, mechanical properties, stock thresholds — belongs to Filament DB and is none of
this plugin's business.

### C-4: `density` is nullable, `diameter` is not — but inheritance is resolved server-side

From `src/models/Filament.ts`: `diameter: { type: Number, default: 1.75, min: 0.01 }` — **always
present**, because the schema default applies. `density: { type: Number, default: null, min: 0 }` —
**may be null**, and the mm→g conversion is impossible without it.

**Verified empirically against a live instance (2026-08-01), not just read off the schema:**

- Creating a filament with no `density` is **accepted** — it stores `density: null` while
  `diameter` gets the 1.75 default. So density is genuinely optional and the null case is
  reachable. The FR-6 fallback chain is necessary, not dead code.
- **Both projections resolve density from the parent.** The list route does
  `$ifNull: ["$density", {$arrayElemAt: ["$_parent.density", 0]}]`, and the detail route applies the
  same `own ?? parent` rule. A variant with no own density and a parent at 1.99 reports **1.99 in
  both**.

Two consequences, and the second removes work:

1. The fallback only ever fires for a **root** filament with no density, or a variant whose parent
   also lacks one. Narrower than a naive reading of the schema suggests — but still reachable.
2. **The plugin never needs to walk the parent chain itself.** Inheritance resolution is the
   server's job and it already does it. Do not reimplement it.

##### Verified field resolution — parent(all set) / variant(nothing set)

Measured 2026-08-02 against the live instance, not inferred, for **the fields this plugin reads**.
**`GET /api/filaments/:id` is the authoritative read for an assigned spool** — read it and trust it.

| Field | Used for | Parent | List (variant) | Detail (variant) | |
|---|---|---|---|---|---|
| `density` | mm→g conversion | 1.99 | 1.99 | **1.99** | inherited |
| `diameter` | mm→g conversion | 2.85 | *absent* | **2.85** | inherited — **detail only** |
| `type` | material check (FR-4) | required on create; always present | — | — | n/a |
| `color` | picker/sidebar swatch | `#abcdef` | `#808080` | `#808080` | own value, by design |

Two things to take from this:

- **`diameter` inherits properly — it does not fall back to the 1.75 schema default.** Worth
  confirming explicitly: a 2.85 mm parent yields 2.85 on the variant. Had it defaulted instead, the
  mm→g conversion would have been wrong by (2.85/1.75)² ≈ **2.65×** on 2.85 mm filament.
- **`diameter` is absent from the list projection**, so the picker's cached list is *not* sufficient
  for conversion. Fetch detail for assigned filaments (FR-6). `color` correctly does not inherit —
  a variant *is* a colour — so the swatch uses the record's own value.

Other filament fields (`cost`, `temperatures`, `netFilamentWeight`, `lowStockThreshold`, …) are out
of scope: the plugin does not read them. Tare and net-remaining are never computed locally either —
`spool-check` does that server-side (FR-4).

### C-5: The print-history `source` enum has no `"octoprint"` value

Accepted values are `manual | prusaslicer | orcaslicer | bambu | other`; anything else falls back to
the default. v1 sends `source: "other"` and identifies itself in `notes`. **Upstream ask:** file an
issue on `hyiger/filament-db` to add `"octoprint"` to the enum, then switch.

### C-6: OctoPrint 2.0 breaking changes that touch this plugin

Targeting 2.0 only means writing against the post-cleanup APIs from day one — no compat shims:

- **Blueprint endpoints are CSRF-protected by default.** The plugin's API needs `@csrf_exempt()`
  on anything called outside OctoPrint's own JS, or must send the token.
- `octoprint.access.users.*` is snake_case; `octoprint.users` is gone.
- `admin_permission` / `user_permission` are removed — declare explicit permissions via
  `octoprint.access.permissions`.
- `get_plugin_data_folder()` comes from `OctoPrintPlugin`, not `PluginSettings`.
- Serial settings moved to `plugins.serial_connector.*` (relevant to the dev environment, not the
  plugin itself).
- Packaging should be `pyproject.toml` with build isolation, not `setup.py`.
- `netifaces` / `passlib` are no longer bundled — not needed here, but the rule applies to any dep.
- JS: `OctoPrintClient.users` → `OctoPrintClient.access.users`; `usersViewModel` →
  `accessViewModel.users`.

`octoprint.comm.protocol.gcode.sent` **survives 2.0** — verified in the 2.0 hooks documentation. It
is still described as "triggered just after the command was handed over to the serial connection,"
which is exactly the metering point needed. Run
[`octoscanner`](https://github.com/jacopotediosi/octoscanner) against the tree in CI as a guard.

### C-7: Filament DB auth is opt-in bearer

Unauthenticated by default; when `FILAMENTDB_API_KEY` is set on the server, **every** `/api` request
needs `Authorization: Bearer <key>`. The plugin must support an optional key and store it as a
`SettingsPlugin` secret so it is redacted from the settings API.

---

## Architecture

### Component layout

```
octoprint_filamentdb/
├── __init__.py                 — plugin entry point, mixins, hook registration
├── plugin.py                   — FilamentDBPlugin: mixin composition, lifecycle
├── api.py                      — SimpleApiPlugin + BlueprintPlugin endpoints
├── settings_keys.py            — settings key constants (one place, no string literals)
├── client/
│   ├── filamentdb.py           — requests-based FDB REST client (sync; OctoPrint is threaded)
│   └── models.py               — dataclasses for the FDB shapes the plugin reads
├── metering/
│   ├── odometer.py             — per-tool extrusion accumulator (E-move state machine)
│   ├── convert.py              — mm→g conversion, density fallback, rounding
│   └── gcode_meta.py           — slicer config-block parser (PS/Orca/Bambu/Cura)
├── job.py                      — print lifecycle: start/pause/resume/terminal → commit
├── journal.py                  — durable SQLite store: every job, every write attempt (FR-9b)
├── retry.py                    — retry policy over journal rows in retryable states (FR-9)
└── static/
    ├── js/filamentdb.js        — Knockout viewmodels (sidebar, tab, settings)
    ├── css/filamentdb.css
    └── ...
templates/
├── filamentdb_sidebar.jinja2
├── filamentdb_tab.jinja2
└── filamentdb_settings.jinja2
```

### Mixins used

| Mixin | Purpose |
|---|---|
| `SettingsPlugin` | config, `get_settings_defaults`, `get_settings_restricted_paths` for the API key |
| `AssetPlugin` | JS/CSS |
| `TemplatePlugin` | sidebar + tab + settings templates |
| `SimpleApiPlugin` | `GET`/`POST` plugin API for spool list, select, clear, test-connection |
| `EventHandlerPlugin` | `PrintStarted`, `PrintPaused`, `PrintResumed`, `PrintDone`, `PrintFailed`, `PrintCancelled`, `FileSelected` |
| `StartupPlugin` | connectivity probe, resume any pending commit from disk |

### Hooks used

| Hook | Purpose |
|---|---|
| `octoprint.comm.protocol.gcode.sent` | the odometer — every command actually sent to the printer |
| `octoprint.access.permissions` | declare `FILAMENTDB_SELECT` and `FILAMENTDB_ADMIN` |

### Data flow — the happy path

```
1. User loads a spool on the machine and records it: opens the FilamentDB tab, clicks a slot,
   finds the spool (usually by typing its label number), selects it.
   → plugin stores {toolIdx: {filamentId, spoolId, source, ...cached display fields}} in settings.
   → warns immediately if that filament has no density — needs no file (FR-2, FR-6).
   NOTE: no G-code file is selected at this point, and none may be assumed. Loading a spool and
   choosing a file are separate acts, often hours apart.

2. (Optional, whenever it happens) User selects a G-code file.
   → FileSelected: read the tail of the file, parse the slicer config block.
   → Run the file-dependent checks EARLY as a convenience — material mismatch, sufficiency,
     unassigned tools — so problems surface before the user walks away.
   → This step may never happen before step 3; nothing may depend on it.

3. User hits Print.
   → CONFIRMATION DIALOG (FR-4): per tool, the spool, the estimated grams this job needs, the
     remaining after, and any problems. Continue or Cancel.
   → Frontend-only gate (wraps printerStateViewModel.print / loadAndPrint). A print started via
     the REST API skips straight to step 3b -- nothing below may depend on the dialog running.

3b. The job actually starts.
   → PrintStarted: run the authoritative checks and record their result in the journal (whether
     or not a dialog was shown); reset the odometer; snapshot the loaded-spool assignment for
     this job, so a mid-print reassignment cannot retroactively rewrite where filament came from.

4. Every command sent.
   → gcode.sent: odometer consumes G0/G1/G2/G3 E values, honouring M82/M83/G90/G91/G92 and
     T<n> tool changes. Accumulates mm per tool index.

5. Print reaches a terminal state (PrintDone / PrintFailed / PrintCancelled).
   → Convert per-tool mm → grams using each assigned spool's diameter + density.
   → Build ONE print-history payload with a usage[] entry per tool that has both an assigned
     spool and non-zero grams.
   → POST /api/print-history. Filament DB debits the spools and records the job atomically.
   → On failure: persist to the commit queue and retry (FR-9).
```

### Why an odometer rather than slicer totals or progress-scaling

Three candidate approaches were considered:

| Approach | Verdict |
|---|---|
| Read `filament used [g]` from the slicer block and post it on completion | **Rejected.** Slicer-specific (Cura gives no grams), and yields *nothing usable* on a cancelled print — the single most important case in the brief. |
| Scale the slicer/analysis total by OctoPrint's print progress fraction | **Rejected.** Progress is `filepos`-based, and G-code density per byte is wildly non-uniform (a dense infill region and a sparse travel region occupy similar byte counts). Error on a cancel is easily ±30%. |
| Software odometer on actual E-moves | **Adopted.** Slicer-agnostic, exact to what was really extruded, correct on cancel/failure/pause, and per-tool for free. |

The cost is that the odometer must correctly model extrusion state — this is the highest-risk
component in the plugin and gets the heaviest test coverage (FR-5).

---

## Codebase design constraints (agent navigability)

This project is built primarily by AI coding sessions with a fresh context each time. **The cost
of a change is dominated by how much an agent must read before it can safely edit.** That makes
navigability a real architectural constraint, not a style preference — it is written here so it
governs design reviews rather than being retrofitted by an audit later.

The failure mode to avoid is concrete and observable in `filament-bridge`: a `core/engine.py` with
line references past 4,200. Fixing twenty lines there means loading four thousand into context
first. This project bakes in the fix from the start.

**N-1: One concern per module, with a hard size cap.** 300 lines soft, **500 lines hard**. A module
crossing the hard cap gets split in the same change that crossed it — never "later." If a natural
split isn't obvious, that is itself the signal the module owns too many concerns.

**N-2: Every module opens with a docstring saying what it owns and what it does *not*.** A grep hit
should tell an agent within five seconds whether this is the right file. Example:

```python
"""Per-tool extrusion accumulator.

OWNS: E-move state machine — M82/M83, G90/G91, G92 resets, T<n> tool changes,
      G0/G1/G2/G3 E deltas. Pure: G-code strings in, {tool_index: millimetres} out.
DOES NOT OWN: mm→gram conversion (metering/convert.py), what to do with the
      totals (job.py), or anything network-facing.
"""
```

**N-3: Strict layering, enforced by an import-direction test.**

```
client/     — HTTP + Filament DB shapes.        Imports: nothing internal.
metering/   — G-code parsing + arithmetic.      Imports: nothing internal.
journal.py  — durable SQLite store (FR-9b).     Imports: nothing internal.
retry.py    — retry policy over journal rows.   Imports: journal.py, client/.
job.py      — orchestration.                    Imports: all of the above.
api.py      — plugin REST endpoints.            Imports: journal.py, job.py.
plugin.py   — OctoPrint wiring.                 Imports: job.py, api.py.
```

`metering/` must never import `client/`, and `journal.py` — pure storage — must import neither. The
payoff is a guarantee, not a guideline: **a G-code metering bug cannot possibly require reading the
API client**, so an agent can correctly ignore it. A unit test asserts the import directions so the
property can't erode.

**N-4: The core is pure functions.** Odometer, mm→g conversion, slicer-block parser, and
commit-payload builder take plain values and return plain values — no OctoPrint imports, no network,
no settings object. An agent fixing a conversion bug reads `convert.py` and `test_convert.py` and
nothing else. This is also why these components can carry heavy test coverage cheaply.

**N-5: `plugin.py` is wiring only — no logic.** The mixin class registers hooks and delegates. The
moment a decision is made inside a mixin method, it belongs in a module the tests can reach without
booting OctoPrint. God objects are how the 4,000-line file happens.

**N-6: Constants live in exactly one place.** Settings keys in `settings_keys.py`, no string
literals at call sites. Same for event names and API paths. "Where is this key used?" must be one
grep with zero false positives.

**N-7: Tests mirror source paths 1:1.** `metering/odometer.py` → `tests/test_odometer.py`. Fixing a
bug means reading exactly two files.

**N-8: A task→file routing table lives in `CLAUDE.md`** and is updated in the same commit as any
structural change. This is the highest-leverage item on the list: it converts "search the repo" into
"read two files." It is the first thing a fresh session consults after the session brief.

**N-9: Docs are split by *when you read them*, and capped.**

| Doc | Read when | Cap |
|---|---|---|
| `prompts/startnewsession.md` | first thing, every session | ~200 lines |
| `CLAUDE.md` | every session, as reference | ~200 lines |
| `docs/prd.md` | designing or implementing a feature | uncapped (it's the spec) |
| `docs/decisions.md` | before re-deriving a design | append-only |

`CLAUDE.md` must not grow into a second PRD. When it drifts toward the cap, the content moves to the
PRD and `CLAUDE.md` keeps a pointer. The session brief is a *state* document — what's in flight —
not a knowledge dump.

**N-10: Errors name their origin.** Log lines and exceptions carry the module and the operation, so
a traceback routes to the right file without a search.

---

## User interface

Designed before the metering layer, deliberately: **without a UI the odometer is a black box.** Unit
tests prove the state machine against fixtures, but they cannot show whether the hook is wired
correctly, whether non-print commands are being filtered, or whether pause/resume survives. A live
readout is the instrument for all of that.

The useful consequence: **the first instrument should display raw millimetres**, because millimetres
have *zero* dependencies. Grams need an assigned spool, a Filament DB client, a density and the
conversion; millimetres need only hook → accumulate → display. So a live mm counter is buildable
before any of the data layer exists, and it can be checked against the slicer's
`filament used [mm]` at print end — which is already FR-5's acceptance bar.

### Reference: the Spoolman plugin's sidebar

`octoprint-spoolman`'s sidebar is the proven layout and the starting point. Per tool it shows a
colour swatch, `Tool #0:`, `[PLA] PLA Pistachio Green (Prusament)`, `615.6g / 1000g`, and a greyed
`#181` (its spool id), with `✕` (clear) and `…` (more) buttons per row, and `Refresh` /
`Open Spoolman` at the bottom. Five MMU slots fit without scrolling.

A screenshot is kept locally at `private_data/screenshots/` (gitignored — not committed).

Two deliberate departures:

1. **`Tool #0`** → we display `Tool 1` by default (`toolDisplayOffset`, see FR-3). OctoPrint's own
   0-based label is the thing users dislike, and it disagrees with both the MMU hardware and
   Filament DB's `Slot 1…5`.
2. **The weight figure means something different.** See below — this is not a cosmetic difference.

### Weight display: Filament DB is gross, Spoolman is net

Spoolman's `615.6g / 1000g` is *net remaining / nominal net* — it stores net directly. **Filament DB
stores gross on the spool** (filament + reel), with the tare and nominal net on the **filament**, so
the same display has to be computed:

```
net_remaining = spool.totalWeight  −  filament.spoolWeight      (gross − tare)
nominal_net   = filament.netFilamentWeight
              →  "624 g / 1000 g"
```

Both `spoolWeight` and `netFilamentWeight` live on the filament (shared across its spools), are
nullable, and are **inheritance-resolved in both projections** (C-4) — so the list projection already
carries everything the picker needs, with no extra fetch.

Verified against the live library (36 spools): all three fields are populated, tares vary genuinely
per filament (154 / 190 / 200 / 245 g), and every spool is fully computable. So the good path is the
common one — but the degraded paths still need defining:

| Missing | Display | Why |
|---|---|---|
| tare (`spoolWeight`) | `1042 g gross · tare not set` | **Never show gross as if it were net** — it overstates remaining filament by the weight of the reel, ~200 g. Label it explicitly. |
| nominal (`netFilamentWeight`) | `624 g` — no denominator, no bar | A ratio needs both halves. |
| gross (`totalWeight`) | `not weighed` | The spool exists but has never been put on a scale. |

Two further rules:

- **Net may legitimately exceed nominal.** Manufacturers overfill; a "1 kg" reel can hold 1050 g.
  Clamp the progress bar at 100% but **show the true number** — never clamp the figure itself.
- **Show gross on hover or in the detail view.** When a user physically weighs a spool they read
  *gross*, so having it available is what makes reconciliation possible.

**This affects display and the sufficiency check only — never the commit.** The usage write sends
grams *consumed*, and Filament DB decrements gross itself (C-1). A missing tare degrades the UI and
FR-4's sufficiency check, but the core meter-and-commit loop is unaffected. That separation is worth
preserving: incomplete inventory metadata must never block recording what was actually used.

### Sidebar

Always visible; the at-a-glance state. Per tool:

```
┌─ Filament DB ──────────────────────── ● ┐
│ ▉ Tool 1                      [✕] [⋯]   │
│   [PLA] PLA Galaxy Black (Prusament)    │
│   842.0 g / 1000 g   ▓▓▓▓▓▓▓▓░░  84%    │
│   #177                                  │
│   ⌇ dried 2026-07-15                    │
│                                         │
│ ── printing ─────────────────────────── │
│ ▉ #177   ▲ 12.40 g  ·  4 062 mm         │
│                                         │
│ [⟳ Refresh]  [🗄 Open Filament DB]      │
└─────────────────────────────────────────┘
```

Field rules, following `octoprint-spoolman`'s precedent of making optional identifiers settings
toggles (it ships `showLotNumberInSidebar` / `showSpoolIdInSidebar`):

| Field | Default | Notes |
|---|---|---|
| `label` (`#177`) | **always shown** | The direct analogue of Spoolman's `#181`, and what is physically on the spool. Primary identifier. |
| `instanceId` (`970fdbcd56`) | **toggle, off** | 10 hex chars, not human-memorable. Earns its place when an NFC/QR scan misbehaves or when cross-referencing. Rendered de-emphasised beside the label. |
| `notes` | **shown only if non-empty** | Free text on the spool subdocument. One truncated line, full text on hover. Most spools have none, so it costs nothing in the common case. |
| `lotNumber` | toggle, off | Same treatment as `instanceId`. |

During a print each tool additionally shows **live metered grams *and* raw millimetres**. The
millimetre figure is the debugging instrument — it is what gets compared against the slicer's
`filament used [mm]`, and it keeps working when no spool is assigned or no density is known.

### Debug panel *(setting, off by default)*

A collapsible section exposing the odometer's internal state: current tool, absolute/relative E
mode, last E value, per-tool raw millimetres, count of `G92` resets seen, and any unsupported
commands encountered (`M200`, `G10`/`G11`, `M221`).

This exists because **a total that is silently wrong looks exactly like a total that is right.** The
state machine is the highest-risk component in the plugin (FR-5); shipping it without a readout of
its own state means debugging it from logs correlated against the terminal tab. Off by default, so
it costs ordinary users nothing.

## Functional requirements

### P0 — must ship in v1

#### FR-1: Connect to Filament DB

- Settings: **Filament DB URL** (scheme + host + port), optional **API key**, connection timeout.
- The API key is registered in `get_settings_restricted_paths()` so it is never returned by the
  settings API to a non-admin and never lands in a support bundle.
- A **Test connection** button probes `GET /api/openapi` and reports the resolved `info.version`
  (Filament DB has no dedicated health or version endpoint — this is the documented workaround
  already used by `filament-bridge`).
- Startup probe runs once, non-blocking; failure is surfaced in the sidebar as a degraded state,
  never as an exception that breaks OctoPrint startup.

#### FR-2: Browse and select spools

- `GET /api/filaments` fetches all filaments with embedded spools; the plugin flattens to a spool
  list client-side (C-3).
- Cached in memory with a configurable TTL (default 5 min) and a manual **Refresh** button. A
  library of a few hundred filaments is a single request; no pagination exists to use.
- Picker columns: colour swatch, vendor, name, material type, remaining grams, location, label,
  lot number. Sortable.

##### Finding a spool

**Loading a spool is a standalone act.** The user walks up, puts a spool on the machine, and records
it. **No G-code file is selected and no print is pending** — so nothing in this picker may depend on
knowing what will be printed. That rules out an "enough for this print" filter and any G-code-driven
pre-selection of material type; both belong to the pre-print check (FR-4), not to loading.

**One search box, ranked by match quality — no modes.** Verified against the live library, the
identifiers available per spool are a numeric `label` (all 36 spools: `5, 19, 21, 47 … 204, 224` —
the user's physical numbering), a 10-char hex `instanceId` (Filament DB's durable per-spool
identity, and the key NFC/QR resolves against), and the 24-hex Mongo `_id`. Rather than making the
user pick a search mode, one field ranks:

1. **exact `label`** — the common case; typing `177` puts spool 177 first
2. **exact `instanceId`** — a scanned or pasted tag id
3. **exact `_id`** — pasted from a Filament DB URL
4. **`label` prefix** — `17` → 170–177
5. **fuzzy** over vendor / name / type / colour name / location

Each row shows **why** it matched, so a fuzzy hit is never mistaken for an exact one. This mirrors
what `filament-bridge`'s mobile lookup learned in practice: numeric lookup is the common case, text
search is the fallback — hence its numeric-keypad default.

Search runs **client-side over the cached list** — no round-trip per keystroke. If an exact
identifier misses locally, fall back to `GET /api/filaments/match?instanceId=…` once (C-3), which
catches a spool created since the last cache refresh.

**Filters** (persistent, independent of any file):

- **Material type** chips — PLA / PETG / PC / TPU, driven by what is actually in the library.
- **Location** — 34 of 36 spools have one; this is the "which drawer is it in" filter.
- **Hide retired**, on by default.

**Default sort: most recently used on this printer**, then `label` ascending for spools never used
here. The ordering comes from the plugin's **own write journal** (FR-9b) — already stored, free, and
more relevant than any global last-used, because it reflects what this machine actually consumes. In
practice a user reloads the same handful of spools.

**Duplicate assignment: warn, do not block.** If a spool is already assigned to another tool, the
row shows an **"already on Tool N"** badge and selecting it raises a confirmation. One physical spool
usually cannot be in two slots, so this is normally a mis-click — but it is not the plugin's place to
declare a printer setup impossible. FR-7 already sums duplicate assignments into a single usage
entry, so the data stays correct either way; the badge exists so the mistake is *visible* rather than
silently averaged away.
- Retain `spools[].instanceId` in the cached model. v1 does not display it, but it is Filament DB's
  durable per-spool identity and costs nothing to keep — it is already in the list projection.
  (Resolution of a scanned tag does **not** depend on this cache: `GET /api/filaments/match` and
  `POST /api/nfc/decode` do that server-side — see C-3 and FR-14.)
- The list projection is sufficient for the picker — but **not** for conversion, since it omits
  `diameter` (C-4). The swatch uses the record's **own** `color`, which correctly does not inherit
  from the parent: a variant *is* a colour.
- **Remaining weight is computed, not read.** `net = spool.totalWeight − filament.spoolWeight`,
  against a `filament.netFilamentWeight` denominator. Both filament-level fields are
  inheritance-resolved in the list projection, so no extra fetch is needed — see
  §User interface → Weight display for the degraded paths when any of the three is null.
- **Retired spools are hidden by default**, with a toggle to show them (mirrors the Spoolman
  plugin's archived-spool behaviour).
- Selection is per tool index. Assignment is stored in settings as:

  ```yaml
  plugins:
    filamentdb:
      selectedSpools:
        "0":
          filamentId: "665f…"
          spoolId: "665f…"
          # cached for offline display only — authoritative values come from the API
          display: { vendor: "Prusament", name: "PLA Galaxy Black", type: "PLA", color: "#1a1a2e" }
  ```

- **Clear** removes the assignment for a tool. A tool with no assignment is metered but its usage
  is discarded at commit time (with a log line), never guessed at.
- **Warn at assignment time if the filament has no density.** This check needs only the spool, not a
  file, so it fires the moment a spool is loaded — the earliest and cheapest possible point. See
  FR-6 §What actually happens when there is no density.

#### FR-3: Multi-tool and MMU awareness

**Validated 2026-08-01 — an earlier draft of this requirement was wrong.** It derived the slot
count from the printer profile alone. That is not safe, for two independent reasons.

**Finding 1: the MMU tool count is manual user configuration, and nothing enforces it.**
OctoPrint learns an MMU has 5 tools only because the user set **Number of extruders = 5** and
ticked **Shared nozzle** in the printer profile. Prusa's own OctoPrint documentation instructs
this. It is not auto-detected, and — verified against
[`jukebox42/Octoprint-PrusaMMU`](https://github.com/jukebox42/Octoprint-PrusaMMU) — the MMU plugin
**does not set it either**; that plugin works at the G-code and firmware-message level (intercepting
`Tx`, parsing `MMU2:` responses) and never touches the profile. So a working MMU setup can easily
report `extruder.count = 1` while the G-code drives `T0`–`T4`. Silently rendering one slot and
charging five tools' filament to it would be a data-corruption bug, not a UI annoyance.

**Finding 2: another plugin can rewrite or suppress the tool command before the odometer sees it.**
A `gcode.queuing` handler may replace a command or drop it with `None,`, and a dropped command never
reaches `gcode.sent`. `Octoprint-PrusaMMU` — which the maintainer runs on the test rig — does both:
it **remaps** `T<n>` to a different tool when filament mapping is enabled, and **suppresses** the
literal `Tx` placeholder while it prompts the user. An odometer that infers the active tool purely
from observed tool commands can therefore diverge from what the file asked for. See §Known plugin
interactions.

Requirements that follow:

**Confirmed against OctoPrint 2.0.0rc4 (Q-4): the profile model is unchanged.** `printer/profile.py`
still defines `extruder.{count, offsets, nozzleDiameter, sharedNozzle, defaultExtrusionLength}` with
defaults `count: 1` and `sharedNozzle: False`, validated `0 < count < 100`. There is no new tool
abstraction in 2.0, so everything below applies as written.

- **Slot count is the union of three sources**, not the profile alone:
  1. `self._printer_profile_manager.get_current_or_default()["extruder"]["count"]`
  2. tool indices present in OctoPrint's analysis metadata (`analysis.filament.tool0…toolN`)
  3. the per-extruder array length in the slicer config block, when present
- **When the G-code uses more tools than the profile declares, render the larger number and warn
  prominently**, naming the fix ("your printer profile says 1 extruder but this file uses 5 tools —
  set Number of extruders to 5 and tick Shared nozzle"). Never silently collapse tools.
- **Track the active tool defensively.** Maintain the odometer's tool index from observed `Tx`, but
  reconcile it against OctoPrint's own current-tool state rather than trusting the command stream
  as the sole source. Log a warning when the two disagree.
- **Cross-check per-tool attribution at commit time — but expect legitimate divergence.** When the
  slicer block supplies a per-extruder `filament used [mm]` array, compare the odometer's per-tool
  distribution against it. If the **total** agrees but the **per-tool split** does not, warn and
  record the discrepancy in the print-history `notes` rather than writing a confidently wrong split.

  **This check false-positives when tool remapping is active.** The slicer array is indexed by the
  *file's* tool numbers; a remapping plugin makes the printer use *different physical* tools. Both
  the odometer and the spool assignment then correctly follow the physical tool while the slicer
  array does not. Detect the condition (see §Known plugin interactions) and downgrade the mismatch
  to an informational note instead of a warning.
- `extruder.sharedNozzle` is read and displayed, because it changes what the numbers mean: on a
  shared nozzle, tool-change purge is attributed to whichever tool is active at the time of the
  purge. That is physically correct, but users should see that purge waste lands on a tool rather
  than being tracked separately.
- Profile changes at runtime re-render the slots. Assignments for tool indices that no longer exist
  are retained in settings (not deleted) but hidden, so downgrading and re-upgrading a profile does
  not silently lose them.

##### Tool numbering: 0-based internally, 1-based on screen

There is a real three-way mismatch here, verified against both systems:

| Source | Numbering | Evidence |
|---|---|---|
| G-code `T<n>` | **0-based** | `T0` is the first tool |
| OctoPrint internals | **0-based** | keys are `"tool" + extruder`; analysis emits `tool%d` |
| OctoPrint UI | **"Tool 0"** | `gettext("Tool") + " " + extruder` — literally the array index |
| Prusa MMU hardware | **1-based** | slots are physically labelled 1–5 |
| Filament DB AMS slots | **1-based** | the dev instance's Core One has `slotName: "Slot 1" … "Slot 5"` |

**OctoPrint has no setting to change this.** Searched 2.0's source for `toolOffset`,
`firstToolNumber`, `toolNumbering` and similar — nothing exists. The label is derived straight from
the index, so the only way to present a different number is to do it ourselves.

Rules:

- **Internal keys are always 0-based**, matching `T<n>` and OctoPrint's `tool<n>`. This is the wire
  format, not a preference. **Never renumber internally** — an offset applied anywhere but the view
  layer is how off-by-one bugs get into inventory data.
- **Display defaults to 1-based** for multi-tool setups, because that is what the user reads off the
  printer *and* off Filament DB. A `toolDisplayOffset` setting (default `1`) covers anyone who
  prefers otherwise.
- **Show both where it could be ambiguous** — `Slot 1 (T0)`. Cheap, and it removes all doubt when
  cross-referencing a G-code file or an OctoPrint terminal log.
- **Single extruder: follow OctoPrint and drop the number entirely** — it labels a lone tool just
  `"Tool"`, with no index, and diverging from that would be gratuitous.
- **The data path never depends on any of this.** Filament DB identifies AMS slots by `_id`, not by
  index or name, so FR-11's mapping is `tool_index → slotId` and the numbering question cannot reach
  stored data.

**Verification targets** (these are acceptance tests, not assumptions):

1. A 5-tool shared-nozzle profile renders 5 slots, and `T3` in the stream routes extrusion to
   slot 3.
2. A **1-extruder profile** printing a 5-tool MMU file renders 5 slots **and** raises the profile
   warning.
3. With `Octoprint-PrusaMMU` installed on an MK3s-style flow, tool attribution is still correct —
   or, if it cannot be, the cross-check fires. **This needs testing against a real MMU3 setup;
   the virtual printer cannot reproduce the plugin's `Tx` interception.**

#### FR-4: Pre-print validation

**Timing matters, and an earlier draft got it wrong.** It triggered these checks on `FileSelected`,
which quietly assumed loading a spool and choosing a file are part of one flow. They are not: a user
loads spools when they load spools, and picks a file later — often much later, often having loaded
nothing since. **At load time there is no file, so nothing about the print can be known.**

Checks are therefore grouped by **what they actually depend on**, and each runs at the earliest
point its inputs exist:

| Check | Depends on | Runs at |
|---|---|---|
| Filament has no density | the spool alone | **assignment time** (FR-2) — no file needed, earliest possible warning |
| Filament DB unreachable | nothing | startup + print start |
| No spool assigned for a tool the file uses | file **+** assignment | **print start** |
| Material mismatch | file **+** assignment | **print start** |
| Insufficient filament | file **+** assignment | **print start** |

**Print start is the authoritative gate.** It is the last moment before filament is consumed and the
only moment both the file and the assignments are guaranteed known. `FileSelected` is an *early
bonus* — if a file happens to be selected, run the file-dependent checks then too, so problems
surface before the user walks away. It is not the primary trigger, and nothing may depend on it
having fired.

Re-run the file-dependent checks whenever an assignment changes *while* a file is selected.

Reads, in priority order:

1. **Slicer config block** — the tail of the G-code file. PrusaSlicer, SuperSlicer, OrcaSlicer and
   Bambu Studio append `; key = value` lines at end-of-file:
   - `filament_type` — per-extruder, e.g. `PLA;PETG`
   - `filament used [g]`, `filament used [mm]`, `total filament used [g]`
   - `filament_settings_id` — the preset *name*
   Only the last ~64 KB of the file is read; the block is at the end and files can be hundreds of MB.
2. **OctoPrint's own analysis metadata** — `_file_manager.get_metadata()` gives
   `analysis.filament.tool0.length` (mm) and `.volume` (cm³), computed by OctoPrint from E-moves
   regardless of slicer. This is the universal fallback for the sufficiency check.

Checks performed:

| Check | Requires | Behaviour |
|---|---|---|
| **No spool assigned** | file + assignment | Warn per unassigned tool that the G-code actually uses. |
| **Material mismatch** | slicer block | Warn when `filament_type[n]` ≠ the assigned spool's `type` (case-insensitive, trimmed). |
| **Insufficient filament** | slicer block *or* analysis | Warn when required grams exceed the spool's remaining **net** filament, minus a configurable safety buffer (default 0 g). Use Filament DB's own `spool-check` endpoint — see below. |
| **Filament DB unreachable** | — | Warn that usage will not be recorded. |

**Cura emits no material type** (a declined upstream feature request), so the mismatch check simply
does not fire for Cura-sliced files. The sufficiency check still works via the analysis fallback.
The UI must say *why* a check was skipped rather than showing a silent pass — a green tick that
means "not checked" is worse than no tick.

##### The pre-print confirmation dialog

The checks are not a scattering of warn/block toggles. They surface in **one dialog shown when the
user hits Print**, which is the workflow the Spoolman plugin proved and users already expect:

> **Print start → "here is what this job will consume from each spool, plus anything that looks
> wrong" → Continue or Cancel.**

Contents, per tool: the assigned spool, the **estimated grams this job needs**, the remaining after,
and any detected problems (unassigned tool, material mismatch, insufficient filament, missing
density, Filament DB unreachable). Showing the numbers even when nothing is wrong is the point — it
is the moment the user confirms they loaded what they think they loaded.

Setting: **always show** (default) / **only when there are problems** / **never**.

**Mechanism (Q-9, resolved).** OctoPrint fires `PrintStarted` *after* the job begins, so a backend
gate cannot cleanly stop it — by then the printer has homed and may have purged. The gate is
therefore **frontend**: wrap the print function on OctoPrint's own view model and call the original
only on confirm. Verified against `octoprint-spoolman`, which does exactly this:

```js
const origPrint = self.printerStateViewModel.print;
self.printerStateViewModel.print = function confirmBeforeStartPrint() {
    // show modal; on 'onConfirm' → origPrint()
};
```

**Both entry points must be wrapped** — `printerStateViewModel.print` *and* `loadAndPrint` (the
Files-list "load and print" action). Wrapping only the first leaves a common path ungated.

**This is a UX gate, not a guarantee, and the backend must never depend on it.** It only covers
prints started from the OctoPrint UI; a job started via the REST API, by a queue plugin, or by any
other route bypasses the dialog entirely and goes straight to `PrintStarted`. So:

- Metering, snapshotting and commit are driven purely by backend events and work regardless (FR-5,
  FR-7).
- The authoritative checks still **run** at `PrintStarted` and record their results in the journal,
  even when no dialog was shown. A bypassed dialog must never mean an unchecked, unrecorded print.

**Fragility to watch:** monkey-patching another view model's method is inherently brittle, and
OctoPrint 2.0 changed several view models. Verify against 2.0 and fail soft — if the wrap cannot be
applied, log it and fall back to notification-only warnings rather than breaking the Print button.

**Use `GET /api/filaments/:id/spool-check?weight=N` rather than computing net remaining locally.**
Filament DB's own endpoint already handles three things the plugin would otherwise reimplement and
get wrong:

- **gross → net conversion** (`remainingWeight = spool.totalWeight − filament.spoolWeight`)
- **variant inheritance of the tare** — variants typically store `spoolWeight: null` and inherit it
  from the parent; reading `filament.spoolWeight` directly returns null and silently skips the check
- **null-tare and retired-spool guards**, plus a ready-made human-readable `warning` string

It returns `{ok, requiredWeightG, requiredLengthM, spools:[{label, remainingWeightG, enough}]}`.
The local analysis fallback is still needed to *derive* the required grams when the slicer block is
absent, but the sufficiency comparison itself should be the server's answer.

**Block mode must stay off by default**, and the over-usage case in FR-7 is why: Filament DB's
recorded weight is an estimate, so "not enough filament" is frequently wrong in the user's favour.

#### FR-5: Extrusion metering (the odometer)

A per-tool accumulator fed by `octoprint.comm.protocol.gcode.sent`, tracking millimetres of
filament advanced per tool index.

State it must model correctly:

- **`G0` / `G1`** — linear moves; take the `E` parameter.
- **`G2` / `G3`** — arc moves; also carry `E`. (Called out explicitly in
  [filament-db#1039](https://github.com/hyiger/filament-db/issues/1039); a naive implementation that
  only handles `G0`/`G1` silently under-counts on arc-heavy G-code.)
- **`M82` (absolute) / `M83` (relative)** extrusion mode, and the fact that `G90`/`G91` set the
  *positioning* mode which on some firmwares also governs E. Track both and resolve per firmware
  convention, defaulting to Marlin behaviour.
- **`G92 E<n>`** — resets the extruder origin without extruding. A missed `G92` in absolute mode
  produces a single enormous phantom extrusion; this is the classic failure mode of naive odometers.
- **`T<n>`** — tool change; subsequent extrusion accrues to the new tool index.
- **Retractions** — negative deltas. Net accumulation, not absolute value, so a retract/prime pair
  nets to zero.
- **Never count** commands the plugin itself or another plugin injects outside the print stream.
  Filter on the printing state, not merely on receiving the hook.

**Validated against real hardware.** The capture in
[`tests/fixtures/serial/mmu3-filament-change-runout.md`](../tests/fixtures/serial/mmu3-filament-change-runout.md)
confirms the accumulation model exactly. Between `G92 E0.0` at `N2386` and `M114` at `N2406`, the
relative-E sum — including a `G92` reset and a retract/prime pair netting to zero — comes to
**4.05109 mm**, and the firmware answers `E:4.05`. That is a ready-made unit-test assertion against
real firmware behaviour rather than invented data, and it covers `M83`, `G92`, and retraction
netting in one go.

**Known accuracy limit — firmware can extrude without the host seeing it.** The same capture shows
the extruder position moving **4.05 → 9.67 mm (+5.62 mm) with no host-issued command**, during the
MMU unload/eject sequence. The odometer cannot observe this: those moves never appear in
`gcode.sent`.

The mass involved here is negligible — 5.62 mm of 1.75 mm filament is about **0.017 g** — but the
error is **systematic and always in the same direction** (under-count), and a full multi-material
tool change with firmware-side ramming would be materially larger. v1 accepts this and documents it
rather than pretending to precision it does not have. Two mitigations are noted for later, neither
in v1 scope:

- Firmware position reports (`Recv: X:… E:…`, seen unsolicited in the capture) carry the extruder's
  own E counter. Reconciling the odometer against it between `G92` resets would both *detect* and
  *quantify* the drift.
- Any changeover marker (FR-12) implies a firmware-side sequence occurred, so the marker itself is a
  hint that a gap exists at that point in the timeline.

**Known interaction — another plugin can rewrite or suppress tool commands before the odometer sees
them.** A handler on `octoprint.comm.protocol.gcode.queuing` may return a replacement command, or
suppress one entirely with `None,` — and a suppressed command **never reaches `gcode.sent`**.
`Octoprint-PrusaMMU`, which the maintainer runs, does **both**. See §Known plugin interactions for
the detail and why the net effect on metering is mostly benign.

Non-goals for the odometer in v1: volumetric extrusion (`M200`), firmware retraction (`G10`/`G11`),
and per-extruder-multiplier compensation (`M221`). Each is logged as an unsupported-command warning
once per print so the user knows the count may be off, rather than silently producing wrong data.

**Testing.** This component is pure and deterministic — a list of G-code strings in, a dict of
per-tool millimetres out. It gets a fixture-driven unit test suite with real sliced files
(PrusaSlicer single-tool, PrusaSlicer 5-tool MMU, OrcaSlicer, Cura, an arc-heavy file), each with a
hand-verified expected total cross-checked against the slicer's own `filament used [mm]`. Agreement
within ~1% of the slicer's figure is the acceptance bar; systematic disagreement means the state
machine is wrong.

#### FR-6: mm → grams conversion

```
volume_mm3 = π × (diameter_mm / 2)² × length_mm
grams      = volume_mm3 / 1000 × density_g_cm3
```

Sanity check: 1000 mm of 1.75 mm filament at 1.24 g/cm³ → 2.98 g. Cross-checked against Filament
DB's own `spool-check` endpoint, which reports 42.5 g ≡ 14.03 m (3.03 g/m) — consistent.

Inputs come from the **filament** document of the assigned spool: `diameter` (always present,
defaults to 1.75) and `density` (**nullable** — C-4).

Density fallback chain, in order:

1. **The density returned by the API** — already `own ?? parent`, because Filament DB resolves
   variant inheritance server-side in both projections (C-4). **Do not walk the parent chain in the
   plugin**; it is already done.
2. A per-material-type default from a settings map (`PLA: 1.24, PETG: 1.27, ABS: 1.04, ASA: 1.07,
   TPU: 1.21, PA: 1.14, PC: 1.20`), matched on the filament's `type`.
3. A global fallback density setting (default 1.24).

Steps 2–3 fire only for a **root** filament with no density, or a variant whose parent also lacks
one — verified reachable, but uncommon. That rarity is a testing hazard, not a reason to skip the
fallback: it means the path will almost never be exercised by accident, so it needs a deliberate
fixture (see Test strategy).

##### What actually happens when there is no density

The plugin always knows the **length** exactly — the odometer counts millimetres. Filament DB
accepts only **grams**. Density is the sole bridge between them, so a missing density means the
conversion cannot be done from measurement alone. The handling is three-layered: warn early,
degrade honestly, stay correctable.

**1. Prevent — warn at assignment time, not at commit.** This check needs only the spool, so it
fires the moment the spool is loaded (FR-2) — no file required, and the earliest point it possibly
can. The warning names the filament and deep-links straight to it in Filament DB, where the fix takes
ten seconds. Discovering it after a 12-hour print is the failure this exists to avoid. It is repeated
at print start alongside the file-dependent checks.

**2. Degrade — estimate, commit, and mark it everywhere.** If the user prints anyway, the job is
**never dropped and never silently guessed**. Grams are computed from the material-type default,
the usage commits normally, and the estimate is disclosed in four places: the commit toast, the
journal row (FR-9b), the print-history `notes` field in Filament DB, and the plugin log.

Accuracy is worth being honest about, because it varies wildly:

- **Common unfilled materials cluster tightly** — PLA ≈ 1.24, PETG ≈ 1.27, ABS ≈ 1.04. A
  type-matched default is typically within 1–3%, comfortably inside the ±2–3% that filament
  diameter tolerance already imposes. The estimate costs almost nothing.
- **Filled and exotic materials do not** — wood-, metal-, glow- and carbon-filled blends and TPU
  range from ~1.1 to over 2.0. A default can be **30%+ wrong**. When the filament's `type` is not
  in the map and the global fallback is used, say so specifically rather than reusing the mild
  wording from the common case.

**3. Recover — the journal keeps the raw millimetres.** FR-9b records metered mm per tool
alongside the computed grams and a `density_estimated` flag. So once a real density is entered in
Filament DB, the entry can be recomputed exactly and the correction applied — the measurement was
never lost, only the conversion was uncertain. This is why the journal stores mm and not just the
final grams.

**Setting: `onMissingDensity` — `estimate` (default) | `block`.** `block` refuses the print in the
pre-print check for users who would rather fix the data than carry an estimate. There is
deliberately no "commit zero" or "skip silently" option: both quietly under-report real consumption,
which is the one outcome worse than an estimate.

**The plugin never writes a density back to Filament DB.** Guessing a value into the material
database would turn a one-job estimate into permanent library truth, and v1 writes print-history
records only (C-1).

**Confirmed against a live instance (Q-1): the list projection carries `density` but NOT
`diameter`.** `diameter` appears only in the inheritance-resolved views.

So the plugin resolves conversion inputs per **assigned spool** — never for the whole library —
via **`GET /api/spools/{spoolId}`**, which returns `{filament, spool}` with the filament's variant
inheritance already resolved (C-3). One request per loaded tool, refreshed on assignment change.
`GET /api/filaments/{id}` would also work, but the spool-level route is a better fit: the plugin
already holds the `spoolId`, and it gets the spool back in the same call.

Embedded spools in the list projection carry `_id, instanceId, label, locationId, openedDate,
purchaseDate, retired, totalWeight` — enough to render the picker (FR-2) without any detail fetch.

##### Precision and rounding

**The rule that matters for correctness: never round an intermediate value.** The odometer
accumulates millimetres as full-precision floats and the conversion to grams happens **once**, at
commit time, on the final per-tool total. Rounding per G-code command and then summing would
accumulate error across the hundreds of thousands of moves in a real print — a genuine bug, not a
cosmetic one.

Rounding therefore happens at exactly two boundaries:

| Boundary | Precision | Rationale |
|---|---|---|
| **Wire** — `grams` in the print-history payload | **3 decimal places** | ≈ 1 mm of 1.75 mm filament. Finer than any real accuracy in the system. |
| **UI** — sidebar, toasts, pre-print checks | **2 decimal places** | 0.01 g ≈ 3 mm of filament; more digits is false precision on screen. |

**Why round on the wire at all rather than sending the raw float.** The physical accuracy of this
measurement is nowhere near float precision: filament diameter tolerance alone is roughly ±0.02 mm
on 1.75 mm stock, which is ±2–3 % on volume, and Filament DB's `density` values carry two or three
significant figures. A committed value of `12.399999999999999` claims precision the system does not
have by several orders of magnitude, and it lands in Filament DB's stored `totalWeight` and usage
history where a user reads it. Rounding to 3 dp discards at most 0.0005 g per usage entry — around
0.00005 % of a 1 kg spool, unbiased, and utterly swamped by the diameter tolerance. The
readability is worth vastly more than the precision given up.

Related numeric rules:

- **Comparisons use unrounded values.** The pre-print sufficiency check (FR-4) compares full
  precision; only the number *displayed* is rounded.
- **Clamp each usage entry at 0 before sending.** A tool whose net extrusion is negative — possible
  in principle for a tool that only ever retracted — would produce a negative `grams`, which
  Filament DB rejects with a `400`. Because the whole payload is one transactional request, that
  single bad entry would fail the commit for **every** tool and lose the entire job's usage. Clamp
  per entry, and log when a clamp fires since it indicates an odometer state bug.
- **Guard against negative zero.** `-0.0` must serialize as `0`, not `-0`.

#### FR-7: Commit usage to Filament DB

Fires once per print, at the terminal state.

Trigger events: `PrintDone`, `PrintFailed`, `PrintCancelled`. **`PrintPaused` does not commit** —
this deliberately differs from the Spoolman plugin, which commits on pause. Filament DB's unit of
record is a *job*, and committing at each pause would fragment one physical print into several
`PrintHistory` documents. The odometer accumulates across pause/resume and commits once.

`PrintPaused` is still handled, but only to **record a changeover marker** (per-tool odometer
snapshot + timestamp) and persist it with the job state — see FR-12. v1 does not act on markers
beyond noting the pause count in the record's `notes`.

**Cancel produces `PrintCancelled` followed by `PrintFailed`.** A `last_print_cancelled` flag
suppresses the duplicate, exactly as the Spoolman plugin does. Without it every cancelled print
double-commits.

Payload:

```jsonc
POST /api/print-history
{
  "jobLabel":  "benchy_0.2mm_PLA_MK4.gcode",   // truncated to 200 chars
  "printerId": "<optional, from settings>",     // v1: usually unset
  "startedAt": "2026-08-01T10:00:00Z",
  "source":    "other",                         // C-5 — no "octoprint" enum value yet
  "notes":     "OctoPrint FilamentDB v1.0.0 · result: cancelled at 41% · density estimated for T1",
  "usage": [
    { "filamentId": "665f…", "spoolId": "665f…", "grams": 12.4 },
    { "filamentId": "665f…", "spoolId": "665f…", "grams": 3.1 }
  ]
}
```

Rules:

- **One `usage[]` entry per tool** that has an assigned spool *and* non-zero metered grams. Tools
  with no assignment are dropped, with a log line naming the discarded grams.
- **Assignments are snapshotted at `PrintStarted`**, not read at commit time. Reassigning a spool
  mid-print must not retroactively change where the already-consumed filament is charged.
- If two tools resolve to the **same spool**, their grams are summed into one entry. Sending two
  entries for the same spool works but produces a confusing double row in the FDB usage history.
- **Skip the POST entirely** when total metered grams across all assigned tools is zero (e.g. a
  print cancelled before the first extrusion). API constraints require 1–100 usage entries.
- **Grams are rounded to 3 decimal places and clamped at 0** — see FR-6 §Precision and rounding.
  Summing for the same-spool case happens on unrounded values; rounding is applied once, last.
- **Never cap the committed grams at what the spool supposedly holds** — see §Over-usage below.
- **Always send `spoolId` explicitly** (Q-6). It is *optional* in the API, and that is precisely the
  hazard: omitting it makes Filament DB silently pick the first non-retired spool with
  `totalWeight > 0`, falling back to the first non-retired spool. That is an implicit inventory
  choice the user never made, on a request that debits real weight.
- Constraints to respect: `jobLabel` ≤ 200 chars; 1–100 usage entries; `grams` non-negative and
  ≤ `MAX_USAGE_GRAMS` = **1,000,000 g** (Q-5 — a 1-tonne overflow backstop, ~50× the largest spool
  sold, so it will never fire on a real job); `notes` ≤ 2000 chars.
- On success, fire a plugin event and push the updated spool weights to the sidebar.

##### Over-usage — printing more than the spool is recorded as holding

A routine, expected case, not an error: Filament DB's stored weight is an **estimate** that drifts
from reality (spools are rarely reweighed, tare values are nominal, manufacturers overfill). A job
needing 25 g on a spool recorded as having 24 g left will usually print fine.

Worked example, tare 200 g:

| Step | Value |
|---|---|
| stored `spool.totalWeight` (gross) | 224 g |
| displayed remaining (net = gross − tare) | 24 g |
| job consumes | 25 g |
| Filament DB writes `max(0, 224 − 25)` | 199 g |
| displayed remaining `max(0, 199 − 200)` | **0 g** ✓ |

**The desired outcome — the spool shows empty — happens natively.** Both the print-history and
usage routes clamp with `Math.max(0, …)`, and `spool-check` clamps the derived net at 0 as well.
No special handling is needed to make the spool read 0.

Requirements:

- **Commit the full metered grams. Never cap the value at the spool's recorded remaining.** The
  usage record must state what was physically extruded. Capping it at 24 g would understate real
  consumption, silently corrupt the material-cost picture, and destroy the only signal that the
  stored weight was wrong.
- **Detect the overshoot and surface it**, since it is genuinely actionable: *"Committed 25.000 g to
  spool `Galaxy Black #3`. It was recorded as holding 24.0 g and is now empty — 1.0 g over. The
  recorded weight was low; reweigh the spool or mark it retired."* Also add it to the
  print-history `notes`.
- **Do not auto-retire the spool.** A spool reading 0 may still have usable filament, and retiring
  is a user decision. Offer it as a one-click action in the toast instead.
- **The overshoot grams are charged nowhere**, which is the correct outcome — the filament came off
  this spool and the spool is now empty. Do not attempt to spill the excess onto another spool.

**Known upstream wart (documented, not worked around).** Because the clamp floors the **gross** at
0 rather than at the tare, the stored `totalWeight` above ends at 199 g — 1 g less than an empty
reel physically weighs. The displayed net is unaffected (`spool-check` re-clamps at 0), so this is
cosmetic in Filament DB itself, but a below-tare gross can propagate oddly to anything else reading
that field. v1 deliberately does **not** issue a corrective `PUT` to set `totalWeight = tare`:
that would be a second, non-transactional write outside the C-1 single-write rule, and a partial
failure between the two would be worse than the wart. Filed as an upstream suggestion instead —
floor at `spoolWeight` when the tare is known, falling back to 0 when it is null.

#### FR-8: Result reporting in the UI

- Sidebar shows, per tool: colour swatch, vendor + name, remaining grams, and live metered grams
  during a print. All displayed grams use **2 decimal places** (FR-6 §Precision and rounding).
- After a commit: a toast naming the job, the grams committed per spool, and a deep link to the
  record in Filament DB (`{FILAMENTDB_URL}/filaments/{filamentId}` — Filament DB has **no
  standalone spool page**, so spool links point at the parent filament).
- On commit failure: a persistent (non-auto-dismissing) error with the reason and the pending-retry
  state. Losing usage silently is the worst possible failure for this plugin.

#### FR-9: Durable write queue and retry policy

OctoPrint restarting, the host losing power, or Filament DB being down at the moment a print ends
must not lose the usage record.

- The odometer's per-tool totals and the snapshotted assignment are persisted to the journal
  (FR-9b) **periodically during the print** (default every 60 s and on every tool change) and on
  every terminal event.
- **There is no separate queue store.** "The queue" is a query over journal rows in a retryable
  state. A standalone pending-commit file plus a job log would be two sources of truth for the same
  fact, and they would drift.
- On startup, any row left `pending` or in a retryable failure state is picked up and surfaced.
- Automatic retry is **bounded and conservative**: retry only on errors that are unambiguously
  pre-write — connection refused, DNS failure, HTTP 5xx *before* any response body, request-level
  timeout with no bytes sent. Exponential backoff, capped attempt count.
- **A timeout *after* the request was sent is never auto-retried.** Filament DB has no idempotency
  key, so a blind retry risks double-debiting a job that actually landed. These are parked as
  `failed_ambiguous` for the user to resolve, with a deep link to Filament DB's print history so
  they can see whether the job recorded.

  This is a real limitation, and the honest fix is upstream: an idempotency key (or a
  client-supplied job UUID) on `POST /api/print-history` (upstream ask #2).

- **4xx validation errors are never auto-retried either** — the payload will fail identically.
  These become `failed_permanent` and need user action.

#### FR-9b: Write journal and job history UI

**This is the plugin's trust surface, and it is a P0 differentiator — not nice-to-have.** The
common complaint about comparable integrations, including the Spoolman OctoPrint plugin, is that
they do not tell you what they did. A tracker that fails silently is worse than no tracker at all,
because you believe your inventory is correct when it is not. Every write this plugin attempts —
**successful or not** — is recorded and visible.

**Store.** A SQLite database in the plugin data folder (`get_plugin_data_folder()`), via stdlib
`sqlite3` — no new dependency. Chosen over an append-only JSONL file because rows are *mutated*
(attempt counts, state transitions, user resolution) and need querying and pagination; JSONL would
need compaction and would drift.

**One row per job**, recording:

| Field | Notes |
|---|---|
| job label, file path | as sent in `jobLabel` |
| started / ended timestamps, terminal state | done / failed / cancelled |
| per-tool detail | spool (filament id, spool id, display name), **metered mm**, computed grams, `density_estimated` flag + the density value actually used |

**Metered millimetres are stored, not just the final grams.** That is deliberate: length is the
measurement, grams are a derived value, and the derivation can be wrong when density was estimated
(FR-6). Keeping mm means such an entry can be **recomputed exactly** once a real density exists,
instead of the measurement being lost to a bad conversion.
| the exact payload sent | verbatim, so it can be replayed or pasted into a bug report |
| outcome state | see state machine below |
| attempt count + timestamp and error of each attempt | HTTP status, reason, response body excerpt |
| Filament DB record id | on success — enables the deep link |
| warnings raised | density fallback, over-usage overshoot, tool-attribution mismatch, unassigned tools dropped |

**State machine:**

| State | Meaning | Auto-retry? |
|---|---|---|
| `pending` | metered, not yet accepted | in flight |
| `committed` | Filament DB accepted it | — |
| `failed_retryable` | unambiguously pre-write failure | **yes**, with backoff |
| `failed_ambiguous` | timeout after send — may or may not have landed | **no** — double-debit risk |
| `failed_permanent` | 4xx validation error | **no** — will fail identically |
| `resolved_manually` | user recorded it in Filament DB by hand | — |
| `discarded` | user chose to drop it | — |

**UI — a "History" section in the plugin tab**, newest first, filterable by state:

- Each row shows job name, date, terminal state, total grams, per-spool breakdown, and outcome.
- **Failures show the reason inline** — HTTP status and message, not a generic "error". The whole
  point is that the user can act on it.
- Per-row actions:
  - **Retry** — re-attempt the write. On a `failed_ambiguous` row, **confirm first** with a warning
    that it may already be recorded, plus a deep link to Filament DB's print history to check.
  - **Mark resolved** — "I recorded this manually," stops the nagging without falsely claiming the
    plugin wrote it.
  - **Remove entry** — discard. Confirmed, because it destroys the record of consumed filament.
  - **Copy payload** — the exact JSON, for manual replay or a bug report.
  - **Open in Filament DB** — deep link to the created print-history record, on success.
- **Bulk retry** for all `failed_retryable` rows, for the "Filament DB was down all weekend" case.

**Nagging, deliberately.** A badge on the plugin tab shows the count of unresolved failures, and
the sidebar carries a persistent warning while that count is above zero. Only `resolved_manually`
and `discarded` clear it. Silence is the failure mode being designed out.

**Retention.** Keep the last N jobs (default 500, configurable). **Retention never deletes an
unresolved failure** — only `committed`, `resolved_manually`, and `discarded` rows are eligible for
pruning. Auto-deleting a failed write the user has not dealt with would recreate the exact problem
this requirement exists to solve.

**Export.** A "download journal as JSON/CSV" action, so a user can reconcile in a spreadsheet or
attach it to an issue.

#### FR-10: Permissions

Two plugin permissions via the `octoprint.access.permissions` hook:

- `FILAMENTDB_SELECT` — view spools and assign them to tools, view the write journal, and retry a
  failed write. Default: granted to Operator.
- `FILAMENTDB_ADMIN` — change plugin settings (URL, API key, check modes), and **discard or
  bulk-modify journal entries**. Default: Admin only. Destroying the record of consumed filament is
  an admin action.

Blanket `admin_permission` is removed in OctoPrint 2.0 (C-6); this is the required replacement, not
a nice-to-have.

---

### P1 — designed in v1, shipped in 1.1

These are **not built in v1**, but the v1 architecture must not preclude them. Each is called out
here so the seams exist from the start.

#### FR-11: Filament DB printer slot assignment *(1.1)*

Filament DB models printers with AMS slots and supports assigning a spool to a slot:

```
GET    /api/printers                      → printers with amsSlots[] and occupancy
GET    /api/spools/:spoolId/assignment
PUT    /api/spools/:spoolId/assignment    { printerId, slotId }
DELETE /api/spools/:spoolId/assignment
```

**v1 keeps loaded-spool state in OctoPrint only.** Filament DB learns what was used via
print-history at job end, nothing more.

**Required v1 seams** so 1.1 is additive:

- A **settings toggle** `pushSlotAssignment` (default `false`) is *defined in v1's settings schema*
  and rendered as a disabled "coming in 1.1" control, so enabling it later needs no settings
  migration.
- Settings schema reserves `filamentDbPrinterId` and a `toolSlotMap` (`{ "0": "<slotId>", … }`).
  **Keyed by 0-based tool index, valued by the slot's Filament DB `_id`** — never by slot name or
  slot number. Verified against the dev instance: `amsSlots[]` entries carry an `_id` plus a
  free-text `slotName` (`"Slot 1" … "Slot 5"`), so the `_id` is the only stable identifier and the
  0-vs-1 numbering question never touches stored data.
- A Filament DB printer record for the target machine already exists on the dev instance
  (`Prusa Core One`, 5 AMS slots), so this is testable when the time comes.
- All spool assign/clear operations in v1 route through a **single internal choke point**
  (`assignment.set(tool, spool)` / `assignment.clear(tool)`) rather than writing settings from
  several call sites. 1.1 adds the FDB write inside that one function.
- Filament DB's own docs warn AMS slot assignments are "reliable only in single-database
  deployments" (sync remapping caveat). The 1.1 setting's help text must repeat that warning.

#### FR-12: Mid-print spool change *(1.1)*

Close out the outgoing spool's accumulated grams, prompt for the new spool, and start accruing to
it — so one job can charge two (or more) spools on the same tool. Requested in
[filament-db#1039](https://github.com/hyiger/filament-db/issues/1039). The dominant real-world
trigger is **a spool running out mid-print** and the user loading a replacement.

**Can this be tracked accurately? The metering is exact; the *detection* is the hard part.**
These are separate problems and conflating them is how this feature gets designed wrong.

**Metering — exact, no estimation involved.** The odometer knows precisely how many millimetres
were extruded before the changeover boundary and how many after. Splitting a tool's usage between
the old and new spool is arithmetic on numbers already being tracked, not an approximation. Once
the boundary is known, accuracy equals the odometer's own accuracy.

**Detection — don't detect the change; record every pause as a candidate boundary.**

The tempting design is to identify a filament change from a specific signal — `M600` in the stream,
or a particular firmware action command. That is fragile. When the printer's own filament sensor
fires, **the printer initiates `M600` itself and the command never appears in OctoPrint's outgoing
stream**, so there is nothing for the odometer to see. Whether the host hears about it depends on
the firmware emitting an action command, which Prusa historically did not do on runout
([Prusa-Firmware#805](https://github.com/prusa3d/Prusa-Firmware/issues/805)) and which still varies
by model and firmware version.

**A real capture disproved the simple version of this.** A live MMU3 runout/jam was captured from
hardware — see [`tests/fixtures/serial/mmu3-filament-change-runout.md`](../tests/fixtures/serial/mmu3-filament-change-runout.md).
It shows:

- **No `M600` in the outgoing stream.** As predicted.
- **No `// action:` commands whatsoever.** So OctoPrint's native action-command handling never
  fires, and `octoprint.comm.protocol.action` is *not* a usable signal here. This was the mechanism
  an earlier draft leaned on.
- **The outgoing stream simply stops.** The last command before the event is `N2419`; the next is
  `N2448`. In between there are only inbound lines — `echo:busy: processing` repeating while the
  firmware does everything itself. **OctoPrint is blocked on serial flow control, not paused.**
  From its point of view the print is still `Printing`, just slow.

**`PrintPaused` does not fire.** Confirmed by source inspection (Q-7): `PRINT_PAUSED` is emitted
from exactly one place, `printer/standard.py:1395`, reachable by only three routes — a host-side
pause, an `// action:pause`/`paused` command handled in `serial_connector/serial_comm.py`, or a
command matching `pausingCommands`. The capture contains none of them.

**And it is worse than that: `pausingCommands` defaults to `["M0", "M1", "M25"]` — `M600` is not in
the list.** So even a *slicer-emitted* `M600`, sitting plainly in the outgoing stream, does not
pause OctoPrint on a default install. The host keeps streaming while the printer runs its change
sequence.

Two consequences:

1. **Pause-based marking is not a viable primary mechanism.** It works only when the user has
   explicitly added `M600` to `pausingCommands`, or their firmware emits an action command. Neither
   can be assumed.
2. **The plugin should detect and advise.** On startup and at print start, check whether `M600`
   appears in `plugins.serial_connector.pausingCommands`; if not, surface a one-time,
   dismissible hint explaining that OctoPrint will not pause on a filament change and offering to
   add it. This is a genuine OctoPrint configuration gap that bites people well beyond this plugin,
   and it is cheap to point at. **Advise, never edit another plugin's settings silently.**

Note that the plugin's *own* marking does not depend on any of this: `M600` is visible via
`gcode.sent` whether or not OctoPrint chooses to pause on it.

What the capture *does* give is a rich, unambiguous inbound signal:

```
echo:MMU2:Unloading to FINDA        echo:MMU2:Ejecting filament
echo:MMU2:FSENSOR FIL. STUCK        echo:MMU2:FILAMENT EJECTED
echo:MMU2:Parking selector          echo:MMU2:Saving and parking
```

The design therefore widens from "watch for a pause" to **"watch for any evidence the extrusion
timeline was interrupted."** A changeover marker is recorded on *any* of:

| Signal | Source | Covers |
|---|---|---|
| `PrintPaused` / `PrintResumed` events | OctoPrint | host-side pause, user clicking pause, **and `M600` only if the user added it to `pausingCommands`** |
| `M600` / `M601` seen outbound | `octoprint.comm.protocol.gcode.sent` | slicer- or user-issued change — seen regardless of whether OctoPrint pauses |
| `// action:pause` / `paused` | `octoprint.comm.protocol.action` | firmware that does announce itself |
| **`echo:MMU2:` state messages** | **`octoprint.comm.protocol.gcode.received`** (Q-8) | **Prusa MMU — the case that produced this capture** |
| **A prolonged outbound stall while `Printing`** | send-timestamp watchdog | **the universal backstop — no firmware dialect needed** |

The last row is the important one. It requires no vendor-specific parsing: if the print state is
`Printing` and nothing has been sent for longer than a threshold (default ~90 s, configurable) while
inbound traffic continues, something interrupted the job. Record a marker. False positives are
cheap — an unresolved marker changes nothing unless the user acts on it.

> **Record a changeover marker on any interruption signal**, snapshotting the odometer's per-tool
> totals as `{timestamp, source, {tool_index: millimetres}}`.

This is robust by construction across every case that matters, and the cases are broader than MMU:

- a slicer- or user-issued `M600`
- a firmware-initiated runout
- **a deliberate mid-print colour change on a single-extruder printer** — the common "pause at
  layer N, swap filament for lettering or a logo, resume" workflow, whether driven by a slicer
  pause, an `M601`, a pause-at-layer plugin, or the user simply clicking pause
- a user pausing for any other reason and swapping a spool while they are there

**No firmware-specific parsing is load-bearing for correctness**, and the feature is explicitly
*not* MMU-only — a single-tool user doing colour changes benefits from it identically.

**Resolution is a separate, deferrable step.** Because the boundary is already recorded, the user
does not have to answer anything mid-print:

- **On resume**, offer a dismissible prompt: *"Print paused at 14:32 — did you change a spool?"*
  with a per-tool picker.
- **Or at job end, before commit**, present the recorded markers and let the user assign spools to
  each segment retroactively.
- **If the user never answers**, nothing changes: the whole job charges to the originally-assigned
  spools, which is exactly v1 behaviour. **Graceful degradation, never a wrong guess.**

Automatic signals (`M600` seen in the stream, a recognized action command) are then a pure
*accelerator* — they pre-select "yes, a change happened" on the relevant marker instead of being
load-bearing for correctness.

**Practical next step for verification:** OctoPrint's Terminal tab shows the raw `// action:…` line
when a runout fires. Capturing that on the target printer identifies exactly which signal the
firmware sends, which lets 1.1 pre-fill rather than merely ask. Worth doing during v1 development —
it costs one runout and nothing else.

**Two accuracy caveats to document rather than fix:**

- On a genuine runout the outgoing spool physically hit zero *before* the change. The odometer's
  figure for it will slightly overshoot what the spool actually held; Filament DB clamps
  `totalWeight` at 0, so the spool correctly ends empty and the overshoot grams are simply not
  charged anywhere. Correct outcome, worth documenting so it is not later reported as a bug.
- MMU3 handles runout through its own load/unload logic rather than a host-visible `M600`, so the
  MMU case needs separate verification and may only ever support the manual path.

**v1 seams — record in v1, resolve in 1.1.** Two cheap additions to v1 make 1.1 a UI-only change:

1. **The odometer accumulates into a `(tool_index, assignment_id)` key** rather than a bare tool
   index, so charging one tool's usage across two spools within a single job is a shape the
   commit-payload builder already understands.
2. **Pause markers are recorded in v1 even though v1 cannot resolve them.** `PrintPaused` is
   already a handled event and the odometer totals are already in memory — appending
   `{timestamp, {tool: mm}}` to the persisted job state is a handful of lines. The payoff is real:
   if a runout happens on a v1 install, **the data needed to reconstruct the split already exists**
   rather than being lost forever.

   v1 additionally notes pauses in the print-history record (e.g. *"print paused 2× — usage may
   need review"*), so a user who did swap a spool has a visible prompt to correct the record in
   Filament DB by hand.

#### FR-13: Auto-match spools from G-code *(1.2+)*

Fuzzy-match `filament_settings_id` + vendor + type against Filament DB filaments and pre-select per
tool. Explicitly deferred: there is **no stable unique filament ID in standard G-code** — no
Filament DB id, no OpenPrintTag UUID — so this requires a real matcher, which is the hardest part of
`filament-bridge`. Building it twice is the wrong move.

The better path is to close the identity gap upstream: get the OpenPrintTag UUID or Filament DB id
injected into the G-code as a comment (via the `hyiger` PrusaSlicer Filament Edition fork, or via
templated custom filament start-G-code). Then matching is exact and trivial. Worth pursuing in
parallel with v1 implementation.

#### FR-14: NFC-driven spool loading *(future — seams only, not designed here)*

**Not being designed now.** The goal of this section is narrower and specific: confirm that a later
NFC feature is **additive**, and record the small number of v1 decisions that would otherwise force
a redesign.

The shape, in one line: an NFC tag is read when a spool is loaded → the tag resolves to a Filament
DB spool → that spool becomes the loaded spool for a tool. The reader lives on the OctoPrint host;
Prusa printers do not read NFC themselves.

**Filament DB has already built the hard part.** Two purpose-built endpoints, verified live
(C-3), both explicitly intended for cross-origin clients like this one:

- **`POST /api/nfc/decode`** — takes raw tag bytes (OpenPrintTag CBOR, Bambu MIFARE, OpenTag3D),
  decodes them server-side, and returns `{decoded, match, candidates}`. Its docstring states the
  design intent plainly: *"the mobile scanner app's whole job is: read NFC bytes → POST here →
  render the result"*, deliberately centralised so there is one tested decoder instead of drifting
  duplicates. A plugin doing NFC should reuse it rather than decode anything itself.
- **`GET /api/filaments/match?instanceId=…`** — resolves an identifier with a documented tier
  order: `instanceId → name → vendor+type → vendor`.

**How much identity a scan actually yields depends on who wrote the tag:**

| Tag | Result |
|---|---|
| **Written by Filament DB** — its `spoolUid` carries an FDB instance id | **Exact spool identity.** `matchFilament` hits the spool-level tier (#732) and returns `matchedSpool: {_id, instanceId, label}` alongside the filament, with `matchedBy: "instanceId"`. Verified live: querying a real spool's `instanceId` returned that exact spool. That is precisely the `(filamentId, spoolId)` pair the plugin needs — nothing further required. |
| **Third-party / vendor OpenPrintTag** | **Filament-level only.** A vendor `spoolUid` will not collide with an FDB instance id, so matching falls through to the heuristic tiers and returns `matchedSpool: null`, `matchedBy: "heuristic"`. You learn *which filament*, not *which physical spool* — so with multiple spools of that filament, the plugin must pick or ask. |

**Why this is additive.** Assignment is the only thing NFC changes, and v1 already funnels every
assignment through one internal choke point — `assignment.set(tool, spool)` / `assignment.clear`
(FR-11). NFC becomes another caller. Metering, conversion, commit and the journal are untouched.

**The v1 decisions that keep it additive:**

| v1 decision | Why NFC needs it |
|---|---|
| **Assignment records carry a `source`** — `manual` in v1 | Distinguishes a hand-picked assignment from an NFC-driven one in the journal and UI, and stops the two silently overwriting each other. One enum field. |
| **The choke point is callable from a background thread**, pushing a UI update via `send_plugin_message` | NFC events arrive asynchronously, not from a UI click. v1 already needs async→UI push for live metered grams, so this is free — but an assignment path written as a request handler only would need rewriting. |
| **The odometer keys on `(tool_index, assignment_id)`**, not bare tool index (already specified, FR-12) | An NFC insert *during* a print is a spool change, and should produce a changeover marker like FR-12's other triggers. That structure already supports splitting one tool's usage across two spools. |

**Deliberately left open** — design questions for that version, not now: reader hardware; whether to
read tags on the OctoPrint host or subscribe to Filament DB's `GET /api/scan/stream`; what to do
with a heuristic-only match on a multi-spool filament; and whether a scan auto-assigns or
pre-selects for confirmation.

---

### Known plugin interactions

#### `Octoprint-PrusaMMU` — *coexistence deferred, but the facts are recorded*

[`jukebox42/Octoprint-PrusaMMU`](https://github.com/jukebox42/Octoprint-PrusaMMU) runs on the
maintainer's Core One + MMU, i.e. **the primary hardware test rig**. Coexistence design is deferred,
but three things are verified from its source and matter now.

**1. What it does to the command stream — corrects an earlier claim in this document.** An earlier
draft said it *suppresses* `Tx`, so the odometer would miss tool changes. It does both, and the
distinction matters:

| Behaviour | Mechanism | Effect on metering |
|---|---|---|
| **Remaps** `T<n>` → `T<mapped>` when filament mapping is on, and on MK4 single-filament override | returns a replacement command | `gcode.sent` still fires — the odometer sees the **remapped**, i.e. **physically correct**, tool. **Benign, arguably desirable.** |
| **Suppresses** the literal `Tx` placeholder while prompting the user | `return None,` + `set_job_on_hold(True)` | that one command never reaches `gcode.sent`; the real tool command follows after the user chooses |
| **Rewrites `M109 S`** into `[(cmd,), (T<n>,)]` | appends a tool command | an extra tool command the odometer will see |

So the net effect on **totals is nil**, and on **attribution it is mostly self-correcting**: the
odometer follows the physical tool, which is what the spool assignment is about. The real casualty
is the FR-3 cross-check against the slicer's per-extruder array, which is indexed by the *file's*
tool numbers and will legitimately disagree under remapping.

**2. It publishes events for exactly this purpose.** It registers custom events via
`octoprint.events.register_custom_events`, and `plugin_prusammu_mmu_changed` carries a source comment
saying it exists *for other plugins*:

```
plugin_prusammu_mmu_change     plugin_prusammu_show_prompt
plugin_prusammu_mmu_changed    plugin_prusammu_refresh_nav
```

**This is a better MMU signal than parsing `echo:MMU2:` ourselves** (FR-12) — it is a supported
interface rather than reverse-engineered firmware chatter, and it also reveals when remapping is
active. Consuming it should be preferred if the plugin is installed, with our own parsing as the
fallback when it is not.

**3. It already integrates with spool inventory — which is the actual overlap.** It detects the
`Spoolman` and `SpoolManager` plugins by identifier and adds them to a `FILAMENT_SOURCES` setting.
So it has a filament-source concept, and **both plugins would want to own "which spool is in slot
N."** That is the coexistence problem to solve, and it is a product question, not a technical one:

- The source list appears to be **hardcoded detection**, not a registration hook, so becoming a
  recognised "Filament DB" source likely needs an upstream PR rather than anything we can plug into.
- Alternatives are to stay independent (two UIs, two sources of truth — poor), or to read its
  selection and treat it as the authority for *which slot*, while we own the Filament-DB spool
  identity behind it.

**Deferred deliberately.** Nothing in v1 depends on resolving this: v1's slot assignment is
self-contained and works whether or not PrusaMMU is installed. Revisit before any MMU-focused
release, and talk to both upstreams — the Filament DB author already knows about this plugin.

### Explicit non-goals for v1

- Any Spoolman or `filament-bridge` dependency.
- Real-time incremental usage commits during a print.
- Embedding the Filament DB web UI in an OctoPrint tab via iframe (suggested in #1039). It sounds
  cheap and isn't: Filament DB sets frame-ancestor headers, mixed-content rules bite on HTTPS
  OctoPrint instances, and the auth story for an iframed app with a bearer key is unpleasant.
  v1 uses deep links that open in a new tab.
- NFC / RFID spool identification at the printer.
- Writing anything to Filament DB other than print-history records.
- Filament DB → OctoPrint direction (e.g. FDB telling OctoPrint what is loaded).
- OctoPrint 1.x support.

---

## Development environment

### Topology

```
┌──────────────────────────────┐     ┌────────────────────────────────┐
│ octoprint (docker)           │     │ filament-db (existing dev)     │
│  OctoPrint 2.0.0rc4+         │────▶│  from filament-bridge work     │
│  virtual printer, 5 tools    │     │  Next.js + MongoDB             │
│  plugin bind-mounted, -e     │     └────────────────────────────────┘
└──────────────────────────────┘
```

The Filament DB side is **already running** from the `filament-bridge` dev environment at
`http://crzydev.home.arpa:3000` and is reused as-is rather than standing up a second instance.

**Scale as of 2026-08-01: 45 filaments / 36 spools**, of which 33 are variants — good coverage of
the parent/variant model, though still well short of the production instance for picker-performance
work.

**It does not exercise the FR-6 density fallback**, and that gap is subtler than a record count.
Every filament returns a non-null density — but for variants that is the *inherited* value, since
both projections resolve `own ?? parent` (C-4). To reach the fallback you need a **root** filament
(no `parentId`) with `density: null`; a null-density *variant* will silently inherit and never
exercise the path. Seed that specific shape before calling FR-6 verified.

All mutable state lives in `private_data/` (gitignored in full) — the OctoPrint volume, scratch
G-code, keys, notes. Committed test data goes in `tests/fixtures/` instead. Same convention as
`filament-bridge`.

### `docker-compose.dev.yml` requirements

- **We build our own image — no official one ships OctoPrint 2.0** (Q-2, resolved). `Dockerfile.dev`
  layers the PyPI RC onto `octoprint/octoprint:latest`.

  **Build-time gotcha, already handled:** the base image sets `PIP_USER=true` with
  `PYTHONUSERBASE=/octoprint/plugins`, and `/octoprint` is a `VOLUME`. A plain `pip install` lands
  in the volume and is **shadowed the moment the bind mount attaches at runtime** — the container
  silently keeps running 1.11.x. The Dockerfile forces `PIP_USER=false` and then asserts
  `octoprint.__version__` starts with `2.`, so a failed upgrade breaks the build instead of wasting
  an afternoon.
- Plugin source **bind-mounted and installed editable** (`pip install -e /plugin`) so a container
  restart picks up Python changes; static JS/CSS changes need only a browser reload. The editable
  install is commented out in `Dockerfile.dev` until `pyproject.toml` exists.
- Seeded `config.yaml` so the container comes up connected, with no click-through wizard:

  ```yaml
  plugins:
    virtual_printer:
      enabled: true
      numExtruders: 1        # phase 1 — single tool; raise to 5 for phase 3
      hasBed: true
    _disabled: [softwareupdate]
  ```

  **Testing is staged, one new variable per phase** (see the README's Testing workflow for the full
  table): **1.** clean instance, no third-party plugins, single extruder — the core loop;
  **2.** real single-tool hardware; **3.** MMU (`mmu5` profile, then the real Core One + MMU);
  **4.** plugin coexistence, notably `Octoprint-PrusaMMU`.

  Most of the documented risk — per-tool attribution, tool remapping, `echo:MMU2:` parsing — is
  phase 3+. The phase-1 loop is one tool, one spool, one accumulator, which keeps that complexity
  off the critical path. Single-extruder is also the majority real-world case.

  **Confirmed against a live 2.0.0rc4 container (Q-3).** Despite 2.0 moving serial handling into the
  bundled `serial_connector` plugin, `virtual_printer` remains a separate bundled plugin with the
  same settings key and the same `numExtruders` / `hasBed` options, registering port `VIRTUAL`
  through a serial factory. The snippet above is correct as written.
- The single-extruder `_default` profile is the phase-1 default; an `mmu5` profile
  (5 tools, shared nozzle) ships alongside it for phase 3.
- **The bundled Software Update plugin must be disabled** (`plugins._disabled: [softwareupdate]`).
  OctoPrint ranks 1.11.8 as the latest *stable* and 2.0.0rc4 as a prerelease, so the updater offers
  a **downgrade off the target version**, which silently destroys the dev environment. Belt and
  braces: `plugins.softwareupdate.checks.octoprint.prerelease_channel: rc/devel` so a re-enabled
  updater still tracks RCs rather than stable.

  The image is the single source of truth for the OctoPrint version. An in-container `pip install`
  writes to `site-packages`, which is **not** in the mounted volume, so it is silently discarded
  when the container is recreated — a version bump means editing the `OCTOPRINT_VERSION` build arg
  and rebuilding, never updating from inside.
- Credentials for the dev instance live in `private_data/dev-credentials.md` (gitignored), never in
  the repo.

### Test G-code fixtures

Committed under `tests/fixtures/gcode/`, kept small (a few layers each, truncated with the config
block preserved):

| Fixture | Exercises |
|---|---|
| PrusaSlicer, single tool | baseline; config block with type + grams |
| PrusaSlicer, 5-tool MMU | per-extruder arrays, `T<n>` changes, shared nozzle |
| **Real MMU3 runout capture** (`serial/mmu3-filament-change-runout.md`) | **real hardware** — relative-E validation against firmware `M114`, arc extrusion, `G92` reset, the `echo:MMU2:` message sequence, and the outbound stall. Prefer this over synthetic data for FR-5 and FR-12 tests. |
| OrcaSlicer | config-block dialect differences |
| Cura | **no** `filament_type` — the skipped-check path |
| Arc-heavy (`G2`/`G3`) | odometer arc handling |
| Relative-E (`M83`) + `G92` resets | odometer state machine |

### Test strategy

- **Unit** — odometer (fixture-driven, the heaviest suite), mm→g conversion incl. the density
  fallback chain, slicer config-block parser per dialect, commit-payload builder (dedupe, drop
  unassigned, skip-when-zero, field limits).

  **The density fallback needs a deliberate fixture.** It is only reachable via a *root* filament
  with `density: null` — a null-density variant inherits from its parent and never reaches it
  (C-4). Left to real data it would never run, and the branch would rot untested.
- **Integration** — FDB client against a mocked HTTP layer, covering: bearer auth, 401, network
  failure, and the exact `POST /api/print-history` payload shape.
**Hardware scope.** Real-hardware verification is done on the **Prusa ecosystem** (MK-series +
MMU3, PrusaSlicer) — the maintainer's platform. The core metering logic is printer-agnostic by
construction (counting E-moves is a property of G-code, not of a vendor), so other firmwares should
behave identically, but they are **untested and will not be claimed as tested**. The genuinely
Prusa-specific piece is `echo:MMU2:` message parsing — which is exactly why FR-12's primary
detection signal is a vendor-neutral stall watchdog rather than message parsing. See the README's
Testing workflow section for the per-area breakdown.

- **Manual/E2E** — against the real dev Filament DB: print a fixture on the virtual printer, verify
  the print-history record and the spool debit; cancel mid-print and verify partial grams; kill the
  Filament DB container mid-print and verify the commit queue recovers; **run the over-usage case**
  (a job needing more than the spool's recorded net) and verify the spool displays 0, the full
  grams were committed uncapped, and the overshoot notice fires.
- **CI** — lint (`ruff`), unit tests, and `octoscanner` for OctoPrint 2.0 deprecation scanning.

---

## Standards & operating model

This project adopts two internal engineering standards. See [`standards.md`](../standards.md) at
the repo root for the pinned versions and the links to their definitions.

| Standard | Version | Notes |
|---|---|---|
| `handoff-prompt-workflow` | 2.0.0 | Adopted at project start |
| `release-prep-and-cut` | 1.1.0 | Adopted at project start |

**Operating model.** A central **Opus** planning session owns the design, writes handoff prompts for
each feature and bug fix into `prompts/`, and spawns subagents to execute them (Opus for
research/planning prompts, Sonnet for coding prompts). Completed prompts self-update their
frontmatter and `git mv` into `prompts/done/` or `prompts/failed/`. Ask-before-commit applies — the
standard's default, no auto-commit deviation.

**Open item — branch strategy.** `release-prep-and-cut` explicitly *composes with*
`code-checkin-and-pr` and assumes its `dev` → protected-`main` PR flow is in place. That standard
is **not adopted here**, so `/release-prep` has no defined branch strategy to run against. Two ways
to resolve: adopt `code-checkin-and-pr @ 1.2.0` as well (what `filament-bridge` and `partfolder3d`
both do), or record the deviation and define a minimal branch rule directly in this repo's
`standards.md`. Needs a decision before the first release, not before the first commit.

---

## Open questions

**All resolved as of 2026-08-01**, against a live OctoPrint 2.0.0rc4 container, a live Filament DB
dev instance, and the upstream sources. Kept here as the answer record rather than deleted.

| # | Question | Blocks | Resolution path |
|---|---|---|---|
| ~~Q-1~~ | ~~Does `GET /api/filaments` (list projection) include `diameter`?~~ **RESOLVED: no.** Verified against the live instance — the list projection carries `density` but **not** `diameter`; the detail projection (`GET /api/filaments/:id`) has both. So the mm→g conversion must fetch detail for *assigned* filaments only, exactly as FR-6 specifies. | — | Done |
| ~~Q-2~~ | ~~What image tag publishes OctoPrint 2.0 RCs?~~ **RESOLVED 2026-08-01: none does.** `octoprint/octoprint:latest` and `:edge` both pin `octoprint_ref=1.11.8`; `:canary` tracks the `maintenance` branch (still 1.x). The 2.0 RCs are on PyPI (rc1–rc4), so `Dockerfile.dev` layers the RC onto the official image. | — | Done |
| ~~Q-3~~ | ~~Is the virtual printer still at `plugins.virtual_printer.*` in 2.0?~~ **RESOLVED 2026-08-01: yes, unchanged.** Verified on a live 2.0.0rc4 container — `virtual_printer` is still a bundled plugin alongside the new `serial_connector`, still keyed `plugins.virtual_printer.*` with `enabled` / `numExtruders` / `hasBed`, still on port `VIRTUAL` via a serial factory. | — | Done |
| ~~Q-4~~ | ~~Does OctoPrint 2.0 introduce a new tool abstraction?~~ **RESOLVED: no — the model is unchanged.** `printer/profile.py` still defines `extruder.{count, offsets, nozzleDiameter, sharedNozzle, defaultExtrusionLength}`, defaults `count: 1` / `sharedNozzle: False`, validated `0 < count < 100`. FR-3's model holds as written. | — | Done |
| ~~Q-5~~ | ~~Exact value of `MAX_USAGE_GRAMS`?~~ **RESOLVED: `1_000_000` g (1 tonne)**, with `MAX_SPOOL_HISTORY = 1000`. It is an overflow backstop, not a unit check — ~50× the largest FDM spool sold. **No practical constraint on a print job**; validate against it anyway, but it will never fire legitimately. | — | Done |
| ~~Q-6~~ | ~~Does `POST /api/print-history` require `spoolId`?~~ **RESOLVED: it is optional — and that is exactly why we must always send it.** Omitting it makes Filament DB pick `first non-retired spool with totalWeight > 0`, falling back to `first non-retired spool`. That is an implicit choice the user never made. Always send `spoolId` explicitly. | — | Done |
| ~~Q-7~~ | ~~Does OctoPrint fire `PrintPaused` during a firmware-driven MMU change?~~ **RESOLVED by source inspection: no.** `PRINT_PAUSED` fires from exactly one place (`printer/standard.py:1395`), reachable only via a host-side pause, an `// action:pause`/`paused` command, or a command in `pausingCommands`. The capture has none of the three. **See the `pausingCommands` finding below — it is worse than expected.** | — | Done (hardware confirmation still welcome) |
| ~~Q-8~~ | ~~Which hook exposes received lines?~~ **RESOLVED: `octoprint.comm.protocol.gcode.received`**, present in 2.0. Also available: `.queuing` / `.queued` / `.sending` / `.sent` / `.error`, `octoprint.comm.protocol.action`, `.atcommand.*`, `.firmware.*`, `.temperatures.received`. | — | Done |
| ~~Q-9~~ | ~~How does a pre-print check actually stop a print?~~ **RESOLVED: frontend wrap.** `octoprint-spoolman` replaces `printerStateViewModel.print` (**and** `loadAndPrint`) with a function that shows a modal and calls the original only on confirm. A backend gate cannot work — `PrintStarted` fires after the job begins. **UX gate only:** REST-API-started prints bypass it, so backend checks and commit must not depend on the dialog having run. | — | Done |

## Upstream asks (file as issues)

1. **`hyiger/filament-db`** — add `"octoprint"` to the print-history `source` enum (C-5).
2. **`hyiger/filament-db`** — accept a client-supplied idempotency key or job UUID on
   `POST /api/print-history` so a retry after an ambiguous timeout cannot double-debit (FR-9).
3. **`hyiger/filament-db` #1039** — post this design to the thread. It answers the OP's feature
   list, and the metering/`G2`/`G3` point in it is a genuinely good catch worth crediting.
4. **`hyiger/PrusaSlicer` (Filament Edition fork)** — inject the OpenPrintTag UUID or Filament DB id
   into the G-code config block, which would make FR-13 exact instead of fuzzy.
5. **`hyiger/filament-db`** — on over-usage, floor `spool.totalWeight` at the filament's
   `spoolWeight` (tare) rather than at 0, when the tare is known. Today an over-debit can leave a
   stored **gross** weight below what the empty reel physically weighs (FR-7 §Over-usage). Display
   is unaffected because `spool-check` re-clamps the derived net at 0, so this is low severity —
   but the stored field becomes physically impossible, and `spoolWeight` is nullable so the fallback
   to 0 still needs to exist.

## Success criteria for v1

1. A print on a single-tool printer debits the correct spool in Filament DB, within ~1% of the
   slicer's reported gram figure, and appears in Filament DB's print history under the job name.
2. A print cancelled at 40% records roughly 40% of the filament, not 0% and not 100%.
3. A 5-tool MMU print produces one print-history record with a correct per-spool usage breakdown.
4. A Cura-sliced print meters correctly and clearly reports that the material-type check was skipped.
5. Filament DB being unreachable at job end loses no usage — the retry queue recovers it.
6. **The plugin never fails silently.** Every write attempt is visible in the history UI with its
   outcome, and a failure the user has not resolved is impossible to miss: it carries a reason, a
   retry action, and a persistent badge. A user can always answer "did my last print get recorded,
   and if not, why?" without reading a log file.
7. The plugin installs and runs clean on OctoPrint 2.0 with no deprecation warnings
   (`octoscanner` clean).

---

## Sources

- [OctoPrint 2.0.0 plugin migration guide](https://docs.octoprint.org/en/dev/plugins/migration_2_0_0.html)
- [OctoPrint 2.0 hooks reference](https://docs.octoprint.org/en/dev/plugins/hooks.html)
- [OctoPrint virtual printer docs](https://docs.octoprint.org/en/dev/development/virtual_printer.html)
- [OctoPrint 2.0.0 is coming soon](https://octoprint.org/blog/2026/04/20/octoprint-2.0.0-is-coming-soon/) · [rc3](https://octoprint.org/blog/2026/06/23/new-release-candidate-2.0.0rc3/)
- [octoscanner](https://github.com/jacopotediosi/octoscanner)
- [mdziekon/octoprint-spoolman](https://github.com/mdziekon/octoprint-spoolman) · [plugin page](https://plugins.octoprint.org/plugins/Spoolman/)
- [jukebox42/Octoprint-PrusaMMU](https://github.com/jukebox42/Octoprint-PrusaMMU) — `Tx` interception, `MMU2:` firmware-message parsing (FR-3)
- [Prusa KB — OctoPrint configuration](https://help.prusa3d.com/article/octoprint-configuration-and-install_2182) — MMU needs Number of extruders = 5 + Shared nozzle, set manually (FR-3)
- [Prusa-Firmware#805](https://github.com/prusa3d/Prusa-Firmware/issues/805) — `// action:pause` not emitted on filament runout (FR-12)
- [filament-db API docs](https://github.com/hyiger/filament-db/blob/main/docs/api.md) · `src/app/api/print-history/route.ts` · `src/models/Filament.ts`
- [filament-db#1039 — OctoPrint plugin request](https://github.com/hyiger/filament-db/issues/1039)
- [Cura: add material used to G-code (declined)](https://github.com/Ultimaker/Cura/issues/10223)
- `filament-bridge` — `docs/upstream-apis.md`, `backend/app/services/filamentdb.py`
