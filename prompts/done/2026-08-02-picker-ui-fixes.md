---
name: 2026-08-02-picker-ui-fixes
status: completed        # pending | completed | failed
created: 2026-08-02
model: sonnet            # coding — fixes are specified, this is execution
completed: 2026-08-02
result: All five picker fixes landed and verified live (Playwright) -- widened modal with ellipsis
  guard, "169.4 / 359.4 g" scale-figure weight column, instanceId-prefix search tier, Match column
  hidden when not searching, and locationId resolved to names throughout. 46 pytest + 13 JS tests
  pass; all four degraded weight paths re-verified under the new format via zzz-* records, deleted
  after.
---

# Task: Fix five picker UI issues found in real use

Five problems reported after actually assigning a spool. Two are functional bugs, one is a display
bug, two are layout. All are small and independent.

**Run this AFTER `2026-08-02-dedupe-weights-search.md` has landed** — that task rewrites
`filamentdb-search.js` and `filamentdb-picker.js`, which this one also touches.

## Before you start

1. **`CLAUDE.md`** — routing table, code-shape rules.
2. **`docs/prd.md`** — **FR-2** (the picker, the five-tier search), **C-3b** (the fields we read),
   **§User interface** (theming rules — no hardcoded colours).
3. **`docs/decisions.md`** — top entries.

## Working tree check

`git status --porcelain` first. This prompt file is exempt. You are on **`dev`**; `main` is
protected.

## The five fixes

### 1. The filament line wraps to 6+ lines — widen the modal

`[TYPE] Name (Vendor)` overflows badly in the narrow picker. Real example:
`[PLA] Amolen PLA Matte Dual Color Green Purple (Amolen)`.

**Widen the picker modal** so a typical filament name fits on one line.

Additionally, as an **overflow guard only**: clip anything still too long with an ellipsis and put
the full text in a `title` tooltip. This is not a second design — it exists so a pathological name
can never wrap to six lines again. **Rows must stay uniform height.**

### 2. Weight column: drop the nominal, add the scale figure

Currently `169.4 g / 1000 g`. Every filament in the library has a 1000 g nominal, so that half of
the ratio carries almost no information while costing width.

Show **net remaining and expected gross** — the number you would actually read off a scale:

```
169.4 / 359.4 g
```

- **No parentheses, no "on scale" text** — the numbers alone.
- **The column header carries the meaning**: `Remaining / Scale`. Meaning belongs in the header, not
  repeated on every row.
- Expected gross = `net + tare`, i.e. the spool's stored `totalWeight`. Use the stored gross
  directly rather than recomputing it from net.
- **The degraded paths still apply** (C-2 / §Weight display). When tare is unknown there is no net,
  so keep rendering `1042 g gross · tare not set`; when gross is unknown, `not weighed`. Do not
  invent a scale figure you cannot compute.

**This is the picker column.** Leave the sidebar's own weight display alone unless the same change
obviously applies — the sidebar has room and a different job.

### 3. BUG: the hex identifier is not searchable

Confirmed by running the ranking directly:

```
"177"          → exact_label          ✓
"970fdbcd56"   → exact_instance_id    ✓   full hex works
"970fdb"       → NO MATCH             ✗
"970"          → NO MATCH             ✗
```

`instanceId` is matched **only on a full 10-character exact hit**, and `fuzzyHit()` does not include
it. Nobody types ten hex characters, so in practice the identifier is unsearchable.

**Add an `instanceId` prefix tier**, ranked **above** fuzzy text: a hex prefix is a deliberate
identifier search, so it should outrank an incidental substring hit in a vendor name. Suggested
order, extending FR-2's five tiers:

```
exact label → exact instanceId → exact _id → label prefix
            → instanceId prefix → fuzzy
```

Update the tier constants, the JS test cases, and FR-2 in the PRD to match — the PRD currently
documents five tiers and will now be six.

### 4. BUG: the Match column is empty for every row

The "why it matched" column is blank when browsing, because ranking only runs when there is a query
— with an empty box the rows come from a different path and carry no tier.

**Hide the Match column entirely when there is no active query**, and show it only while searching.
An always-present column that is always empty reads as broken.

Verify it populates correctly *during* a search: searching `177` must show that row as an exact
label match, and `amolen` must show fuzzy hits.

### 5. BUG: the location filter shows GUIDs

The dropdown lists raw `locationId` values like `6a385c81a66ab307b7f9b5d3`. Filament DB exposes
`GET /api/locations` returning `{_id, name, …}` — 12 real locations with names like `Bin 1 - PLA`,
`Bin 2 - PETG`, `Bagged`.

- Fetch locations (cache them alongside the filament list; they change rarely) and **resolve
  `locationId` → name** everywhere a location is shown — the filter dropdown and the row/tooltip.
- **This also fixes a silent second bug:** `fuzzyHit()` already searches a `row.locationName` field
  that is never populated, so location text search has never matched anything. Populating it makes
  that work.
- Unknown or missing `locationId` must degrade gracefully — show nothing, not a raw GUID and not
  `undefined`.

**Scope note:** this adds a Filament DB read beyond C-3b's list. Update **C-3b** to record that the
plugin also reads `GET /api/locations` for display names. Keep it to that — do not start syncing,
editing, or otherwise expanding into location management.

## Verify

Filament DB: `http://crzydev.home.arpa:3000`, reachable from the container, throwaway test instance
you may write to.

1. `pytest` — all pass, including the Node-run search tests, with new cases for the instanceId
   prefix tier.
2. Container restart; clean load, no new errors or deprecation warnings.
3. **Playwright browser check — no console errors.** Every one of these fixes touches Knockout
   bindings, and each of the last three steps had a real bug that only a browser check caught.
4. Open the picker and confirm, with screenshots:
   - the filament line for `Amolen PLA Matte Dual Color Green Purple` sits on **one line**
   - the weight column reads `169.4 / 359.4 g` for `#177`, under a `Remaining / Scale` header
   - the location filter lists **names** (`Bin 1 - PLA`, …), not GUIDs
   - the Match column is **absent** with an empty search box
5. Search behaviour, reporting the tier for each:
   - `177` → top hit, exact label
   - `970fdbcd56` → exact instanceId
   - `970fdb` → **now matches**, instanceId prefix
   - `amolen` → fuzzy
   - a location name, e.g. `Bin 1` → **now matches** via the populated `locationName`
6. Re-check the degraded weight paths still render correctly with the new column format (`zzz-*`
   records; delete them after).

**If a step fails, fix it. Do not report success with a caveat.**

## Conventions to honor

- `fix:` prefix — these are bug fixes plus small UI corrections.
- 500-line cap (N-1); OWNS / DOES NOT OWN docstrings (N-2).
- **No hardcoded colours** — Bootstrap 2 / OctoPrint classes so themes restyle us.
- Update the **PRD** where behaviour changed: FR-2's tier list (five → six) and C-3b's field list
  (add the locations read). Update `CLAUDE.md`'s routing table if modules change (N-8).
- `docker exec` needs `-i`; `pip` in the container needs `PIP_USER=false`.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. Move it to `prompts/done/` (or `prompts/failed/`) — untracked, so plain `mv`.
3. Record non-obvious decisions in `docs/decisions.md`, newest at top.
4. **You are a spawned agent: do NOT commit.** Report the file list, a proposed one-line `fix:`
   message, all verification results **including the tier reported for each of the five search
   queries** and the exact weight string rendered for `#177`. Confirm `zzz-*` records were deleted.
   Never `git add -A`, never push.
