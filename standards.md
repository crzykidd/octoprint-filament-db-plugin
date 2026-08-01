# Standards implemented

This project implements the following [standards](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards)
from the crzynet `homelab-configs` repo. Each row pins the **version** that this
project has actually wired up.

| Standard | Version | Adopted | Notes |
|---|---|---|---|
| [handoff-prompt-workflow](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/handoff-prompt-workflow/README.md) | 2.0.0 | 2026-08-01 | `prompts/TEMPLATE.md` copied; `CLAUDE-snippet.md` pasted verbatim into `CLAUDE.md`; `docs/decisions.md` created. Operating model: central Opus planning session writes prompts and spawns subagents (Opus = research/planning, Sonnet = coding). **Ask-before-commit applies** — no auto-commit deviation. |
| [release-prep-and-cut](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/release-prep-and-cut/README.md) | 1.1.0 | 2026-08-01 | `release-prep.md` / `release-cut.md` copied to `.claude/commands/`; `CLAUDE-snippet.md` pasted verbatim into `CLAUDE.md`. Placeholders unfilled — no version file, `CHANGELOG.md`, or CI exists yet (pre-alpha). **Partial adoption until first release.** |

Not adopted:

- [code-checkin-and-pr](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/code-checkin-and-pr/README.md)
  — **open item, needs a decision before the first release.** `release-prep-and-cut`
  explicitly composes with this standard and assumes its `dev` → protected-`main` PR flow,
  commit-prefix conventions, and CI checks are in place. Without it, `/release-prep` has no
  defined branch strategy to run against. Resolve by either adopting it at `1.2.0` (what
  `filament-bridge` and `partfolder3d` both do) or defining a minimal branch rule here and
  recording the deviation.
- [repo-sandbox-permissions](https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/repo-sandbox-permissions/README.md)
  — this environment is not sandbox-provisioned.
