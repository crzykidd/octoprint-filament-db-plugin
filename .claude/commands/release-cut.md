---
description: Cut a GitHub release after the dev→main PR has merged and main CI is green
argument-hint: <version>   (e.g. 0.3.6 — must match what /release-prep prepared)
---

<!--
Template from standards/release-prep-and-cut @ v1.0.0
(crzynet/homelab-configs/standards/release-prep-and-cut/README.md).

Placeholders are RESOLVED for this project (octoprint-filament-db-plugin).

  octoprint_filamentdb/_version.py           octoprint_filamentdb/_version.py

  CI       "CI"  (.github/workflows/ci.yml -- Lint, Test on a
                           Python 3.9/3.13 matrix, Package build, Compose
                           validation, Config validation). "CodeQL" also runs on
                           push to main and must be green.

  <PUBLISH_WORKFLOW>       NONE. This project publishes no container images and
                           has no registry. It is an OctoPrint plugin: the
                           distributable is the sdist/wheel built by the Package
                           build job, and distribution is the OctoPrint Plugin
                           Repository, which lists a manifest pointing at the
                           GitHub release -- it does not host artefacts for us.

  <RELEASE_IMAGE_TAGS>     NONE -- see above. There is no image-publishing step
                           and no "point of no return for production images".
                           Publishing the GitHub release is still meaningful
                           (the tag is permanent and must never be re-cut), but
                           nothing is pushed to a registry.
-->

# Release Cut

You are publishing the GitHub release for **v$ARGUMENTS**. Run this ONLY
after:

- `/release-prep $ARGUMENTS` has merged into `main`, and
- the push-to-`main` **CI** and **CodeQL** workflows are green on the merge
  commit.

There is **no image-publish step** in this project — no registry, no
`:latest`. What makes this irreversible is the **tag**: it is permanent, and
the standard forbids re-tagging. Verify the version and the changelog section
before tagging, not after.

## Execution rules

- `$ARGUMENTS` SHOULD be bare semver (no `v` prefix). If a leading `v` was
  typed (`v0.3.6`), strip it silently. After stripping, if the value does
  not match `MAJOR.MINOR.PATCH` exactly, STOP and ask for a valid version.
- The bare value MUST equal the current version in `octoprint_filamentdb/_version.py` on
  `main`. If it does not, STOP.
- The release tag is `v$ARGUMENTS` (with the `v` prefix — matches the
  existing tag convention and the Docker `type=semver` extraction). Before
  calling `gh`, assert the tag string matches `^v[0-9]+\.[0-9]+\.[0-9]+$`
  exactly. If it does not, STOP — never create a malformed tag.
- Do NOT add `Co-authored-by` lines anywhere.
- If any verification step fails, STOP and report. Do not create the tag.

## Step 1 — Verify we are releasing the right commit

1. `git fetch origin` and check out `main`: `git checkout main && git pull`.
2. Confirm the version in `octoprint_filamentdb/_version.py` equals `$ARGUMENTS`. If not, the
   prep PR is not merged (or the wrong version was passed) — STOP.
3. Confirm the working tree is clean.
4. Confirm `git log` shows the `chore(release): prepare v$ARGUMENTS` commit on
   `main`. If absent, STOP — the PR has not been merged.

## Step 2 — Verify CI is green on main

Use `gh` to confirm the latest runs on `main` for this commit succeeded:

1. `gh run list --branch main --limit 10` and confirm the most recent runs
   for the release commit concluded `success` for BOTH `CI` and `CodeQL`.
2. If a run is still in progress, tell the user to wait and STOP — do not tag
   a commit whose checks have not finished.
3. If a run failed, STOP and report which job failed.

## Step 3 — Confirm the version tag does not already exist

`git tag -l "v$ARGUMENTS"` and `gh release view v$ARGUMENTS` — if either
exists, STOP and report. Never overwrite an existing release/tag.

## Step 4 — Assemble the release notes

Extract the `## [$ARGUMENTS] — <date>` section from `CHANGELOG.md` (everything
from that header up to, but not including, the next `## [` header). This is
the release body — the changelog is the single source of truth, matching the
PR description `/release-prep` created.

## Step 5 — Create the release

Write the extracted section to a temp file and pass it via `--notes-file`.
Create an annotated tag on the current `main` HEAD and publish the release in
one step with `gh`:

```
gh release create v$ARGUMENTS \
  --target main \
  --title "v$ARGUMENTS" \
  --notes-file <tmp>
```

Do not try to inline multi-line release notes.

## Step 6 — Verify the release artefacts

There is no image-publish workflow in this project. Instead:

1. Confirm the GitHub release for `v$ARGUMENTS` exists and its body matches the
   `CHANGELOG.md` section **verbatim** (`gh release view v$ARGUMENTS`).
2. Confirm the tag points at the intended `main` commit.
3. If the release is intended for the **OctoPrint Plugin Repository**, note that
   submission is a separate, manual step against that repository's own index —
   it is not automated here and must not be assumed to have happened.

## Step 7 — Report

Print:

- The release URL.
- The tag created (`v$ARGUMENTS`).
- Confirmation that the release body matches the CHANGELOG section verbatim.
- A reminder that **no images are published** — the artefacts are the sdist and
  wheel attached to / buildable from the tag, and that listing on the OctoPrint
  Plugin Repository, if wanted, is a separate manual submission.

Done — the release is live.
