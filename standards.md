# Standards implemented

This project implements the following [standards](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards)
from the crzynet `homelab-configs` repo. Each row pins the **version** that this
project has actually wired up.

| Standard | Version | Adopted | Notes |
|---|---|---|---|
| [handoff-prompt-workflow](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/handoff-prompt-workflow/README.md) | 2.0.0 | 2026-08-01 | `prompts/TEMPLATE.md` copied; `CLAUDE-snippet.md` pasted verbatim into `CLAUDE.md`; `docs/decisions.md` created. Operating model: central Opus planning session writes prompts and spawns subagents (Opus = research/planning, Sonnet = coding). **Ask-before-commit applies** — no auto-commit deviation. |
| [release-prep-and-cut](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/release-prep-and-cut/README.md) | 1.1.0 | 2026-08-01 | `release-prep.md` / `release-cut.md` copied to `.claude/commands/`; `CLAUDE-snippet.md` pasted verbatim into `CLAUDE.md`. Version file (`_version.py`, bare `0.0.1`) and `CHANGELOG.md` now exist. Still missing: CI, and the slash-command placeholders (`<VERSION_FILE>`, `<LOCAL_CHECKS>`, …) are unfilled. **Partial adoption until first release.** **Reaching `main` is the user's gate** — run via `/release-prep` → human review + merge → `/release-cut`. An agent must never merge; see the rule block in `CLAUDE.md`. |

Not adopted:

- [code-checkin-and-pr](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/code-checkin-and-pr/README.md)
  — **partially satisfied in practice; formal adoption still open.** As of 2026-08-01 the repo
  implements this standard's branch rule directly: work happens on **`dev`**, and **`main` is
  protected** — PRs required, force-pushes and deletions blocked, `enforce_admins: true` so the
  owner cannot bypass it either. Conventional-commit prefixes are in use.

  Not yet in place: the required CI checks (lint, tests, SAST/CodeQL, image build) that the
  standard also mandates, since there is no application code to check. Formally adopt at `1.2.0`
  once CI exists — that is also what `release-prep-and-cut` assumes, since it composes with this
  standard.
- [repo-sandbox-permissions](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/repo-sandbox-permissions/README.md)
  — this environment is not sandbox-provisioned.
