---
name: 2026-08-02-spool-picker
status: completed        # pending | completed | failed
created: 2026-08-02
model: sonnet            # coding — design is settled, this is execution
completed: 2026-08-02
result: >
  Filament DB client, TTL cache, weight computation, assignment choke point, plugin API, and
  the spool picker/sidebar UI all built and verified live against crzydev.home.arpa:3000 --
  including the #177 inheritance/null-colour acceptance target and all five degraded-weight
  paths (data created and cleaned up). Found and fixed three real Knockout bugs (a double-fired
  click binding that could swallow the duplicate-assignment confirmation, a wrong
  printerProfilesViewModel property that always read tool count as 1, and a bare `color`
  reference throwing on unassigned rows) plus the deferred-import fix for standalone client/
  imports. 54 tests pass; container restarts clean.
---

# Task: Filament DB client + spool picker — assign a spool to a tool

Connect to Filament DB, let the user find and assign a spool per tool, and show it in the sidebar.
This is the first time the plugin talks to Filament DB at all.

Step 3 of the order in `prompts/startnewsession.md`. Steps 1 (skeleton) and 2 (live mm readout) are
done and committed.

## Before you start

Read, in this order:

1. **`CLAUDE.md`** — operational rules, routing table, code-shape rules N-1…N-10.
2. **`docs/prd.md`** — **FR-1** (connect), **FR-2** (browse/select, the ranked search),
   **C-2** (gross vs net), **C-3** (endpoints), **C-3b** (the seven fields we read),
   **C-4** (nullable density, inheritance), **C-7** (auth), and **§User interface**
   (sidebar layout, weight display, theming rules).
3. **`docs/decisions.md`** — top entries. Lessons that apply directly:
   - **Never cache `settingsViewModel.settings` in a viewmodel constructor.**
   - **UI work needs a real browser check.** A clean server log is not evidence the UI works.
   - **The offline-diff method**: pure modules can be exercised without the container.

## Working tree check

`git status --porcelain` first; if files this plan touches are dirty, list them and ask. This prompt
file is exempt. You are on **`dev`**; `main` is protected.

## Scope

**In scope:** the Filament DB client, caching, the plugin API, the assignment choke point, the
picker UI, and the sidebar rendering with computed weights.

**Explicitly OUT of scope — do not build:**

- mm→gram conversion of extrusion (`convert.py`). **The live readout stays in millimetres.**
- slicer metadata parsing, pre-print checks, the pre-print confirmation dialog
- the journal, retry, or any print-history write
- edit-spool (FR-15), NFC (FR-14), slot writeback (FR-11)
- `additional_state_data` / custom events

## What to do

### 1. `octoprint_filamentdb/client/filamentdb.py`

A `requests`-based client. **Imports nothing internal** (N-3) and must be unit-testable against a
mocked HTTP layer without OctoPrint.

| Method | Endpoint | Use |
|---|---|---|
| `list_filaments()` | `GET /api/filaments` | the picker — list projection, embedded spools |
| `get_spool(spool_id)` | `GET /api/spools/{spoolId}` | **an assigned spool** — returns `{filament, spool}` with the filament **inheritance-resolved** |
| `get_version()` | `GET /api/openapi` → `info.version` | Test Connection (there is no health endpoint) |

- Optional `Authorization: Bearer <key>` when the API key setting is set (C-7).
- Configurable timeout; **never** let a network error escape into OctoPrint's event loop.
- **`GET /api/spools/{spoolId}` is the read for an assigned spool**, not the parent filament —
  one call returns spool + inheritance-resolved filament, and we already hold the `spoolId`.
  **`diameter` is absent from the list projection**, so the picker cache alone is not sufficient.

### 2. Cache

In-memory, TTL from settings (default 5 min), plus a manual **Refresh**. One request fetches the
whole library; there is no pagination to use. Retain `spools[].instanceId` in the cached model —
v1 displays it, and it is the NFC resolution key later.

### 3. Assignment — one choke point

`assignment.set(tool_index, spool)` / `assignment.clear(tool_index)`. **Every** assign/clear routes
through these; do not write settings from several call sites. Records carry a **`source`** field
(`"manual"` for now) — an FR-11/FR-14 seam.

Must be **callable from a background thread** and push a UI update, for the same reason.

Persist per FR-2's `selectedSpools` shape. **Snapshot semantics matter later** (FR-7), so keep the
stored record self-sufficient: ids plus cached display fields.

### 4. Plugin API (`api.py`)

Endpoints for the frontend: list/search spools, assign, clear, test connection, force refresh.

- **Enforce permissions** (FR-10): `FILAMENTDB_SELECT` to view and assign, `FILAMENTDB_ADMIN` for
  settings. Do not leave endpoints unguarded.
- Blueprints are **CSRF-protected by default** in OctoPrint 2.0 (C-6).
- Never return the API key to the client.

### 5. Picker UI — a modal from the sidebar

Per FR-2. **One search box ranked by match quality — no mode switch:**

1. exact `label` → 2. exact `instanceId` → 3. exact `_id` → 4. `label` prefix →
5. fuzzy over vendor / name / type / colour / location

Each row shows **why it matched**. Search runs **client-side over the cache** — no request per
keystroke.

Filters: **material type** chips, **location**, **hide retired** (on by default).

**Sort:** FR-2 specifies "most recently used on this printer", sourced from the write journal —
**which does not exist yet**. For this step, sort by **`label` ascending** and leave a clear
`TODO(FR-9b)` at the sort site. Do not invent a substitute signal.

**Duplicate assignment warns, does not block** — show an "already on Tool N" badge and confirm.

### 6. Sidebar — replace the placeholder

Per §User interface: **fixed four-line rows**, everything optional in a hover tooltip.

```
▉ Tool 1                      [✕] [⋯]
  [PLA] PLA Galaxy Black (Prusament)
  842.0 g / 1000 g   ▓▓▓▓▓▓▓▓░░
  #177 · 970fdbcd56
```

`⋯` menu: **Open in Filament DB** →
`{FILAMENTDB_URL}/filaments/{filamentId}?spool={spoolId}` (spool-precise, opens in a new tab).
Bottom bar: **Refresh** and **Open Filament DB**. Keep the live millimetre readout from step 2.

**Weight is computed, not read** (C-2 / §Weight display):

```
net = spool.totalWeight − filament.spoolWeight     over filament.netFilamentWeight
```

Degraded paths — **never show gross as if it were net**, it overstates by the weight of the reel:

| Missing | Show |
|---|---|
| tare | `1042 g gross · tare not set` |
| nominal | `624 g` — no denominator, no bar |
| gross | `not weighed` |

Net may **exceed** nominal on overfilled reels: clamp the bar at 100%, never the figure.

**Warn at assignment time if the filament has no density** (FR-2/FR-6) — this needs only the spool,
no file. Do not implement the estimate itself; just surface the warning.

**No hardcoded colours** — Bootstrap 2 / OctoPrint classes only, so themes restyle us. The one
literal colour is the filament swatch, **and it can be `null`** — see the acceptance target below.

### 7. Small fix carried from step 2

`octoprint_filamentdb/__init__.py` imports `plugin.py`, which imports `octoprint` — so
`metering/odometer.py` cannot be imported standalone outside the container, weakening N-4. Make the
pure packages importable without OctoPrint installed (e.g. defer the plugin import). This directly
helps this step: `client/` should be unit-testable the same way.

### 8. Tests

- `tests/test_filamentdb_client.py` — mocked HTTP: bearer auth applied, 401, timeout, connection
  refused, malformed JSON. **No live network in tests.**
- `tests/test_weights.py` — the net computation and all three degraded paths, plus net-exceeds-
  nominal.
- `tests/test_search_ranking.py` — the five-tier ranking order.
- Keep the import-direction test green (N-3).

## Verify — against the live dev instance

Filament DB is at **`http://crzydev.home.arpa:3000`**, unauthenticated, **confirmed reachable from
inside the container** (63 filaments). Do not stand up a second instance.

1. `pytest` passes.
2. Container restart; clean load, no new errors or deprecation warnings.
3. **Test Connection** returns the Filament DB version.
4. **Playwright browser check** — no console errors, idle and with a spool assigned.
5. **Acceptance — assign spool `#177` to Tool 0.** Concrete expected values, read live:

   | | |
   |---|---|
   | label | `177` |
   | instanceId | `970fdbcd56` |
   | vendor / name | Amolen / Amolen PLA Matte Dual Color Green Purple |
   | type | PLA |
   | gross | 359.37 g |
   | tare | 190 g |
   | nominal | 1000 g |
   | **sidebar must show** | **169.4 g / 1000 g** (169.37 net) |

   Two things this specific spool deliberately exercises:
   - **It is a variant** (`parentId` set), so `density` (1.24) and `diameter` (1.75) must come back
     inheritance-resolved via `GET /api/spools/{spoolId}`. Confirm `diameter` is present —
     it is absent from the list projection, so getting 1.75 proves the detail path is used.
   - **Its `color` is `null`.** The swatch must render something sane and must not throw. Check
     the browser console specifically for this.

   **Re-read these values live before asserting.** The dev instance is actively being edited, so if
   the numbers have drifted, use the current ones and say so — the point is that
   `net = gross − tare` renders correctly, not these exact figures.

6. Search `177` returns it as the **top** hit, labelled as an exact-label match.
7. Assign it to a second tool and confirm the duplicate warning appears (temporarily raise the
   printer profile's extruder count if needed, then put it back to 1 — phase 1 is single-extruder).
8. Clear the assignment; sidebar returns to its empty state.

9. **Exercise the degraded weight paths — create the data, it does not exist naturally.**
   Every real spool in the library has gross, tare and nominal populated, so these branches are
   otherwise unreachable and would ship untested. **The dev Filament DB is a throwaway test
   instance and may be freely written to.** Create `zzz-*` filaments/spools via the API covering:

   | Case | Expected sidebar |
   |---|---|
   | `spoolWeight` (tare) null | `… g gross · tare not set` — **never** presented as net |
   | `netFilamentWeight` null | bare `… g`, no denominator, no bar |
   | `totalWeight` (gross) null | `not weighed` |
   | net **exceeds** nominal (overfilled reel) | true figure shown, bar clamped at 100% |
   | `density` null on a **root** filament | the assignment-time density warning fires |

   That last one matters: a null-density *variant* inherits from its parent and never reaches the
   fallback (C-4), so the record must be a root filament with no `parentId`.

   Delete the `zzz-*` records afterwards. Filament DB's DELETE is a soft-delete, so tombstones
   remain — that is expected and fine.

**If a step fails, fix it — do not report success with a caveat.** If genuinely blocked, stop and
report what and why.

## Conventions to honor

- `feat:` prefix. Update the **routing table in `CLAUDE.md`** for new modules (N-8).
- 500-line hard cap (N-1); OWNS / DOES NOT OWN docstrings (N-2); AGPLv3 headers.
- **All code original.** Prior art may be read and cited, never copied.
- `docker exec` needs `-i` for heredocs; `pip` in the container needs `PIP_USER=false`.
- **The dev Filament DB is a throwaway test instance and may be freely written to.** Step 9 of the
  verification requires creating records. Name anything you create `zzz-*` and delete it when done,
  purely so the library stays readable — not because the data is precious.
- If the PRD is *wrong* (not merely silent), stop and report rather than diverging.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. Move it to `prompts/done/` (or `prompts/failed/`) — it is untracked, so plain `mv`.
3. Record non-obvious decisions in `docs/decisions.md`, newest at top.
4. **You are a spawned agent: do NOT commit.** Report the file list, a proposed one-line `feat:`
   message, every verification result **including the exact weight string the sidebar rendered for
   #177 and for each of the five degraded cases in step 9**, and any decision the PRD did not
   cover. Confirm the `zzz-*` records were deleted. Never `git add -A`, never push.
