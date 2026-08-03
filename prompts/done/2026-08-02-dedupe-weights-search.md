---
name: 2026-08-02-dedupe-weights-search
status: completed        # pending | completed | failed
created: 2026-08-02
model: sonnet            # coding — the approach is decided below, this is execution
completed: 2026-08-02
result: Deleted filamentdb-weights.js (weights.py is now sole implementation, called
  server-side and reaching the sidebar via AssignmentStore._decorate() plus api.py's
  list-endpoint serialization) and search.py + its pytest file (filamentdb-search.js is
  now sole implementation, covered by a Node-run test wired into pytest via a new
  Dockerfile.dev nodejs dependency). All five weight strings verified byte-identical in
  both sidebar and picker; 44/44 tests pass (54 before, net -11 old Python tests +1 new
  Node-wrapper test); zzz-* Filament DB test records deleted.
---

# Task: Remove the Python/JS duplication in weights and search

The spool-picker step left two pieces of logic implemented **twice** — once in Python with pytest
coverage, once as a hand-synced JavaScript port. **The JS is what actually renders the UI**, so the
54 passing tests cover code that largely does not run. A rounding change or a reworded degraded-path
string would pass every test and still be wrong on screen.

This is a **cleanup**: no new features, no behaviour change the user can see. Every rendered string
must be byte-identical before and after.

The two cases get **different** treatment, because the risk is different — a wrong weight corrupts
the user's sense of inventory, a wrong search rank is an annoyance.

## Before you start

1. **`CLAUDE.md`** — routing table and code-shape rules N-1…N-10.
2. **`docs/prd.md`** — **C-2** and **§Weight display** (the degraded paths), **FR-2** (the five-tier
   ranking, and that search must run client-side with no round-trip per keystroke).
3. **`docs/decisions.md`** — top entry, which records this duplication as a known follow-up.

## Working tree check

`git status --porcelain` first; if files this plan touches are dirty, list them and ask. This prompt
file is exempt. You are on **`dev`**; `main` is protected.

## What to do

### 1. Weights → server-side only. Delete the JS port.

The weight computation feeds inventory figures, so it gets the strict treatment: **one
implementation, the tested one.**

- **`api.py`: decorate spools with their computed weight** wherever spool data is returned to the
  frontend — the list/search endpoint as well as the assign response, which already does this.
  Each spool gains `weightText` and `weightPercent` from `weights.compute_weight(...)`.
- **Delete `octoprint_filamentdb/static/js/filamentdb-weights.js`** and drop it from
  `get_assets()`.
- **`filamentdb.js` and `filamentdb-picker.js` consume the server-provided fields** instead of
  computing. They should not contain weight arithmetic, rounding, or degraded-path strings at all.
- `weights.py` and `tests/test_weights.py` are unchanged and become the sole implementation.

The payload grows slightly. That is the intended trade: the client refetches on refresh anyway, and
the library is a single request with no pagination.

### 2. Search → JS is the single implementation. Delete `search.py`.

Search **must** stay client-side — FR-2 is explicit that there is no round-trip per keystroke, and
that is a UX requirement, not an implementation detail. So the JS is the real implementation, and
`search.py` is a shadow with **no runtime role**. A tested module that nothing calls is worse than
no module: it looks like coverage.

- **Delete `octoprint_filamentdb/search.py` and `tests/test_search_ranking.py`.**
- **Cover `filamentdb-search.js` directly** with a Node-run test, so the ranking that actually runs
  is the ranking that is tested.

**Make the JS test real, not skipped.** Node is **not** in the dev container (it is on the host), so
a test that silently skips would be no better than the shadow module. Add Node to `Dockerfile.dev`
so the whole suite runs in one place, and wire the JS test into `pytest` (a small test that shells
out to `node` and asserts on its output is fine — it keeps one command to run everything).

Port the existing ranking cases from `tests/test_search_ranking.py` before deleting it, so coverage
does not regress: all five tiers (exact `label` → exact `instanceId` → exact `_id` → `label` prefix
→ fuzzy), and that each result reports **why** it matched.

### 3. Update the routing table

`CLAUDE.md`'s table currently points at both implementations and explains the hand-sync. Replace
those rows with the single owner for each concern (N-8).

## Verify

1. `pytest` — all tests pass, **including the new Node-run search test actually executing rather
   than skipping.** State the test count before and after.
2. Container rebuild (Node is a new image dependency) and restart; clean load, no new errors or
   deprecation warnings.
3. **Playwright browser check — no console errors**, both idle and with a spool assigned. Deleting a
   JS file and changing what the viewmodels read is exactly the kind of change that breaks bindings
   silently.
4. **Behaviour is unchanged. Re-verify every rendered weight string against the previous run** —
   these must be byte-identical:

   | Case | Must still render |
   |---|---|
   | spool `#177` assigned | `169.4 g / 1000 g` |
   | tare null | `1042 g gross · tare not set` |
   | nominal null | `624.0 g` |
   | gross null | `not weighed` |
   | net exceeds nominal | `1050.0 g / 1000 g`, bar clamped at 100% |

   The degraded cases need `zzz-*` records again — **the dev Filament DB is a throwaway test
   instance and may be freely written to**; delete them afterwards.

   **Check the picker rows too, not just the sidebar** — the picker was a separate call site of the
   deleted JS, so it is the more likely regression.

5. Search `177` still returns it as the top hit, labelled an exact-label match.

**If a step fails, fix it. Do not report success with a caveat.** If genuinely blocked, stop and
report what and why.

## Conventions to honor

- `refactor:` prefix — this changes no behaviour.
- 500-line cap (N-1); OWNS / DOES NOT OWN docstrings (N-2); AGPLv3 headers on new files.
- `docker exec` needs `-i` for heredocs; `pip` in the container needs `PIP_USER=false`.
- If you conclude either half of this plan is wrong — e.g. server-side weights turn out to need a
  round-trip per row somewhere — **stop and report rather than half-doing it.** Leaving one
  implementation deduped and the other still forked is worse than either end state.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. Move it to `prompts/done/` (or `prompts/failed/`) — untracked, so plain `mv`.
3. Record non-obvious decisions in `docs/decisions.md`, newest at top.
4. **You are a spawned agent: do NOT commit.** Report the file list, a proposed one-line
   `refactor:` message, the before/after test counts, confirmation the Node test runs rather than
   skips, and **the five weight strings re-verified from both the sidebar and the picker**. Confirm
   the `zzz-*` records were deleted. Never `git add -A`, never push.
