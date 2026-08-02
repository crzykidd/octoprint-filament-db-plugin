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

## 2026-08-02 — Loading a spool is a standalone act; checks are grouped by their inputs

An earlier draft triggered all pre-print checks on `FileSelected`, which quietly assumed loading a
spool and choosing a file are one flow. **They are not.** A user loads spools when they load spools
and picks a file later — often much later. At load time there is no file, so nothing about the print
can be known.

Two things follow, and the second is the one that was actually wrong:

1. **The picker cannot depend on the print.** No "enough for this print" filter, and no
   G-code-driven pre-selection of material type. Both belong to FR-4, not to loading. (The type
   *chips* stay — they filter the library, not the print.)
2. **Print start is the authoritative gate**, not file-select. It is the last moment before filament
   is consumed and the only moment both file and assignments are guaranteed known. `FileSelected`
   is an early bonus when a file happens to be selected; nothing may depend on it having fired.

Checks are now grouped by what they depend on, each running as early as its inputs allow. The useful
consequence: **the missing-density warning needs only the spool**, so it fires at *assignment* time —
earlier than the old design managed, and independent of whether a file is ever selected.

Follow-on: "block" mode needs a mechanism, since `PrintStarted` fires *after* the job begins —
cancelling there means the printer has already homed and possibly purged. Logged as Q-9. Warn is the
default, so v1's core path is unaffected.

## 2026-08-02 — Spool picker: one ranked search box, no modes

Grounded in the live library rather than assumed. All 36 spools carry a **numeric `label`**
(`5, 19, 21, 47 … 204, 224` — the user's physical numbering), a **10-char hex `instanceId`**
(Filament DB's durable per-spool identity, the NFC/QR key, and the direct equivalent of Spoolman's
hex id), and a 24-hex Mongo `_id`.

Rejected a mode switch (search-by-label vs search-by-id vs text). Instead **one field ranked by match
quality**: exact `label` → exact `instanceId` → exact `_id` → `label` prefix → fuzzy over
vendor/name/type/colour/location, with each row showing *why* it matched so a fuzzy hit is never
mistaken for an exact one. This matches what `filament-bridge`'s mobile lookup already learned —
numeric lookup is the common case, hence its numeric-keypad default.

Search is client-side over the cached list (no round-trip per keystroke), falling back once to
`GET /api/filaments/match?instanceId=` on an exact-identifier miss, which catches a spool created
since the last refresh.

**Default sort: most recently used on this printer**, from the plugin's own write journal (FR-9b) —
already stored, and more relevant than a global last-used because it reflects what this machine
actually consumes.

**Duplicate assignment warns rather than blocks.** One physical spool usually cannot be in two slots,
so it is normally a mis-click — but it is not the plugin's place to declare a printer setup
impossible. FR-7 already sums duplicate assignments into one usage entry so the data stays correct;
the "already on Tool N" badge exists so the mistake is visible rather than silently averaged away.

## 2026-08-02 — CORRECTION: Filament DB has NFC/identifier lookup endpoints (C-3 was wrong)

The preceding NFC entry claimed Filament DB has **no lookup-spool-by-identifier endpoint**, so an
NFC read would have to resolve client-side against the picker cache. **That was wrong**, and so was
C-3's claim that there is no standalone spool endpoint. Both were over-generalised from a
`filament-bridge` doc note about there being no spool-*label* lookup — a note that was true for
what the bridge uses and false as a general statement.

Enumerating Filament DB's actual API routes found four relevant endpoints:

- **`POST /api/nfc/decode`** — decodes raw OpenPrintTag CBOR / Bambu MIFARE / OpenTag3D bytes
  server-side and returns `{decoded, match, candidates}`. Its docstring states the intent: the
  mobile scanner's whole job is read bytes → POST → render, deliberately centralised so there is
  one tested decoder rather than drifting duplicates.
- **`GET /api/filaments/match?instanceId=&name=&vendor=&type=`** — identifier resolution with tier
  order `instanceId → name → vendor+type → vendor`, returning `{match, candidates, matchedSpool}`.
- **`GET /api/spools/{spoolId}`** — `{filament, spool}` with the filament **inheritance-resolved**.
- `GET /api/scan/stream` + `POST /api/scan/publish` — the scan event stream.

Both `match` and `nfc/decode` are deliberately outside the same-origin guard; their docstrings name
the mobile app and PrusaSlicer/OrcaSlicer as intended cross-origin callers. An OctoPrint plugin is
the same class of client.

**Answering the question that prompted this** — does scanning an OpenPrintTag identify the spool?
Verified live: querying a real spool's `instanceId` returned `matchedSpool: {_id, instanceId,
label}` plus the filament, i.e. the exact `(filamentId, spoolId)` pair the plugin needs. But that
holds for a **Filament-DB-written** tag, whose `spoolUid` carries an FDB instance id. A
**third-party vendor** OpenPrintTag falls through to the heuristic tiers and yields a filament-level
match with `matchedSpool: null` — which filament, not which physical spool.

**This also improves v1, not just the future feature.** `GET /api/spools/{spoolId}` is a better read
for an assigned spool than fetching the parent filament: one call returns both the spool and the
inheritance-resolved filament, and the plugin already holds the `spoolId`. FR-6 updated.

**Process note:** this is the second time a `filament-bridge` doc note was carried into this PRD as
a general constraint when it only described that project's usage. Verify against Filament DB's
actual routes, not the bridge's notes.

## 2026-08-02 — NFC is additive; four v1 seams keep it that way

> **⚠️ PARTIALLY SUPERSEDED** by the entry above (same day). Seam 1 below — caching
> `spools[].instanceId` because Filament DB supposedly has no lookup-by-identifier endpoint — was
> based on a **false premise**. Those endpoints exist (`GET /api/filaments/match`,
> `POST /api/nfc/decode`), so tag resolution happens server-side and does not depend on the cache.
> **Three seams, not four.** Seams 2–4 stand. Kept as written for the history.

NFC spool loading is a **future** version item and is deliberately **not designed** here. The only
question asked was narrower: does v1 need to change so a later NFC feature doesn't force a redesign?
Answer: barely.

NFC changes exactly one thing — *what sets the loaded spool* — and v1 already funnels every
assignment through one internal choke point (`assignment.set`/`clear`, added for the FR-11 slot
writeback seam). NFC becomes another caller. Metering, conversion, commit and the journal are all
untouched.

Four v1 decisions keep it additive, each cheap now and a migration later:

1. **Keep `spools[].instanceId` in the cached spool model** even though v1 never reads it. It is
   Filament DB's per-spool identifier and the key an NFC/QR read resolves against — and since FDB
   has **no lookup-spool-by-identifier endpoint**, that resolution must run client-side against this
   cache. It is already in the list projection; the only requirement is not stripping it.
2. **Assignment records carry a `source`** (`manual` in v1) so NFC- and hand-driven assignments are
   distinguishable and don't silently overwrite each other.
3. **The choke point is callable from a background thread** and pushes a UI update. NFC events are
   asynchronous; an assignment path written as a request handler only would need rewriting. v1
   already needs async→UI push for live metered grams, so this is free.
4. **The odometer keys on `(tool_index, assignment_id)`** — already specified for FR-12. An NFC
   insert mid-print *is* a spool change and should produce a changeover marker like any other.

Left open for that version: reader hardware, whether to read tags directly or subscribe to Filament
DB's scan stream, unresolvable tags, and auto-assign vs pre-select-for-confirmation.

## 2026-08-02 — Testing is Prusa-first; other platforms untested, not unsupported

Real-hardware verification runs on the maintainer's Prusa MK-series + MMU3 with PrusaSlicer.
Recorded so the boundary is explicit rather than implied.

The core metering logic is **printer-agnostic by construction** — counting E-moves is a property of
G-code, not of a vendor — so Marlin/Klipper/RepRap should behave identically. But "should" is not
"tested", and the README says so rather than implying broader coverage than exists.

The genuinely vendor-specific piece is `echo:MMU2:` parsing, and that is precisely why FR-12's
*primary* detection signal is a vendor-neutral stall watchdog with message parsing as an
accelerator. Had it been the other way round, every non-Prusa platform would need its own detection
implementation.

Boundary noted for later: the advanced-G-code work (`M200` volumetric, `G10`/`G11` firmware
retraction, `M221` multiplier) is where firmware differences start to matter for real. Each needs
per-platform verification rather than an assumption that Prusa behaviour generalises.

## 2026-08-02 — Detail projection resolves inheritance for every conversion-critical field

Tested rather than assumed, after the reasonable proposition that "Filament DB combines the values
so we never need to worry where we look." **Correct for what the plugin actually needs** — with two
exceptions worth knowing.

Built a parent with fields set and a variant with none, then compared both projections. In
`GET /api/filaments/:id` the variant inherits `density` and `diameter`. So the rule stands: **read
detail for an assigned spool and trust it; never walk the parent chain.**

The specific worry that prompted the test was `diameter`, which carries a schema default of 1.75 —
a default is not inheritance, and had a 2.85 mm parent's variant fallen back to 1.75 the mm→g
conversion would have been wrong by (2.85/1.75)² ≈ **2.65×**. It inherits correctly. Worth having
checked; a silent 2.65× error on volumetric conversion would have been very hard to spot from
plausible-looking gram figures.

One exception that matters: **`diameter` is absent from the *list* projection entirely.** The
picker's cached list is therefore not sufficient for conversion — detail must be fetched for
assigned filaments. (Same finding as Q-1, now with the inheritance dimension confirmed.) `color`
correctly does not inherit — a variant *is* a colour — so the swatch uses the record's own value.

Also learned in passing: `type` **is** required on create (a variant without it 400s), unlike
`density`.

**Scope correction (same day).** This investigation also catalogued `cost`, `temperatures`,
`netFilamentWeight` and `lowStockThreshold`, and produced an upstream ask about
`lowStockThreshold` inheritance. **All of that was out of scope and has been removed** — the plugin
does not read those fields. The root cause was mine: the first PRD draft put a low-stock indicator
into FR-8 that the user never asked for, and the field audit then inherited that invented scope.
FR-8's low-stock indicator is deleted along with it. **The fields this plugin reads are `density`,
`diameter`, `type`, `color`, `vendor`, `name`, and the spool sub-fields — nothing else.**

## 2026-08-02 — Missing density: estimate and disclose, never block or silently guess

The handling was specified but scattered across FR-4, FR-6 and FR-9b, and could not be read off the
document as a single answer. Consolidated into FR-6 §"What actually happens when there is no
density". The reasoning, recorded because the alternatives are all defensible:

The plugin always knows **length** exactly; Filament DB accepts only **grams**; density is the sole
bridge. Three options:

- **Block the commit** — never writes a wrong number, but loses real usage if the user doesn't act.
  Hostile after a long print. Kept as an opt-in setting, not the default.
- **Estimate silently** — rejected outright. An invented number entering inventory as though it
  were measured is the worst outcome available.
- **Estimate, disclose, stay correctable** — chosen.

Three layers: **warn at `FileSelected`** (when the fix costs ten seconds, not after a 12-hour
print); **estimate from the material-type default and disclose in four places** (toast, journal row,
print-history `notes`, log); **keep the raw millimetres in the journal** so the entry can be
recomputed exactly once a real density exists.

That last point is why FR-9b stores metered mm and not just grams — length is the measurement,
grams are derived, and only the derivation is uncertain.

Accuracy honesty drove the wording: unfilled PLA/PETG/ABS cluster tightly enough that a type-matched
default lands within 1–3%, inside the ±2–3% that diameter tolerance already imposes. Filled and
exotic blends (wood, metal, glow, CF, TPU) span ~1.1–2.0+ and can be 30%+ wrong, so the
unknown-type path must warn differently rather than reusing the mild common-case wording.

Explicitly rejected: writing a guessed density **back** to Filament DB. That would promote a
one-job estimate to permanent library truth, and v1 writes print-history only (C-1). Also rejected:
any "commit zero" or "skip silently" option — both under-report real consumption, which is worse
than a disclosed estimate.

## 2026-08-01 — `density` is optional, but inheritance is resolved server-side (C-4 refined)

Tested directly against the live dev instance rather than inferred from the Mongoose schema, after
the question "density is required, right?" — a reasonable assumption that turns out to be wrong in
one direction and right in another.

- **It is not required.** `POST /api/filaments` with no `density` is accepted and stores
  `density: null`, while `diameter` picks up its schema default of 1.75. The null case is real, so
  the FR-6 fallback chain is necessary.
- **But both projections resolve it from the parent.** The list route does
  `$ifNull: ["$density", {$arrayElemAt: ["$_parent.density", 0]}]` and detail applies the same
  `own ?? parent` rule. Confirmed with a purpose-built parent(1.99)/variant(null) pair: the variant
  reports **1.99 in both projections**.

This also corrects an earlier reading. "45/45 filaments have a non-null density" was measured off
the list projection, which is the *inherited* value — not evidence that every record carries its
own.

Two consequences:

1. **The plugin must never walk the parent chain itself.** The server already does it, in both
   projections. Reimplementing it would be duplicated logic that silently diverges.
2. **The fallback is only reachable via a *root* filament with `density: null`.** A null-density
   *variant* inherits and never reaches it. So the branch needs a deliberate test fixture — left to
   real data it would never execute and would rot untested. Recorded in the test strategy.

## 2026-08-01 — Q-1…Q-8 resolved; two answers changed requirements

All eight open questions answered against a live OctoPrint 2.0.0rc4 container, the live Filament DB
dev instance, and upstream source. Full answers are in the PRD's Open questions table. Two were not
confirmations — they changed the design:

**`M600` is not in OctoPrint's default `pausingCommands`.** The default is `["M0", "M1", "M25"]`
(`serial_connector/config_schema.py`). So a slicer-emitted `M600`, sitting plainly in the outgoing
stream, **does not pause OctoPrint at all** on a default install. Combined with Q-7 — `PRINT_PAUSED`
fires from exactly one place, reachable only by a host pause, an `// action:pause`/`paused`, or a
`pausingCommands` match — this closes the question the MMU capture opened: pause-based marking is
not viable as a primary mechanism, and the vendor-neutral stall watchdog is load-bearing.

New requirement from this: the plugin should *detect* that `M600` is missing from `pausingCommands`
and surface a dismissible hint. It is a real OctoPrint configuration gap that bites people well
beyond this plugin. **Advise; never silently edit another plugin's settings.**

**`spoolId` is optional on `POST /api/print-history` — which is exactly why it must always be
sent.** Omitting it makes Filament DB pick `first non-retired spool with totalWeight > 0`, falling
back to `first non-retired spool`. That is an implicit inventory choice the user never made, on a
request that debits real weight. The PRD previously said "send it explicitly regardless" on a
hunch; that hunch is now justified.

Also worth recording, though they only confirmed existing design: `diameter` is absent from the
Filament DB list projection but present in detail (Q-1), so FR-6's fetch-detail-for-assigned-only
approach stands; OctoPrint 2.0 introduces **no** new tool abstraction (Q-4), so FR-3 holds;
`MAX_USAGE_GRAMS` is 1,000,000 g — an overflow backstop that will never fire on a real job (Q-5);
and `octoprint.comm.protocol.gcode.received` is the hook for `echo:MMU2:` parsing (Q-8).

**Test-data gap found while answering Q-1:** the dev Filament DB has 10 filaments / 7 spools, not
the 200+ of production, and **every record has a non-null density** — so FR-6's density fallback
chain is currently untestable there. Seed a null-density record before calling FR-6 verified.

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
