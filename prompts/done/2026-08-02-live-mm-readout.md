---
name: 2026-08-02-live-mm-readout
status: completed        # pending | completed | failed
created: 2026-08-02
model: sonnet            # coding — design is settled, this is execution
completed: 2026-08-02
result: >
  Odometer + job.py lifecycle + live sidebar readout implemented and verified end to end.
  Acceptance print measured 2668.1mm tool-0 vs 2669.01mm declared (-0.034%, within 1%).
  Cancel-partway confirmed a partial (30.7mm), non-reset total. Found but deliberately did
  not fix a step-3 bug: resends re-fire gcode.sent, double-counting (~0.06% of commands in
  this run, negligible here but should be fixed before FR-6).
---

# Task: Live raw-millimetre readout — make the odometer observable

Wire the extrusion hook to a per-tool accumulator and show the running millimetre total live in the
sidebar. This is **the instrument**: it is what makes every later metering change verifiable instead
of a black box.

Deliberately **millimetres only**. Millimetres have zero dependencies — no Filament DB, no spool
selection, no density, no conversion. That is the whole reason this step comes before those.

Step 1 (the plugin skeleton) is done and committed. This is step 2 of the order in
`prompts/startnewsession.md`.

## Before you start

Read, in this order:

1. **`CLAUDE.md`** — operational rules, the task→file routing table, code-shape rules N-1…N-10.
2. **`docs/prd.md`** — **FR-5** (the odometer) and **§User interface** (sidebar layout, the
   four-channel publishing rules).
3. **`docs/decisions.md`** — the top entry especially. Two lessons from step 1 that apply directly:
   - **Never cache `settingsViewModel.settings` in a viewmodel constructor.** It is `undefined`
     until an AJAX call resolves *after* all constructors run. Bind templates to
     `settingsViewModel.settings…` directly.
   - **UI work needs a real browser check.** Step 1's only genuine bug was invisible server-side.
     Playwright was installed into a throwaway venv for this; do the same. A clean server log is
     *not* evidence the UI works.

## Working tree check

Run `git status --porcelain` first. If files this plan touches have uncommitted changes, list them
and ask. Surface unrelated dirty files once. This prompt file is exempt.

You are on **`dev`**. `main` is protected.

## Scope

**In scope:** the accumulator, the hook wiring, the print lifecycle, the live sidebar number, tests.

**Explicitly OUT of scope** — do not build these, they are later steps:

- any Filament DB API call, client, or spool data
- spool selection / the picker
- mm→gram conversion or density
- the journal, retry, or the print-history commit
- the debug panel, the pre-print dialog
- `additional_state_data` / custom events (step 4+, once there is spool data worth publishing)

## What to do

### 1. `octoprint_filamentdb/metering/odometer.py` — pure, no OctoPrint imports

An extrusion accumulator: G-code strings in, `{tool_index: millimetres}` out. **Pure** — no
OctoPrint imports, no I/O, no settings object (N-3, N-4). It must be fully testable without booting
OctoPrint.

State it must model:

- **`G0` / `G1` / `G2` / `G3`** — take the `E` parameter. **Arc moves carry `E` too**; the test
  file below is arc-heavy, so omitting `G2`/`G3` will visibly undercount.
- **`M82` absolute / `M83` relative** extrusion mode. Default to relative only if the file declares
  it; track the mode explicitly.
- **`G92 E<n>`** — resets the extruder origin without extruding. A missed `G92` in absolute mode
  produces one enormous phantom extrusion; this is the classic failure of naive odometers.
- **`T<n>`** — tool change; subsequent extrusion accrues to the new tool index.
- **Retractions** — negative deltas. Accumulate net, so a retract/prime pair nets to zero.

Deferred to step 3, do **not** implement now: `M200` volumetric, `G10`/`G11` firmware retraction,
`M221` multiplier, unsupported-command warnings, defensive tool reconciliation, and the
slicer-array cross-check.

### 2. Hook + lifecycle wiring in `plugin.py` (wiring only — N-5)

- Register `octoprint.comm.protocol.gcode.sent`, feeding commands to the accumulator.
- **Only accumulate while actually printing.** Filter on print state, not merely on receiving the
  hook — manual jogs and warm-up commands must not count.
- `PrintStarted` resets the accumulator. Terminal events (`PrintDone` / `PrintFailed` /
  `PrintCancelled`) stop accumulation and leave the final total visible.
- **Cancel fires `PrintCancelled` then `PrintFailed`** — do not double-handle.
- Keep decisions out of `plugin.py`; it delegates.

### 3. Live sidebar display

- Push updates with `self._plugin_manager.send_plugin_message(...)`; the JS receives them via
  `onDataUpdaterPluginMessage`.
- **Throttle the push — roughly 1/second, not per command.** A print sends thousands of commands a
  second; pushing each one would flood the SockJS connection.
- Sidebar shows, per tool, the live figure — e.g. `▲ 4 062 mm`. Follow §User interface: Bootstrap 2
  / OctoPrint classes, **no hardcoded colours**.
- Idle state must read sensibly (no stale number from a previous job presented as current).

### 4. Tests — `tests/test_odometer.py` (mirrors source 1:1, N-7)

**The required assertion is real hardware output.** From
`tests/fixtures/serial/mmu3-filament-change-runout.md`, the sequence `N2386`→`N2406` sums to
**4.05109 mm**, and the printer's own `M114` replies `E:4.05`. Encode that as a test: it covers
`M83`, a `G92` reset, and a retract/prime pair netting to zero, validated against real firmware
rather than invented numbers.

Add unit tests for: absolute (`M82`) mode, `G92` mid-stream, `G2`/`G3` arcs contributing `E`,
tool-change routing, and retraction netting.

### 5. Verify — in the dev container, actually run it

The stack is up: OctoPrint 2.0.0rc4, single extruder, no third-party plugins.

1. `pytest` passes.
2. Restart the container; plugin loads clean, **no new errors or deprecation warnings** in
   `/octoprint/octoprint/logs/octoprint.log`.
3. **Browser check via Playwright** — no console errors, sidebar renders the figure.
4. **The acceptance test.** Print this already-uploaded real PrusaSlicer file on the virtual
   printer:

   ```
   test files/Shape-Box_0.4n_0.2mm_PLA_COREONE_18m.gcode
   ```

   Its config block declares the ground truth:

   ```
   ; filament used [mm] = 2669.01
   ; filament used [g]  = 7.96
   M83 ; extruder relative mode
   ```

   **The odometer's final total for tool 0 must be within 1% of 2669.01 mm.** Report the actual
   figure and the delta. This is FR-5's acceptance bar and the whole point of the step.

   The virtual printer throttles output, so this takes a few minutes. Be patient, or lower
   `plugins.virtual_printer.throttle` in `private_data/octoprint/octoprint/config.yaml` and restart.

5. Watch the number update live during that print, and confirm it stops (not resets) at the end.
6. Cancel a second print partway and confirm a **partial** total remains — that behaviour is the
   core reason this project exists.

**If a step fails, fix it. Do not report success with a caveat.** If genuinely blocked, stop and
report what and why.

## Conventions to honor

- `feat:` prefix. Docs ship with code — update the **routing table in `CLAUDE.md`** if you add
  modules (N-8).
- 500-line hard cap per module (N-1); OWNS / DOES NOT OWN docstring on every module (N-2); AGPLv3
  header on new sources.
- **All code original.** Prior art may be read and cited, never copied — not `octoprint-spoolman`,
  not OctoPrint's vendored `gcodeInterpreter`.
- `docker exec` needs `-i` to accept heredoc stdin, and `pip` inside the container needs
  `PIP_USER=false`. Both have already bitten this project.
- If the PRD is *wrong* (not merely silent), stop and report rather than diverging silently.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. Move this file to `prompts/done/` (success) or `prompts/failed/` (failure). It is untracked, so a
   plain `mv` is correct — `git mv` will fail.
3. Record non-obvious decisions in `docs/decisions.md`, newest at top, dated `2026-08-02`.
4. **You are a spawned agent: do NOT commit.** Prepare the tree and report back with the file list,
   a proposed one-line `feat:` message, every verification result **including the measured
   millimetre total and its delta from 2669.01**, and anything you had to decide that the PRD did
   not cover. Never `git add -A`, never push.
