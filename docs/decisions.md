# Decisions

ADR-style record of non-obvious decisions — approach changes, rejected alternatives, and
workarounds. Newest at top. Add an entry whenever a session makes a call that a future
reader would otherwise have to re-derive.

---

## 2026-08-01 — Tool count cannot come from the printer profile alone (FR-3 corrected)

The first draft of FR-3 derived the number of tool slots from
`printer_profile["extruder"]["count"]`, reasoning that OctoPrint already knows it. Validation
showed that is unsafe:

- **The MMU tool count is manual user configuration.** OctoPrint knows an MMU3 has 5 tools only
  because the user set Number of extruders = 5 and ticked Shared nozzle. Prusa's own docs instruct
  this; nothing enforces or detects it.
- **`Octoprint-PrusaMMU` does not set it either.** That plugin works at the G-code and
  firmware-message level (`Tx` interception, `MMU2:` response parsing) and never touches the
  profile. So a fully working MMU setup can report `extruder.count = 1` while the G-code drives
  `T0`–`T4`.

Rendering one slot for a five-tool file would charge five tools' filament to one spool — data
corruption, not a UI annoyance. Slot count is therefore the **union** of the profile count, the
tool indices in OctoPrint's analysis metadata, and the slicer block's per-extruder array length,
with a prominent warning when the G-code exceeds the profile.

**Second finding from the same validation:** a plugin can suppress a command at
`octoprint.comm.protocol.gcode.queuing` (return `None,`), and a suppressed command **never reaches
`gcode.sent`**. `Octoprint-PrusaMMU` does exactly this to `Tx`. An odometer inferring the active
tool solely from observed `Tx` can therefore mis-attribute. Mitigation: track the active tool
defensively against OctoPrint's own state, and cross-check the per-tool split at commit time
against the slicer's per-extruder `filament used [mm]` array — if the total agrees but the split
does not, warn instead of writing a confidently wrong attribution.

## 2026-08-01 — A real MMU3 capture disproved the "every pause is a marker" assumption

A live serial capture of an MMU3 runout/jam was taken from hardware and committed as
`tests/fixtures/serial/mmu3-filament-change-runout.md`. It **contradicted the preceding decision**
(one entry below), which assumed the print would end up paused and `PrintPaused` would fire.

What the capture actually shows:

- **No `M600`** in the outgoing stream — as predicted.
- **No `// action:` commands at all** — so `octoprint.comm.protocol.action` is not a usable signal.
  That was the mechanism the previous decision leaned on.
- **The outgoing stream just stops.** Last command `N2419`, next command `N2448`, with only
  `echo:busy: processing` inbound in between. **OctoPrint is blocked on serial flow control, not
  paused** — from its perspective the print is still `Printing`.

So `PrintPaused` cannot be assumed to fire (now Q-7, unverified). The design widens from "watch for
a pause" to **"watch for any evidence the extrusion timeline was interrupted"**, with five signals,
of which the important one is vendor-neutral: **a prolonged outbound stall while the state is
`Printing`** while inbound traffic continues. No firmware dialect needed. `echo:MMU2:` message
parsing is added as a strong Prusa-specific signal. False-positive markers are cheap — an
unresolved marker changes nothing unless the user acts on it.

**Two further findings from the same capture:**

1. **The odometer model is validated against real firmware.** Between `G92 E0.0` (N2386) and `M114`
   (N2406) the relative-E sum — including a `G92` reset and a retract/prime pair netting to zero —
   is **4.05109 mm**, and the firmware replies `E:4.05`. Exact match. This becomes a unit-test
   assertion grounded in hardware rather than invented data.
2. **Firmware extrudes without the host seeing it.** During the MMU sequence the extruder position
   moves **4.05 → 9.67 mm (+5.62 mm)** with no host-issued command. The odometer structurally
   cannot observe this. Mass impact is negligible here (~0.017 g) but the error is **systematic and
   always an under-count**, and a full tool change with firmware-side ramming would be larger. v1
   accepts and documents it; reconciling against firmware position reports is noted as a later
   mitigation, not v1 scope.

**Process note:** this is the second design assumption in FR-12 overturned by evidence rather than
reasoning. Detection of physical events should be treated as unverified until a capture proves it,
and the vendor-neutral backstop should always be the primary path.

## 2026-08-01 — AGPLv3, and a clean-room implementation

**Licence: AGPLv3.** Matches the ecosystem — OctoPrint itself and `mdziekon/octoprint-spoolman`
are both AGPLv3 — so the plugin is licence-compatible with everything it sits next to, and the
network-use clause is appropriate for something that runs as a self-hosted web-facing service.

**All code is original. Nothing is copied from `octoprint-spoolman` or any other plugin.** The
licences are compatible, so this is an engineering decision rather than a legal one:

- Almost nothing would transfer. Filament DB uses grams (not millimetres), a gross weight model,
  spools embedded on filaments, and one transactional print-history write that debits weight
  itself. Every layer below metering differs.
- The odometer specifically must be original. `octoprint-spoolman` vendors OctoPrint's
  `gcodeInterpreter`, which is designed for static file analysis. This plugin needs a live,
  per-tool, pause-aware accumulator that handles `G2`/`G3` arcs (FR-5) — precisely the gap raised
  in filament-db#1039 — plus pause markers (FR-12). Adapting the vendored interpreter would be
  more work than writing the state machine, and harder to test.

Studying prior art to understand a problem is fine and is cited where done; copying source is not.
Recorded because "why didn't we just reuse the Spoolman plugin's odometer?" is an obvious future
question.

## 2026-08-01 — The write journal is a P0 differentiator, and it replaces the separate commit queue

Promoted from a sub-bullet of FR-9 to its own requirement (FR-9b). The motivating observation: the
common complaint about comparable integrations, the Spoolman OctoPrint plugin included, is that
they don't tell you what they did. **A tracker that fails silently is worse than no tracker**, because
you trust your inventory while it is quietly wrong. Observability is therefore a feature, not
instrumentation.

**Every write attempt is recorded — successes too, not just failures.** Successes answer the other
half of the trust question ("did my print actually get recorded?").

**Structural consequence: there is no separate pending-commit store.** An earlier draft had
`commit_queue.py` persisting in-flight commits *and* a job log. Those are the same data — "the
queue" is just a query over journal rows in a retryable state. Two stores would be two sources of
truth for one fact and would drift. Merged into `journal.py` (durable store) + `retry.py` (retry
policy over it).

**Storage: SQLite via stdlib `sqlite3`**, not an append-only JSONL file. Rows are *mutated*
(attempt counts, state transitions, user resolution) and need querying and pagination; JSONL would
require compaction and drift. No new dependency either way.

**A six-state machine, because "failed" is not one thing.** `failed_retryable` (pre-write — auto
retry), `failed_ambiguous` (timeout after send — **never** auto-retry, double-debit risk given the
missing idempotency key), `failed_permanent` (4xx — will fail identically), plus `resolved_manually`
and `discarded` for user outcomes. Collapsing these into one "failed" state would either lose usage
or double-debit.

**Two rules that exist to prevent recreating the problem:**

- **Retention never prunes an unresolved failure.** Only `committed` / `resolved_manually` /
  `discarded` rows are eligible. Auto-deleting a failure the user hasn't dealt with would be silent
  failure by another name.
- **Deliberate nagging.** A tab badge and a persistent sidebar warning while unresolved failures
  exist, cleared only by explicit user resolution.

`resolved_manually` is deliberately distinct from `committed` — the plugin must never claim it wrote
something a human actually did by hand.

## 2026-08-01 — Over-usage commits the full grams uncapped; the spool reaching 0 is native behaviour

Scenario raised as a real case: a job needs 25 g, Filament DB shows 24 g remaining, and the print
succeeds — because the stored weight is an **estimate** that drifts (spools rarely reweighed, tare
values nominal, manufacturers overfill).

Verified against `spool-check/route.ts`: the displayed "remaining" is **net and derived**, not
stored — `remainingWeight = spool.totalWeight − filament.spoolWeight`. So with a 200 g tare, a
displayed 24 g means a stored gross of 224 g. Debiting 25 g gives `max(0, 224 − 25) = 199 g`, and
the displayed net becomes `max(0, 199 − 200) = 0`. **The desired "spool shows empty" outcome
happens natively — no special handling needed to produce it.**

Decisions:

- **Commit the full metered grams; never cap at the spool's recorded remaining.** The record must
  state what was physically extruded. Capping at 24 g would understate consumption, corrupt the
  material-cost picture, and destroy the only signal that the stored weight was wrong.
- **Surface the overshoot** — it's actionable ("recorded weight was low; reweigh or retire").
- **Don't auto-retire.** A spool reading 0 may still have usable filament; that's a user call.
- **Don't spill the excess onto another spool.** The filament came off this one.

Known upstream wart, documented not worked around: the clamp floors the **gross** at 0 rather than
at the tare, so the stored `totalWeight` ends 1 g below an empty reel. Display is unaffected
(`spool-check` re-clamps net at 0). v1 deliberately does **not** issue a corrective `PUT` to set
`totalWeight = tare` — that would be a second, non-transactional write outside the C-1 single-write
rule, and a partial failure between the two writes is worse than the wart. Filed upstream instead.

**Two knock-on changes.** The sufficiency check (FR-4) now uses Filament DB's own `spool-check`
endpoint rather than computing net locally — it already resolves **variant tare inheritance**
(variants store `spoolWeight: null` and inherit from the parent, so reading the field directly
returns null and silently skips the check), plus retired-spool and null-tare guards, and returns a
ready-made warning string. And this case is precisely why **block mode stays off by default**:
"not enough filament" is frequently wrong in the user's favour.

## 2026-08-01 — Round grams at two boundaries only: 3 dp on the wire, 2 dp in the UI

Precision was unspecified in the first PRD draft. Settled as:

- **Never round an intermediate value.** The odometer accumulates millimetres at full float
  precision and converts to grams **once**, at commit, on the final per-tool total. Rounding per
  G-code command and then summing would accumulate error across the hundreds of thousands of moves
  in a real print — a correctness bug, not a cosmetic one. This is the rule that actually matters.
- **Wire: 3 dp.** ≈ 1 mm of 1.75 mm filament.
- **UI: 2 dp.** 0.01 g ≈ 3 mm.

Rounding on the wire rather than sending the raw float was a deliberate call. Physical accuracy is
nowhere near float precision — diameter tolerance alone is ~±0.02 mm on 1.75 mm stock (±2–3 % on
volume) and Filament DB densities carry 2–3 significant figures — so `12.399999999999999` claims
precision the system does not have, and it lands in stored `totalWeight` and usage history where a
user reads it. The cost is ≤0.0005 g per entry, unbiased, ~0.00005 % of a 1 kg spool.

Two edge cases specified at the same time, both real failure modes rather than theory:

- **Clamp each usage entry at 0.** A negative `grams` is rejected by Filament DB with a `400`, and
  because the payload is one transactional request that single bad entry would fail the commit for
  **every** tool and lose the whole job's usage. Log when a clamp fires — it indicates an odometer
  state bug.
- **`-0.0` must serialize as `0`.**

## 2026-08-01 — Treat every pause as a changeover marker; don't try to detect filament changes (FR-12)

Separating the two halves of the problem changed the design:

- **Metering is exact.** The odometer knows the millimetres before and after a changeover boundary;
  splitting usage is arithmetic, not estimation.
- **Detecting *why* the print stopped is not.** On a runout the printer initiates `M600` itself, so
  the command never appears in OctoPrint's outgoing stream. Whether the host hears about it depends
  on the firmware emitting an action command — Prusa historically did not on runout
  (Prusa-Firmware#805), and behaviour still varies by model and firmware.

An intermediate draft concluded from this that the feature had to be manual-first, with a UI action
as the primary path. **That was superseded by a user observation:** a real runout *does* produce a
host-visible popup in OctoPrint. OctoPrint natively handles `// action:pause` / `// action:paused`
(pausing the print itself), and the bundled Action Command Prompt / Notification plugins render
firmware dialogs.

The insight that follows is that **the plugin never needs to identify a filament change at all.**
Whatever the firmware dialect, the print ends up paused and `PrintPaused` fires. So:

> Every pause is a candidate changeover boundary. On `PrintPaused`, snapshot the odometer's
> per-tool totals and record a marker.

This is robust by construction — slicer `M600`, firmware runout, and a user manually pausing to
swap a spool all produce a pause and therefore a marker, with no firmware-specific parsing needed
for correctness. Resolution then becomes a separate, **deferrable** step: prompt on resume, or
reconcile retroactively at job end, and if the user never answers, the whole job charges to the
originally-assigned spools (v1 behaviour). Automatic signals demote to a pure accelerator that
pre-selects a marker rather than being load-bearing.

**Consequence for v1:** record markers even though v1 cannot resolve them. `PrintPaused` is already
handled and the totals are already in memory, so it is a handful of lines — and it means a runout
on a v1 install leaves the data to reconstruct the split rather than losing it forever.

Documented-not-fixed: on a real runout the outgoing spool hit zero before the change, so its
odometer figure slightly overshoots; Filament DB clamps at 0, the spool correctly ends empty, and
the overshoot is charged nowhere. MMU3 handles runout through its own load/unload logic and needs
separate verification.

## 2026-08-01 — Treat agent navigability as an architectural constraint, not a style preference

This codebase is built primarily by AI sessions with a fresh context each time, so **the cost of
a change is dominated by how much must be read before it can safely be edited.** That makes
navigability a first-class design constraint, written into the PRD (rules N-1…N-10) so it governs
design reviews rather than being retrofitted by an audit later.

The concrete motivator: `filament-bridge`'s `core/engine.py` carries line references past 4,200.
Changing twenty lines there means loading four thousand into context first. That project ran a
dedicated Claude-token-efficiency audit track in v0.6.11 to claw some of it back; doing it up front
is far cheaper.

The two rules doing most of the work:

- **Strict layering with an import-direction test** (N-3). `metering/` and `client/` import
  nothing internal, and `metering/` may never import `client/`. This converts a guideline into a
  *guarantee*: a G-code metering bug cannot require reading the API client, so an agent can
  correctly ignore it. A test asserts the directions so the property can't erode.
- **A task→file routing table in `CLAUDE.md`** (N-8), updated in the same commit as any structural
  change. Highest-leverage item on the list — it turns "search the repo" into "read two files."

The 500-line hard cap (N-1) is deliberately aggressive and will occasionally feel like it forces a
split earlier than a human-only project would want. That is the intended trade.

## 2026-08-01 — Adopt only two standards at project start

`handoff-prompt-workflow @ 2.0.0` and `release-prep-and-cut @ 1.1.0`. `code-checkin-and-pr`
was deliberately left unadopted for now, which leaves the branch strategy undefined — see
the open item in `standards.md`. Recorded because `release-prep-and-cut` composes with it,
so this is a knowingly incomplete pairing rather than an oversight.

## 2026-08-01 — Commit usage via `POST /api/print-history` only, never the per-spool usage endpoint

Reading `hyiger/filament-db` `src/app/api/print-history/route.ts` showed that endpoint
already debits `spool.totalWeight`, appends a `usageHistory` entry tagged `source: "job"`,
and creates the `PrintHistory` document — all in one MongoDB transaction with rollback.

Calling `POST /api/filaments/:id/spools/:spoolId/usage` in addition would double-debit every
print. The per-spool usage endpoint is reserved for manual weight corrections and is out of
scope for this plugin.

Bonus property: `DELETE /api/print-history/:id` refunds the spool weight atomically, so a
mis-assigned job can be undone entirely from the Filament DB UI.

## 2026-08-01 — Meter extrusion with a software odometer, not slicer totals or progress-scaling

Three options were weighed for "how many grams did this print actually use":

1. **Slicer's `filament used [g]` from the G-code config block** — rejected. Slicer-specific
   (Cura emits no grams), and produces nothing usable on a cancelled print, which is a
   primary requirement.
2. **Scale the slicer/analysis total by OctoPrint's progress fraction** — rejected. Progress
   is `filepos`-based and G-code density per byte is highly non-uniform, so error on a cancel
   is easily ±30%.
3. **Software odometer on actual E-moves via `octoprint.comm.protocol.gcode.sent`** —
   adopted. Slicer-agnostic, exact, correct on cancel/failure/pause, per-tool for free.

The cost is that the odometer must model extrusion state correctly (M82/M83, G92 resets,
G2/G3 arcs, tool changes, retractions). It is the highest-risk component in the plugin and
carries the heaviest test coverage.

## 2026-08-01 — Target OctoPrint 2.0 only; no 1.x compat layer

2.0 removes a decade of deprecations (snake_case access APIs, CSRF-by-default on blueprints,
removal of `admin_permission`, settings-path moves). Supporting 1.11 alongside would mean a
compat shim at every one of those touchpoints and double the test matrix, for a user base
that is expected to migrate. `octoprint.comm.protocol.gcode.sent` — the hook the whole
metering design rests on — was verified to survive 2.0.

## 2026-08-01 — Defer G-code auto-matching of spools to 1.2+

Standard G-code carries **no stable unique filament identity** — no Filament DB id, no
OpenPrintTag UUID — only `filament_settings_id` (a preset *name*), vendor, and type. Matching
on those requires a real fuzzy matcher, which is the hardest and most-iterated component of
`filament-bridge`. Building a second one is the wrong move.

v1 uses manual per-tool selection plus a material-type warning. The better long-term path is
to close the identity gap upstream (inject the OpenPrintTag UUID or FDB id into the G-code
via the `hyiger` PrusaSlicer Filament Edition fork), after which matching becomes exact and
trivial.

## 2026-08-01 — Do not commit usage on `PrintPaused`

`mdziekon/octoprint-spoolman` commits on pause, which suits Spoolman's weight-decrement model.
Filament DB's unit of record is a *job*, so committing per pause would fragment one physical
print into several `PrintHistory` documents. The odometer accumulates across pause/resume and
commits once at the terminal state.

Related: cancelling a print emits `PrintCancelled` **followed by** `PrintFailed`. A
`last_print_cancelled` flag must suppress the duplicate or every cancelled print
double-commits. The Spoolman plugin does exactly this; the pattern is adopted.
