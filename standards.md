# Standards implemented

This project implements the following [standards](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards)
from the crzynet `homelab-configs` repo. Each row pins the **version** that this
project has actually wired up.

| Standard | Version | Adopted | Notes |
|---|---|---|---|
| [handoff-prompt-workflow](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/handoff-prompt-workflow/README.md) | 2.0.0 | 2026-08-01 | `prompts/TEMPLATE.md` copied; `CLAUDE-snippet.md` pasted verbatim into `CLAUDE.md`; `docs/decisions.md` created. Operating model: central Opus planning session writes prompts and spawns subagents (Opus = research/planning, Sonnet = coding). **Ask-before-commit applies** — no auto-commit deviation. |
| [release-prep-and-cut](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/release-prep-and-cut/README.md) | 1.1.0 | 2026-08-01 | `release-prep.md` / `release-cut.md` copied to `.claude/commands/`; `CLAUDE-snippet.md` pasted verbatim into `CLAUDE.md`. Version file (`_version.py`, bare `0.0.1`) and `CHANGELOG.md` now exist. CI now exists (`.github/workflows/ci.yml`, `codeql.yml`, landed 2026-08-02) — the slash-command placeholders (`<VERSION_FILE>`, `<LOCAL_CHECKS>`, …) can be filled in against the real job commands (`ruff check`/`ruff format --check`, `pytest`, `python -m build && twine check dist/*`) the next time `/release-prep` or `/release-cut` is touched. **Partial adoption until first release.** **Reaching `main` is the user's gate** — run via `/release-prep` → human review + merge → `/release-cut`. An agent must never merge; see the rule block in `CLAUDE.md`. |

Not adopted:

- [code-checkin-and-pr](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/code-checkin-and-pr/README.md)
  — **partially satisfied in practice; formal adoption still open.** As of 2026-08-01 the repo
  implements this standard's branch rule directly: work happens on **`dev`**, and **`main` is
  protected** — PRs required, force-pushes and deletions blocked, `enforce_admins: true` so the
  owner cannot bypass it either. Conventional-commit prefixes are in use.

  As of 2026-08-02, the CI checks the standard mandates now exist and are green on `dev`:
  `.github/workflows/ci.yml` (Lint, Test × Python 3.9/3.13, Package build, Compose validation, plus
  a non-blocking OctoPrint 2.0 scan) and `.github/workflows/codeql.yml` (Python +
  javascript-typescript, `security-extended`). **Still open before formal `1.2.0` adoption:**
  attaching the required-status-checks list in branch protection — deliberately left to the user,
  who is deciding those settings separately (see `docs/decisions.md`).
- [repo-sandbox-permissions](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/repo-sandbox-permissions/README.md)
  — this environment is not sandbox-provisioned.
