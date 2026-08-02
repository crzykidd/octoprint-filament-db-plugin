# Start-new-session prompt — octoprint-filament-db-plugin

Point me at this file at the start of a fresh session. It's a standing onboarding brief
(**not a task** — never move it to `done/`). It restates the project, the operating rules, and
what's in flight, so a new session is productive even with no conversation memory.

**Keep it under ~200 lines.** It is a *state* document — what's in flight — not a knowledge
dump. Design detail belongs in `docs/prd.md`; the "why" belongs in `docs/decisions.md`.

## What this project is

An **OctoPrint 2.0 plugin that talks to [Filament DB](https://github.com/hyiger/filament-db)
natively.** Assign a Filament DB spool to each printer tool, meter actual extrusion during the
print, and write **one print-history record** back to Filament DB when the job ends — completed,
failed, or cancelled — including partial usage. No Spoolman, no `filament-bridge` dependency.

- **Stack:** Python 3.9+, OctoPrint 2.0 plugin mixins, `requests`, Knockout JS frontend
  (OctoPrint's native UI framework). Packaged with `pyproject.toml`.
- **Repo:** `crzykidd/octoprint-filament-db-plugin` (name matches this directory).
  Python package `octoprint_filamentdb`, plugin identifier `filamentdb`.
- **Talks to:** a Filament DB instance over REST (`/api/…`), optional `Authorization: Bearer`.

## Read first (in this order)

1. **`CLAUDE.md`** — operational rules + the task→file routing table. Start here for "which
   files do I touch."
2. **`docs/prd.md`** — the v1 spec. Constraints C-1…C-7, requirements FR-1…FR-13, and the
   navigability rules N-1…N-10.
3. **`standards.md`** — adopted standards + pinned versions.
4. **`docs/decisions.md`** — the "why" log. **Check before re-deriving a design.**

## The four constraints that bite hardest

Re-derived by more than one session already; internalize them before touching code:

1. **`POST /api/print-history` already debits spool weight itself** (transactional, tagged
   `source: "job"`). **Never also call `/spools/:id/usage` for the same print** — double-debit.
2. **Filament DB works in grams, gross weight model.** The plugin owns the mm→g conversion;
   there is no length-based endpoint (Spoolman has one; FDB does not).
3. **`filament.density` is nullable** (verified — creating one without it is accepted);
   `diameter` always has the 1.75 schema default. **But Filament DB resolves `own ?? parent` for
   density in BOTH projections — never walk the parent chain yourself.** The FR-6 fallback is
   therefore only reachable via a *root* filament with `density: null`; don't silently default, and
   don't skip the user-facing warning.
4. **OctoPrint 2.0 only.** No 1.x compat shims. Blueprints are CSRF-protected by default;
   `admin_permission` is gone; access APIs are snake_case.

## Operating rules (honor these by default)

**Scope**
- **Only work the thing the user explicitly names.** Never fan out, never pick up adjacent
  work, never add "while I'm here" fixes. Offer others as a one-liner, then wait.
- For substantial *named* work, write a handoff prompt and **dispatch a Sonnet subagent**;
  Opus orchestrates, reviews the diff, integrates. Don't dispatch unnamed work.

**Handoff prompts (`handoff-prompt-workflow` @ 2.0.0)**
- ≤1–2 files and a few lines → do it in-session. **Anything bigger → write a prompt** in
  `prompts/` from `TEMPLATE.md`. When in doubt, write the prompt.
- `model:` frontmatter — Opus for research/planning, Sonnet for coding.
- The executing agent self-updates frontmatter and `git mv`s to `prompts/done/` or
  `prompts/failed/`.

**Git**
- **Ask before committing. Never auto-commit. Never push.** Stage specific paths — never
  `git add -A`.
- One commit at the end; the prompt file bundles into it.
- Check `git status --porcelain` before editing; if the user is mid-edit on a file the plan
  touches, list it and ask.
- **Work on `dev`. `main` is protected** — PRs only, force-push and deletion blocked, and
  `enforce_admins: true` so even the owner cannot push directly. Changes reach `main` via a
  `dev → main` PR. Conventional-commit prefixes (`feat:`/`fix:`/`chore:`/`docs:`).
- **Never put anything in `private_data/`** expecting it to be committed — the whole directory is
  gitignored. Committed test data goes in `tests/fixtures/`.

**Code shape (the N-rules in `docs/prd.md`)**
- **500-line hard cap per module.** Crossing it means splitting in the same change.
- Every module opens with an OWNS / DOES NOT OWN docstring.
- **Layering:** `metering/` and `client/` import nothing internal. `metering/` must never
  import `client/`. An import-direction test enforces this.
- `plugin.py` is wiring only — no logic.
- Tests mirror source paths 1:1.
- **Update the routing table in `CLAUDE.md` in the same commit as any structural change.**

**Decisions**
- Log non-obvious calls (approach changes, rejected alternatives, workarounds) in
  `docs/decisions.md`, newest at top.

## ⏸️ PICK UP HERE (2026-08-01 — design complete, no code yet)

**Status: pre-alpha. PRD written and reviewed. Zero application code.**

Nothing is in flight. The design is settled and the repo scaffolding is in place:
`docs/prd.md`, `docs/decisions.md`, `standards.md`, `CLAUDE.md`, `prompts/TEMPLATE.md`,
`.claude/commands/release-{prep,cut}.md`.

**Not yet done — likely next steps, in dependency order:**

**Testing is staged — one new variable per phase. We are on phase 1.**
**1.** clean OctoPrint 2.0, **no third-party plugins**, **single-extruder** virtual printer — prove
the core loop end to end. **2.** real single-tool hardware. **3.** MMU (`mmu5` profile, then the real
Core One + MMU). **4.** plugin coexistence (`Octoprint-PrusaMMU`). Most documented risk is phase 3+;
don't let it complicate phase 1. Do not install other plugins in the dev instance yet.

1. **Bring up the dev environment and confirm it works.**
   `docker compose -f docker-compose.dev.yml up -d --build` → http://localhost:5000. The compose
   and `Dockerfile.dev` are written but **have never been run** — verify the 2.0 RC upgrade
   actually takes (the Dockerfile asserts it), then walk the wizard and enable the virtual
   printer. This also answers **Q-3**.
2. ~~Resolve the open questions.~~ **Done — Q-1…Q-8 are all answered** (2026-08-01), see the Open
   questions table in `docs/prd.md`. Two changed requirements: `M600` is **not** in OctoPrint's
   default `pausingCommands`, so a filament change does not pause the print at all; and `spoolId`
   is optional on `POST /api/print-history`, which is exactly why it must always be sent.
3. **Formally adopt `code-checkin-and-pr @ 1.2.0`** once CI exists. The branch rule is already
   implemented (`dev` + protected `main`); the CI checks are what's missing.
4. **Seed a null-density ROOT filament in the dev Filament DB** before trusting FR-6. The instance
   is now 45 filaments / 36 spools (33 variants — good parent/variant coverage), but nothing
   exercises the density fallback: a null-density *variant* inherits from its parent, so only a
   root filament with `density: null` reaches that branch. Dev FDB is
   `http://crzydev.home.arpa:3000`, writable, unauthenticated; clean up `zzz-*` records you create.
5. **Then implement UI-first, not bottom-up.** Deliberate change — without a UI the odometer is a
   black box that unit tests cannot fully validate (see `docs/decisions.md`, 2026-08-02). Order:
   1. **plugin skeleton** — loads clean on OctoPrint 2.0, settings, permissions, sidebar shell
   2. **live raw-millimetre readout** — the debug instrument. **Zero dependencies:** no Filament DB,
      no spool selection, no density. Just hook → accumulate → display.
   3. `metering/odometer.py` — now directly observable, and checkable against the slicer's
      `filament used [mm]` (the FR-5 acceptance bar)
   4. `metering/convert.py` → `metering/gcode_meta.py` → `client/filamentdb.py` → spool picker
   5. `journal.py` → `retry.py` → `job.py` → commit path
   6. pre-print confirmation dialog → FR-9b history/failure report

## Current state (update as it moves)

- **Releases:** none. No version file, no `CHANGELOG.md`, no CI yet.
- **Open issues:** none filed — no GitHub repo yet.
- **Upstream asks queued** (file once the repo exists, see `docs/prd.md`):
  1. `hyiger/filament-db` — add `"octoprint"` to the print-history `source` enum (v1 sends
     `"other"` as a workaround).
  2. `hyiger/filament-db` — idempotency key on `POST /api/print-history`, so a retry after an
     ambiguous timeout can't double-debit (this is a real v1 limitation, see FR-9).
  3. `hyiger/filament-db#1039` — post the design to the thread; it answers the OP's request.
  4. `hyiger/PrusaSlicer` (Filament Edition fork) — inject the OpenPrintTag UUID / FDB id into
     the G-code config block, which would make FR-13 auto-matching exact instead of fuzzy.
- **`Octoprint-PrusaMMU` runs on the test rig** (Core One + MMU) — see PRD §Known plugin
  interactions. It **remaps** `T<n>` at the `gcode.queuing` phase, so the odometer sees the
  physically-correct tool (benign), and it publishes `plugin_prusammu_mmu_changed` explicitly for
  other plugins — a better MMU signal than parsing `echo:MMU2:`. Coexistence is **deferred**; both
  it and this plugin want to own "which spool is in slot N".
- **Real MMU3 runout capture is committed** at `tests/fixtures/serial/mmu3-filament-change-runout.md`
  — use it, don't invent serial fixtures. It validates the odometer against firmware `M114`
  (exact match), and it **disproved** the earlier assumption that a filament change produces a
  visible pause: there is no `M600`, no `// action:` command, and the send queue simply stalls.
  **Q-7 (does `PrintPaused` fire at all here?) is still open** — until answered, the vendor-neutral
  stall watchdog is the only detection signal that can be relied on.
- **Needs real hardware to verify:** FR-3 tool attribution with an **MMU3 + `Octoprint-PrusaMMU`**
  installed. That plugin intercepts `Tx` at the `gcode.queuing` phase, and a suppressed command
  never reaches `gcode.sent` — so the odometer can miss a tool change. The virtual printer cannot
  reproduce this. Until it's tested, treat per-tool attribution on MMU as unproven; the *total*
  is not at risk.
- **Dev dependencies:** the Filament DB dev instance from the `filament-bridge` work is reused
  as-is (200+ spools, variants, retired spools, null-density records — better test data than
  anything seeded). The dev compose file joins its network rather than standing up a second
  instance.

## How to start a session

1. Read the docs listed above (`CLAUDE.md` first — its routing table saves the most time).
2. Ask me which piece to work — then work **only** that.
3. For anything over ~2 files: write the handoff prompt, spawn the subagent, report back.
4. Tests + docs in the same commit as the code. **Stop and ask before committing.**
