---
name: 2026-08-02-ci-and-codeql
status: completed        # pending | completed | failed
created: 2026-08-02
model: sonnet             # coding — the design is settled below, this is execution
completed: 2026-08-02
result: >
  Added .github/workflows/ci.yml (Lint, Test x Python 3.9/3.13, Package build,
  Compose validation, non-blocking OctoPrint 2.0 scan) and codeql.yml
  (python + javascript-typescript, security-extended). Verified green on dev:
  CI run 30786092038, CodeQL run 30786092068 (temporary dev trigger, reverted
  after verification). Python 3.9 floor confirmed genuinely true (46/46 pass).
  Node search-ranking test confirmed executed, not skipped. CodeQL needed no
  manual enabling (public repo). ruff pinned to 0.16.1 with an explicit
  [tool.ruff.lint] select in pyproject.toml to freeze the rule set against
  future default-set drift.
---

# Task: CI workflows + CodeQL

Add GitHub Actions CI and CodeQL scanning, modelled on `crzykidd/filament-bridge`, adapted to this
being a **Python OctoPrint plugin with vanilla JS** rather than a FastAPI + React service.

This unblocks two things that are currently stalled: formally adopting `code-checkin-and-pr @ 1.2.0`
(the branch rule is already implemented; the CI checks are what's missing), and filling in the
`/release-prep` placeholders, which reference the exact commands CI runs.

**Branch protection is NOT part of this task.** The workflows must exist and be green on `dev`
before required checks can be attached, and the user is deciding the settings separately. Do not
touch branch protection.

## Before you start

1. **`CLAUDE.md`** — operational rules. Note especially the **never merge to `main`** rule.
2. **`standards.md`** — what is adopted and what is partial.
3. Read the reference implementation at `~/projects/filament-bridge/.github/workflows/`
   (`ci.yml`, `codeql.yml`). **Read the comments, not just the YAML** — they record three separate
   stuck-required-check failures and why the triggers are shaped the way they are.

## Working tree check

`git status --porcelain` first. This prompt file is exempt. You are on **`dev`**; `main` is
protected and **must not be merged to**.

## Three hard-won rules to copy verbatim from filament-bridge

These are not style preferences — each one is a documented production failure in that repo. Copy the
reasoning into our workflow comments too, so nobody "simplifies" them later.

1. **CI triggers on `push` only, never `pull_request`.** Triggering on both produced duplicate
   same-named check runs that left required checks stuck at *"Expected — Waiting for status to be
   reported"*, forcing a manual merge bypass. Branch protection is **non-strict**, so the head
   commit's push run satisfies the PR's required checks.
2. **CodeQL triggers on `push: [main]` + `pull_request: [main]` + a weekly schedule — `dev` is
   deliberately NOT a push trigger.** Scanning every `dev` push duplicated the `pull_request` run
   during an open PR (stuck checks again) and added heavy load.
3. **A job that must satisfy a required check has to always run.** A job skipped via job-level
   `if:` leaves the required context unsatisfied and PRs sit "blocked" forever. If work inside a job
   should be conditional, put the `if:` on the *steps*, not the job.

## What to do

### 1. `.github/workflows/ci.yml`

`on: push: branches: [dev, main]`. Jobs — each becomes a required check later, so the `name:` values
matter and should be stable:

| Job name | What it runs |
|---|---|
| **Lint** | `ruff check octoprint_filamentdb/ tests/` — **pin the ruff version** (filament-bridge pins it because an unpinned install pulls whatever is newest, and a release that broadens the default rule set turns Lint red on unchanged code) |
| **Test** | `pytest`. **Requires Node** — `tests/test_search_ranking_js.py` shells out to `node`, and it is designed to *fail* rather than skip when Node is absent. Use `actions/setup-node`. Confirm in the run log that the JS test executed. |
| **Package build** | `python -m build` then `twine check dist/*`. This is the real release artifact for a plugin — more meaningful here than a Docker image, since we publish to the OctoPrint Plugin Repository, not a registry. |
| **Compose validation** | `docker compose -f docker-compose.dev.yml config --quiet` |

**Python-specific checks — add these too:**

- **Run `Test` as a Python version matrix: 3.9 and 3.13.** This is the highest-value addition.
  `pyproject.toml` declares `requires-python = ">=3.9"`, but every test so far has run on the
  container's **3.10** — so nothing has ever verified the floor we advertise. Modern syntax
  (`match`, `X | Y` unions outside `__future__`, newer stdlib) would break 3.9 users silently.

  **If 3.9 fails, STOP and report it — do not silently raise `requires-python` to make CI green.**
  Whether to support 3.9 or drop it is the user's call, and "our declared floor was never true" is a
  finding worth surfacing, not papering over. The matrix produces one check per version, so name
  them predictably.

- **`ruff format --check`** in the Lint job — cheap consistency guard. **Check only; never
  auto-format the tree in CI**, and do not mass-reformat existing files to make it pass. If it
  fires widely, report rather than churning every file.

- **`octoscanner`** (OctoPrint 2.0 deprecation scan) — genuinely valuable here, since its whole job
  is catching 1.x APIs we must not use, and it has been run manually at each step. But it is
  **early-development software**, so run it **non-blocking** (`continue-on-error: true`) and do
  **not** propose it as a required check. It should inform, not be able to break `main` when its
  rules change upstream.

**Not adding:** `mypy` (the codebase has no broad annotations; enabling it now would be noise), and
dependency scanning (we have essentially two dependencies, and CodeQL covers code-level security).

**Do not** copy filament-bridge's *Migration check* (no Alembic here) or its *Image build* (we ship
a plugin, not a container image; `Dockerfile.dev` is a dev tool, not a release artifact).

Add a `ruff` config to `pyproject.toml` if one is missing, so local and CI runs agree. **Do not
mass-reformat the codebase to satisfy a newly-enabled rule** — if a rule fires widely, either scope
the config to match current style or report it rather than churning every file.

### 2. `.github/workflows/codeql.yml`

Model on filament-bridge's, with our language matrix:

- `languages: [python, javascript-typescript]` — that identifier covers plain JS; we have no
  TypeScript, but the language ID is still the right one.
- `queries: security-extended` — security-focused; style is `ruff`'s job.
- Triggers exactly as rule 2 above.
- Permissions: `actions: read`, `contents: read`, `security-events: write`.

CodeQL analysis must be enabled on the repo for results to upload. If it needs enabling in repo
settings and you cannot do it from the CLI, **say so explicitly in your report** rather than leaving
a silently failing workflow.

### 3. Documentation

- **`standards.md`** — update the `release-prep-and-cut` row (CI now exists) and note what remains
  before `code-checkin-and-pr @ 1.2.0` can be formally adopted.
- **`CHANGELOG.md`** — a line under `[Unreleased]`. This is infrastructure, so keep it brief.
- **`README.md`** — if you add status badges, they must point at the real workflow files.

## Verify

1. **Push to `dev` and watch the actual runs.** `gh run list` / `gh run view`. Do not report success
   from YAML that has never executed.
2. **Every job must be green.** If one fails, fix it. A red CI landing on `dev` is worse than no CI.
3. **Confirm from the Test job's log that the Node-run search test executed rather than skipped** —
   this is the one most likely to silently degrade in a fresh environment.
4. Report the **exact `name:` of every job**, since those strings are what get attached as required
   checks afterwards. Getting them wrong means PRs stuck "blocked".
5. `pytest` still passes locally in the container.

**If a step fails, fix it. Do not report success with a caveat.**

## Conventions to honor

- `chore:` prefix — this is tooling.
- **Never merge to `main`.** Push to `dev` only.
- Do not touch branch protection — the user is deciding those settings separately.
- `docker exec` needs `-i`; `pip` in the container needs `PIP_USER=false`.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. Move it to `prompts/done/` (or `prompts/failed/`) — untracked, so plain `mv`.
3. Record non-obvious decisions in `docs/decisions.md`, newest at top.
4. **You are a spawned agent: do NOT commit.** Report the file list, a proposed one-line `chore:`
   message, **the exact job `name:` strings**, links or run IDs for the green runs, explicit
   confirmation the Node test executed, and whether CodeQL needed manual enabling in repo settings.
   Never `git add -A`, never push to `main`.
