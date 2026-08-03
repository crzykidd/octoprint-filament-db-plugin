# CLAUDE.md — octoprint-filament-db-plugin

> **Start here → [`prompts/startnewsession.md`](prompts/startnewsession.md)** — the standing
> session brief: what's in flight, what's next, and the operating rules. Read it first in
> every fresh session. This file is the *reference* you come back to; that one is the *state*.

Also read [`standards.md`](standards.md) when the work touches anything the adopted standards
govern (handoff prompts, releases).

## What this project is

An OctoPrint 2.0 plugin that talks to [Filament DB](https://github.com/hyiger/filament-db)
natively: assign a Filament DB spool to each printer tool, meter actual extrusion during the
print, and write one print-history record back to Filament DB on job completion, failure, or
cancellation — including partial usage.

**Read [`docs/prd.md`](docs/prd.md) before doing any design or implementation work.** It is
the v1 spec and it contains hard constraints that are expensive to rediscover, in particular:

- `POST /api/print-history` **already debits spool weight itself.** Never also call
  `POST /api/filaments/:id/spools/:spoolId/usage` for the same print — that double-counts.
- Filament DB works in **grams** and a **gross** weight model. The plugin owns the mm→g
  conversion; there is no length-based endpoint.
- `filament.density` is **nullable**; `filament.diameter` is not.
- Target is **OctoPrint 2.0 only**. No 1.x compat shims.

**Stay in scope.** The plugin reads seven fields off a Filament DB filament — `_id`, `density`,
`diameter`, `type`, `vendor`/`name`, `color`, and the spool sub-fields (PRD C-3b). The document has
~40. Do not audit, display, sync, or file upstream issues about fields the plugin does not use.
v1 is: pick a spool per tool, meter the print, write one print-history record back. Nothing else.

Current status: **pre-alpha, phase 1.** Implemented: plugin skeleton, live raw-millimetre odometer
readout, Filament DB client + spool picker + sidebar. Not yet: mm→gram conversion, slicer metadata,
pre-print checks, the write journal, and the print-history commit.

**Licence: AGPLv3. All code must be original.** Prior art (notably
[`mdziekon/octoprint-spoolman`](https://github.com/mdziekon/octoprint-spoolman)) may be *read and
cited* to understand a problem, but **never copied** — not its odometer, not OctoPrint's vendored
`gcodeInterpreter`, not any other plugin's source. Licences are compatible; this is a deliberate
engineering choice, recorded in `docs/decisions.md`. New source files carry an AGPLv3 header.

## 🚦 Merging to `main` is the user's gate — NEVER merge

**This is a hard rule with no exceptions, and it has already been violated once.**

`main` is not a branch you write to. It is a **release gate the user controls**, and reaching it is
a deliberate process run through `/release-prep` and `/release-cut` — not a tidy-up step at the end
of a work session.

Three tiers, loosest to strictest:

| Action | Rule |
|---|---|
| **Commit to `dev`** | **Always allowed.** Agents may commit freely; no need to ask. Still one coherent commit per task, conventional prefix, specific paths — never `git add -A`. |
| **Push `dev`** | **Normally on request.** Not forbidden — push when the task needs it (CI only runs on pushed commits, for instance) or when asked. Use judgement; say what you pushed. |
| **Anything reaching `main`** | **The user's gate. Only via PR, and the merge is theirs.** Never `gh pr merge`. Never push to `main`. Never tag or publish a release. |

**"Push" NEVER means "merge".** They are different requests. If the user says *push*, push the
branch and stop. And **opening a PR is not permission to merge it** — even when you were explicitly
asked to open one. The merge needs its own yes.

> **Project deviation from `handoff-prompt-workflow`.** The standard's pasted snippet below says
> *"ask `y/n` before committing, never auto-commit, never push."* **This project overrides the first
> two:** committing to `dev` needs no approval. The snippet is left verbatim because that is how
> standards are adopted; this note is the deviation, and it is recorded in `standards.md`.
> The **`main` gate is not relaxed** — if anything it is stricter than the standard requires.

**This was violated once** — PR #2, merged on an unchallenged plan rather than an instruction.
**Silence is not consent, and neither is a plan nobody contradicted.** Full account in
`docs/decisions.md` (2026-08-02). The bar to match is PR #1, where the user said *"let's PR dev to
main and merge it"* — explicit, and naming the merge.

## Task → file routing

**Read only what the task needs.** The layering (PRD rule N-3) guarantees these lists are
sufficient — e.g. a metering bug genuinely cannot require the API client, because `metering/`
imports nothing internal.

*Some paths below (`journal.py`, `retry.py`, `metering/convert.py`, `metering/gcode_meta.py`) are
still planned structure (PRD §Architecture) and don't exist yet. Update this table in the same
commit as any structural change — PRD rule N-8.*

| Task | Read | Spec |
|---|---|---|
| Extrusion counted wrong; G-code state bug (`G92`, `M83`, `T<n>`, arcs) | `metering/odometer.py` + `tests/test_odometer.py` | FR-5 |
| Grams wrong; density/diameter fallback | `metering/convert.py` + its test | FR-6, C-2, C-4 |
| Slicer metadata not parsed; material/sufficiency check wrong | `metering/gcode_meta.py` + its test | FR-4 |
| Filament DB request/response, auth | `client/filamentdb.py`, `client/models.py` + `tests/test_filamentdb_client.py` | FR-1, FR-2, C-3, C-7 |
| Spool list stale / TTL / manual refresh | `client/cache.py` | FR-2 |
| Remaining weight wrong; degraded weight paths (missing tare/nominal/gross, overfilled) | `weights.py` + `tests/test_weights.py` — the sole implementation, server-side only; `api.py`/`assignment.py` call it to annotate what they return, the frontend only renders `weightText`/`weightPercent` | C-2, §Weight display |
| Assignment not saved, duplicate-tool warning, stored record shape | `assignment.py` | FR-2 |
| Usage not committed / committed twice / wrong payload | `job.py`, `retry.py` | FR-7, FR-9, **C-1** |
| Write failed / retry / journal state machine | `journal.py`, `retry.py` | FR-9, FR-9b |
| History UI, failure report, retry & discard actions | `static/js/filamentdb.js`, `api.py` | FR-9b |
| Print lifecycle events, cancel double-fire | `job.py` | FR-7 |
| Tool slots, MMU, extruder count | `static/js/filamentdb.js` (`toolCount`, reads `printerProfilesViewModel.currentProfileData()` — **not** `currentProfile()`, which is just the id string) | FR-3 |
| Spool search ranking (six-tier match order) | `static/js/filamentdb-search.js` — the sole implementation (must run client-side, FR-2); tested via `tests/js/filamentdb_search_test.js` + `tests/test_search_ranking_js.py` (Node, run inside the normal `pytest` invocation) | FR-2 |
| Picker modal: filters, sort, assign/clear, duplicate-warning UI | `static/js/filamentdb-picker.js`, `templates/filamentdb_sidebar.jinja2` | FR-2 |
| Pre-print confirmation dialog; Print button not gated | `static/js/filamentdb.js` (wraps `printerStateViewModel.print` **and** `loadAndPrint`) | FR-4, Q-9 |
| Sidebar rows / live odometer readout | `static/js/filamentdb.js`, `templates/filamentdb_sidebar.jinja2` | FR-2, FR-8 |
| Settings key, new option | `settings_keys.py` **first**, then consumers | N-6 |
| Plugin API endpoint (list/assign/clear/test-connection/refresh) | `api.py` | FR-2, C-6 (CSRF) |
| Permissions | `plugin.py` (permissions hook), `api.py` (per-endpoint enforcement) | FR-10 |
| Doesn't look right under a theme; custom CSS | `static/css/`, `templates/*.jinja2` | PRD §OctoPrint UI framework — **never hardcode colours**; use Bootstrap 2 / OctoPrint classes |
| Dashboard/3rd-party plugin can't see our data | `plugin.py` (`additional_state_data`, custom events) | PRD §OctoPrint UI framework — **that hook must never throw; one exception blocklists it until restart** |

## Code shape

The full rules are PRD §"Codebase design constraints" (N-1…N-10). The ones that bind every
change:

- **500-line hard cap per module.** Crossing it means splitting in the same change, not later.
- Every module opens with an **OWNS / DOES NOT OWN** docstring.
- **`metering/` and `client/` import nothing internal**; `metering/` must never import
  `client/`. An import-direction test enforces it.
- **`plugin.py` is wiring only** — the moment a method makes a decision, it belongs in a module
  the tests can reach without booting OctoPrint.
- Tests mirror source paths 1:1.
- Keep **project-authored prose in this file under ~150 lines** — the three verbatim
  `CLAUDE-snippet.md` blocks below are mandated by the adopted standards and sit outside the cap
  (PRD N-9). If our own prose drifts over, move it to the PRD and leave a pointer; never trim the
  snippets.

<!--
Source: standards/code-checkin-and-pr @ v1.2.0 (crzynet/homelab-configs).
Paste the section below verbatim into the adopting project's CLAUDE.md.
The full standard (publishing matrix, retention, CI check definitions) lives at:
https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/code-checkin-and-pr/README.md
-->

## Code check-in (operational rules)

This project adopts the `code-checkin-and-pr` standard. The full why-and-how lives at
the source above; the rules below are the per-session do/don'ts a coding agent must
honor by default:

- **Never push directly to `main`.** `main` is protected. All changes land via a pull
  request from `dev` → `main`, and only when every required check is green.
- **Day-to-day work happens on `dev`** (or a short-lived branch off `dev`). Push to
  `dev` freely.
- **Commit message prefixes are required** — Conventional-Commits style:
  - `feat:` — new user-facing feature
  - `fix:` — bug fix
  - `chore:` — config, tooling, dependencies, maintenance
  - `docs:` — documentation-only changes
- **Do not add `Co-authored-by:` trailers** unless the user explicitly asks.
- **Doc updates ship in the same commit as the code they describe** — never as a
  follow-up commit.
- **Never bypass hooks** (no `--no-verify`, `--no-gpg-sign`, etc.) unless the user
  explicitly asks. If a hook fails, fix the underlying issue.
- **Stable releases are tagged from `main` only.** Don't tag from `dev`.

If you're unsure whether an action would violate one of the above, stop and ask before
acting.

<!--
Source: standards/handoff-prompt-workflow @ v2.0.0 (crzynet/homelab-configs).
The full standard (the plan→decide→execute→document principle, model selection,
TEMPLATE, adoption checklist) lives at:
https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/handoff-prompt-workflow/README.md
-->

## Handoff prompts (operational rules)

This project adopts the `handoff-prompt-workflow` standard. The full why-and-how lives at
the source above; the rules below are the per-session do/don'ts an agent must honor by
default:

- **Edit-size threshold — decide by how much you'll change:**
  - A genuinely small change — roughly **one or two files and a few lines** (a typo, one
    config value, a one-line fix) — do it **in-session**, no prompt.
  - **Anything bigger requires a handoff prompt** — more than ~2 files, a multi-step
    change, a new feature, or any edit large enough that a fresh context would run it
    more cleanly. **When in doubt, write the prompt.**
- **A handoff prompt is a file in `prompts/`** — one per task, from `prompts/TEMPLATE.md`,
  with frontmatter (`name`, `status`, `created`, `model`, `completed`, `result`). Set
  `model:` from the task type: **Opus** for research/planning, **Sonnet** for coding;
  mixed defaults to Opus.
- **Execute the prompt by spawning a subagent — don't hand the user a command.** Spawn an
  agent on the prompt's `model:`, let it run the prompt end-to-end, and **report the
  outcome back**. The agent gets a fresh context; you stay in the loop.
  - **Manual fallback only on explicit request.** If the user says e.g. "use manual
    prompts for this," give them
    `claude --model <model> "Read prompts/<file>.md and execute it as your task."`
    instead of spawning.
- **Check the working tree before editing.** Run `git status --porcelain`, cross-reference
  the files the plan touches; if any have uncommitted changes, list them and ask before
  touching. Surface unrelated dirty files once; they don't block.
- **The prompt self-updates and moves when done.** The executing agent sets its
  frontmatter (`status`/`completed`/`result`) and `git mv`s the file into `prompts/done/`
  (success) or `prompts/failed/` (failure).
- **One commit at the end; the prompt bundles in.** The prompt file is **not** committed
  up front — it lands in the single end commit alongside the work and the prompt move.
  Propose ONE commit (files list + one-line message), ask `y/n`, stage only those specific
  paths. **Never `git add -A`, never auto-commit, never push.** A spawned agent prepares
  the tree and reports the proposed commit back; the orchestrating session surfaces the
  `y/n`.
- **Record non-obvious decisions** (approach changes, rejected alternatives, workarounds)
  in `docs/decisions.md`, newest at top.

If you're unsure whether an action would violate one of the above, stop and ask before
acting.

<!--
Source: standards/release-prep-and-cut @ v1.1.0 (crzynet/homelab-configs).
The full standard (two-phase prep/cut workflow, archive trigger, validation
steps, adoption checklist) lives at:
https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/release-prep-and-cut/README.md
-->

## Release process (operational rules)

This project adopts the `release-prep-and-cut` standard. The full why-and-how
lives at the source above; the rules below are the per-session do/don'ts a
coding agent must honor by default:

- **The version is stored BARE in the source-of-truth file** — no `v` prefix
  anywhere in code. The `v` prefix is added in exactly one place: the git tag
  and matching GitHub release name. Don't add it to README badges, CHANGELOG
  headers, in-code image tags, or anywhere else.
- **`CHANGELOG.md` is the single source of truth for release notes.** The PR
  description (set by `/release-prep`) and the GitHub release body (set by
  `/release-cut`) reuse the **same section verbatim**. Never author release
  notes twice.
- **One commit per release prep.** Version bump + changelog roll + every doc
  sync ship in a single `chore(release): prepare v<version>` commit. No
  `Co-authored-by:` trailers.
- **Never re-tag.** If `v<version>` already exists as a local tag, a remote
  tag, or a GitHub release, STOP. Never delete-and-recreate; never `--force`.
  Pick the next version instead.
- **`/release-cut` only after the PR has merged and CI is green.** The
  publish-to-`main` workflow must have already pushed `:latest` images to the
  registry before `/release-cut` runs. If you cannot confirm both — STOP and
  tell the user to wait.
- **The release tag is the only thing the cut command writes to `main`.** Both
  the prep commit and any follow-up docs commit land on `dev` and reach `main`
  only via PR. Never push directly to `main` as part of a release.

If you're unsure whether an action would violate one of the above, stop and
ask before acting.

> **Note — branch strategy is undecided.** `release-prep-and-cut` composes with
> `code-checkin-and-pr`, which this project has **not** adopted. The `dev` → protected-`main`
> PR flow the rules above assume therefore has no defining standard here yet. See the open
> item in [`standards.md`](standards.md); resolve before the first release.
