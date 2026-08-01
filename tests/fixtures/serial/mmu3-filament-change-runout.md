# Serial capture — MMU3 filament change after a jam/runout

**Captured:** 2026-08-01, from a real Prusa MK3-class printer with MMU (MMU2/3 firmware messages),
mid-print, single-material job. Relative extrusion (`M83`). PrusaSlicer-sliced, arc-heavy
(`G2`/`G3`).

This is the reference fixture for FR-12 (changeover detection) and a regression fixture for FR-5
(the odometer). **It is real hardware output, not synthetic** — prefer it over invented data.

## Why this capture matters

Six findings, each with a design consequence. See `docs/decisions.md` (2026-08-01, "MMU filament
change is invisible…") for the reasoning.

1. **No `M600` anywhere in the outgoing stream.** The entire changeover is firmware/MMU driven.
   Anything watching for `M600` in `gcode.sent` sees nothing.
2. **No `// action:` commands at all.** OctoPrint's native action-command handling never fires, so
   `octoprint.comm.protocol.action` is not a usable signal here.
3. **The outgoing stream simply stops.** The last command before the event is `N2419`; the next is
   `N2448`. In between there are only `Recv:` lines — `echo:busy: processing` repeating while the
   firmware handles everything itself. OctoPrint is blocked on flow control, not paused.
4. **Rich `echo:MMU2:` messages *are* available** — the most reliable signal present.
5. **Firmware-driven E movement is invisible to the odometer.** See the E-axis trace below.
6. **Relative-E accumulation is confirmed exactly** against the firmware's own `M114`. See below.

## E-axis trace — validates the odometer model

Between `N2386` and `N2406` the arithmetic can be checked against firmware ground truth:

| Line | Command | Running E (relative) |
|---|---|---|
| N2386 | `G92 E0.0` | 0.0 — *confirmed by `Recv: … E:0.00`* |
| N2387 | `G1 E-.7` | −0.7 |
| N2392 | `G1 E.7` | 0.0 |
| N2395 | `E.94513` | 0.94513 |
| N2396 | `E.94509` | 1.89022 |
| N2397 | `E.94513` | 2.83535 |
| N2398 | `E.94306` | 3.77841 |
| N2403 | `E.97268` | 4.75109 |
| N2404 | `G1 E-0.70000` | 4.05109 |
| N2406 | `M114` | **`Recv: … E:4.05`** ✅ exact match |

**This validates the FR-5 accumulation model against real firmware**: relative mode, `G92` reset
handling, and retract/prime netting to zero all behave as specified. Use this as a unit-test
assertion.

## The invisible extrusion

During the MMU event the firmware reports its parked position:

```
Recv: X:202.00 Y:-13.00 Z:64.97 E:9.67 Count A:18900 B:21499 Z:25982
```

E has moved **4.05 → 9.67 = +5.62 mm with no host-issued command**. That is the MMU
unload/retract/eject sequence, executed entirely by the printer.

Mass impact here is negligible — ~5.62 mm of 1.75 mm filament ≈ **0.017 g** — but the *principle*
matters: firmware can move the extruder without the host seeing it, and a full multi-material tool
change with ramming would be far larger. The odometer under-counts by exactly this amount, always
in the same direction.

## The MMU event, in order

```
echo:MMU2:Unloading to FINDA
echo:MMU2:Disengaging idler
echo:MMU2:Command Error
echo:MMU2:FSENSOR FIL. STUCK      ← the actual fault
RetryButtonPressed                 ← user pressed a button ON THE PRINTER
CheckUserInput-btnLMR 1
echo:MMU2:Button
DecrementRetryAttempts
echo:MMU2:Unloading to FINDA
echo:MMU2:Retract from FINDA
echo:MMU2:Disengaging idler
ResetRetryAttempts
echo:MMU2:Parking selector
echo:MMU2:Engaging idler
echo:MMU2:Ejecting filament
echo:MMU2:Disengaging idler
echo:MMU2:Command Error
echo:MMU2:FILAMENT EJECTED        ← spool is now out
echo:MMU2:Saving and parking
echo:MMU2:Heater cooldown pending
echo:MMU2:Cooling Timeout started
echo:MMU2:Command Error            (repeats many times while waiting for the user)
```

Then the user loads the new filament and the print resumes at `N2448` with normal extrusion.

## Still to verify (cannot be determined from this capture alone)

- **Did OctoPrint fire `PrintPaused`?** Nothing here proves it did, and finding 3 suggests it may
  not have. Needs the OctoPrint event log or a plugin-side event trace from the same event.
- What the user-visible OctoPrint popup was, and which subsystem raised it.

---

## Raw capture — part 1: printing, then the MMU fault

```
Send: N2324 G2 X129.954 Y114.314 I-.206 J-2.498 E.06881*81
Recv: ok
Send: N2325 G3 X131.701 Y113.493 I1.745 J1.444 E.0675*91
Recv: ok
Send: N2326 G3 X133.448 Y114.42 I-.206 J2.498 E.06881*68
Recv: ok
Send: N2327 G2 X134.833 Y115.217 I1.798 J-1.522 E.05518*78
Recv: ok
Send: N2328 G1 X134.833 Y118.687 E.11746*99
Recv: ok
Send: N2329 G3 X133.448 Y117.808 I.672 J-2.59 E.05643*67
Recv: ok
Send: N2330 G2 X131.701 Y116.987 I-1.745 J1.444 E.0675*126
Recv: ok
Send: N2331 G2 X129.954 Y117.914 I.206 J2.498 E.06881*92
Recv: ok
Send: N2332 G3 X128.207 Y118.736 I-1.745 J-1.443 E.06751*103
Recv: ok
Send: N2333 G3 X126.46 Y117.808 I.206 J-2.498 E.06883*73
Recv: ok
Send: N2334 G2 X124.713 Y116.987 I-1.745 J1.444 E.0675*125
Recv: ok
Send: N2335 G2 X122.966 Y117.914 I.206 J2.498 E.06881*82
Recv: ok
Send: N2336 G3 X121.218 Y118.736 I-1.745 J-1.443 E.06755*96
Recv:  T:224.85/225.00 B:59.47/60.00 X:35.18/36.00 A:46.90/0.00 @:146 B@:101 C@:28.23 HBR@:58
Recv: ok
Send: N2337 G3 X119.471 Y117.808 I.207 J-2.498 E.06883*112
Recv: ok
Send: N2338 G2 X117.724 Y116.987 I-1.745 J1.444 E.0675*117
Recv: ok
Send: N2339 G2 X115.977 Y117.914 I.206 J2.498 E.06881*90
Recv: ok
Send: N2340 G3 X114.23 Y118.736 I-1.745 J-1.443 E.06751*89
Recv: ok
Send: N2341 G3 X112.483 Y117.808 I.206 J-2.498 E.06883*118
Recv: ok
Send: N2342 G2 X110.736 Y116.987 I-1.745 J1.444 E.0675*124
Recv: ok
Send: N2343 G2 X108.989 Y117.914 I.206 J2.498 E.06881*90
Recv: ok
Send: N2344 G3 X107.604 Y118.711 I-1.798 J-1.521 E.05518*96
Recv: ok
Send: N2345 G1 X107.604 Y122.181 E.11746*106
Recv: ok
Send: N2346 G2 X108.989 Y121.303 I-.672 J-2.59 E.05641*105
Recv: ok
Send: N2347 G3 X110.736 Y120.481 I1.745 J1.443 E.06751*109
Recv: ok
Send: N2348 G3 X112.483 Y121.409 I-.206 J2.498 E.06883*119
Recv: ok
Send: N2349 G2 X114.23 Y122.23 I1.745 J-1.444 E.0675*112
Recv: ok
Send: N2350 G2 X115.977 Y121.303 I-.206 J-2.498 E.06881*92
Recv: ok
Send: N2351 G3 X117.724 Y120.481 I1.745 J1.443 E.06751*110
Recv: ok
Send: N2352 G3 X119.471 Y121.409 I-.206 J2.498 E.06883*122
Recv: ok
Send: N2353 G2 X121.218 Y122.23 I1.745 J-1.444 E.0675*71
Recv: ok
Send: N2354 G2 X122.966 Y121.303 I-.206 J-2.498 E.06885*88
Recv: ok
Send: N2355 G3 X124.713 Y120.481 I1.745 J1.443 E.06751*110
Recv: ok
Send: N2356 G3 X126.46 Y121.409 I-.206 J2.498 E.06883*66
Recv: ok
Send: N2357 G2 X128.207 Y122.23 I1.745 J-1.444 E.0675*68
Recv: ok
Send: N2358 G2 X129.954 Y121.303 I-.206 J-2.498 E.06881*90
Recv: ok
Send: N2359 G3 X131.701 Y120.481 I1.745 J1.443 E.06751*101
Recv: ok
Send: N2360 G3 X133.448 Y121.409 I-.206 J2.498 E.06883*121
Recv: ok
Send: N2361 G2 X134.833 Y122.206 I1.798 J-1.522 E.05518*72
Recv: ok
Send: N2362 G1 X134.833 Y125.675 E.11742*106
Recv: ok
Send: N2363 G3 X133.448 Y124.797 I.672 J-2.59 E.05641*70
Recv: ok
Send: N2364 M73 P15 R15*38
Recv: ok
Send: N2365 G2 X131.701 Y123.976 I-1.745 J1.443 E.0675*113
Recv: ok
Send: N2366 G2 X129.954 Y124.903 I.206 J2.498 E.06881*88
Recv: ok
Send: N2367 G3 X128.207 Y125.724 I-1.745 J-1.444 E.0675*92
Recv: ok
Send: N2368 G3 X126.46 Y124.797 I.206 J-2.498 E.06881*76
Recv: ok
Send: N2369 G2 X124.713 Y123.976 I-1.745 J1.443 E.0675*122
Recv: ok
Send: N2370 G2 X122.966 Y124.903 I.206 J2.498 E.06881*85
Recv: ok
Send: N2371 G3 X121.218 Y125.724 I-1.745 J-1.444 E.06753*111
Recv: ok
Send: N2372 G3 X119.471 Y124.797 I.207 J-2.498 E.06881*122
Recv: ok
Send: N2373 G2 X117.724 Y123.976 I-1.745 J1.443 E.0675*117
Recv: ok
Send: N2374 G2 X115.977 Y124.903 I.206 J2.498 E.06881*85
Recv: ok
Send: N2375 G3 X114.538 Y125.703 I-1.745 J-1.444 E.05703*107
Recv: ok
Send: N2376 G1 F11054*79
Recv: ok
Send: N2377 G3 X114.23 Y125.724 I-.306 J-2.244 E.01047*103
Recv: ok
Send: N2378 G3 X112.483 Y124.797 I.206 J-2.498 E.06881*119
Recv: ok
Send: N2379 G2 X110.736 Y123.976 I-1.745 J1.443 E.0675*123
Recv: ok
Send: N2380 G2 X108.989 Y124.903 I.206 J2.498 E.06881*83
Recv: ok
Send: N2381 G3 X107.604 Y125.7 I-1.798 J-1.522 E.05518*100
Recv: ok
Send: N2382 G1 X107.604 Y126.235 E.01811*101
Recv: ok
Send: N2383 G1 X109.069 Y126.235 E.04959*111
Recv: ok
Send: N2384 M204 P3000*107
Recv: ok
Send: N2385 M117 29% L=10/100*88
Recv: ok
Send: N2386 G92 E0.0*102
Recv: X:109.07 Y:126.24 Z:1.80 E:0.00 Count A:24091 B:-833 Z:1007
Recv: ok
Send: N2387 G1 E-.7 F2700*36
Recv: ok
Send: N2388 G1 X109.069 Y126.235 Z1.8 F21000*22
Recv: ok
Send: N2389 G1 X107.258 Y126.581 Z2 F6676.326*47
Recv: ok
Send: N2390 G1 X107.258 Y126.581 F21000*68
Recv: ok
Send: N2391 G1 Z2 F720*10
Recv: ok
Send: N2392 G1 E.7 F1500*12
Recv: ok
Send: N2393 M204 P6000*104
Recv: ok
Send: N2394 G1 F3567*117
Recv: ok
Send: N2395 G1 X107.258 Y98.659 E.94513*87
Recv: ok
Send: N2396 G1 X135.179 Y98.659 E.94509*94
Recv: ok
Send: N2397 G1 X135.179 Y126.581 E.94513*102
Recv: ok
Send: N2398 G1 X107.318 Y126.581 E.94306*111
Recv: ok
Send: N2399 M204 P3000*103
Recv: ok
Send: N2400 G1 X106.851 Y126.988 F21000*77
Recv: ok
Send: N2401 M204 P6000*100
Recv: ok
Send: N2402 G1 F10200*73
Recv: ok
Send: N2403 G1 X106.851 Y98.252 E.97268*90
Recv: ok
Send: N2404 G1 E-0.70000 F2100.000*0
Recv:  T:224.92/225.00 B:59.44/60.00 X:35.34/36.00 A:46.97/0.00 @:144 B@:103 C@:28.23 HBR@:55
Recv: ok
Send: N2405 M400*20
Recv:  T:225.02/225.00 B:59.48/60.00 X:35.08/36.00 A:46.94/0.00 @:140 B@:102 C@:28.23 HBR@:55
Recv: echo:busy: processing
Recv: ok
Send: N2406 M114*23
Recv: X:106.85 Y:98.25 Z:2.00 E:4.05 Count A:20510 B:859 Z:1046
Recv: ok
Send: N2407 G1 E0.70000*85
Recv: ok
Send: N2408 G1 F10200.000*93
Recv: ok
Send: N2409 G1 X135.586 Y98.252 E.97264*91
Recv: ok
Send: N2410 G1 X135.586 Y126.988 E.97268*103
Recv: ok
Send: N2411 G1 X106.911 Y126.988 E.97061*111
Recv: ok
Send: N2412 M204 P3000*99
Recv: ok
Send: N2413 G1 X106.443 Y127.395 F21000*71
Recv: ok
Send: N2414 G1 F10199.987*85
Recv: ok
Send: N2415 G1 X106.443 Y97.845 E1.00023*99
Recv: ok
Send: N2416 G1 X135.993 Y97.845 E1.00023*96
Recv: ok
Send: N2417 G1 X135.993 Y127.395 E1.00023*93
Recv: ok
Send: N2418 G1 X106.503 Y127.395 E.9982*93
Recv: ok
Send: N2419 G1 X106.444 Y127 F21000*91
Recv:  T:224.96/225.00 B:59.55/60.00 X:35.20/36.00 A:47.01/0.00 @:144 B@:99 C@:28.23 HBR@:55
Recv: echo:busy: processing
Recv:  T:224.94/225.00 B:59.53/60.00 X:35.28/36.00 A:47.07/0.00 @:146 B@:100 C@:28.13 HBR@:55
Recv: echo:busy: processing
Recv:  T:225.08/225.00 B:59.53/60.00 X:35.28/36.00 A:47.10/0.00 @:140 B@:101 C@:28.23 HBR@:55
Recv: echo:busy: processing
Recv:  T:225.40/225.00 B:59.52/60.00 X:35.27/36.00 A:47.02/0.00 @:129 B@:103 C@:28.23 HBR@:55
Recv: echo:busy: processing
Recv: X:202.00 Y:-13.00 Z:64.97 E:9.67 Count A:18900 B:21499 Z:25982
Recv:  T:225.68/225.00 B:59.60/60.00 X:35.26/36.00 A:47.10/0.00 @:0 B@:99 C@:28.23 HBR@:55
Recv: echo:busy: processing
Recv:  T:225.78/225.00 B:59.59/60.00 X:35.41/36.00 A:47.11/0.00 @:0 B@:101 C@:28.33 HBR@:55
Recv: echo:busy: processing
Recv:  T:225.04/225.00 B:59.65/60.00 X:35.71/36.00 A:47.10/0.00 @:21 B@:97 C@:28.23 HBR@:64
Recv: echo:busy: processing
Recv:  T:223.69/225.00 B:59.76/60.00 X:36.02/36.00 A:47.11/0.00 @:66 B@:92 C@:28.03 HBR@:78
Recv: echo:busy: processing
Recv:  T:222.12/225.00 B:59.83/60.00 X:36.20/36.00 A:47.08/0.00 @:112 B@:89 C@:27.93 HBR@:76
Recv: echo:busy: processing
Recv: echo:MMU2:Unloading to FINDA
Recv:  T:220.97/225.00 B:59.97/60.00 X:36.29/36.00 A:47.07/0.00 @:133 B@:82 C@:27.93 HBR@:86
Recv: echo:busy: processing
Recv:  T:220.47/225.00 B:60.05/60.00 X:36.33/36.00 A:47.12/0.00 @:133 B@:78 C@:27.73 HBR@:91
Recv: echo:busy: processing
Recv: echo:MMU2:Disengaging idler
Recv:  T:220.53/225.00 B:60.17/60.00 X:36.55/36.00 A:47.14/0.00 @:119 B@:71 C@:27.63 HBR@:92
Recv: echo:MMU2:Command Error
Recv: echo:MMU2:FSENSOR FIL. STUCK
Recv: RetryButtonPressed
Recv: echo:busy: processing
Recv: CheckUserInput-btnLMR 1
Recv: echo:MMU2:Button
Recv: DecrementRetryAttempts
Recv: echo:MMU2:Unloading to FINDA
Recv:  T:221.02/225.00 B:60.29/60.00 X:36.40/36.00 A:47.08/0.00 @:101 B@:65 C@:27.52 HBR@:91
Recv: echo:busy: processing
Recv:  T:221.63/225.00 B:60.34/60.00 X:36.66/36.00 A:47.15/0.00 @:86 B@:62 C@:27.42 HBR@:103
Recv: echo:busy: processing
Recv:  T:222.06/225.00 B:60.41/60.00 X:36.64/36.00 A:47.16/0.00 @:83 B@:59 C@:27.32 HBR@:106
Recv: echo:busy: processing
Recv:  T:222.18/225.00 B:60.49/60.00 X:36.75/36.00 A:47.12/0.00 @:94 B@:54 C@:27.22 HBR@:108
Recv: echo:busy: processing
Recv: echo:MMU2:Retract from FINDA
Recv: echo:MMU2:Disengaging idler
Recv:  T:222.29/225.00 B:60.51/60.00 X:36.85/36.00 A:47.15/0.00 @:101 B@:52 C@:27.22 HBR@:103
Recv: echo:busy: processing
Recv:  T:222.37/225.00 B:60.58/60.00 X:36.79/36.00 A:47.14/0.00 @:107 B@:48 C@:27.12 HBR@:109
Recv: echo:busy: processing
Recv:  T:222.46/225.00 B:60.53/60.00 X:36.81/36.00 A:47.15/0.00 @:111 B@:51 C@:27.11 HBR@:119
Recv: ResetRetryAttempts
Recv: echo:MMU2:Parking selector
Recv: echo:busy: processing
Recv: echo:MMU2:Engaging idler
Recv:  T:222.67/225.00 B:60.58/60.00 X:37.10/36.00 A:47.16/0.00 @:111 B@:47 C@:27.01 HBR@:118
Recv: echo:busy: processing
Recv: echo:MMU2:Ejecting filament
Recv:  T:223.09/225.00 B:60.58/60.00 X:36.93/36.00 A:47.14/0.00 @:102 B@:46 C@:26.91 HBR@:117
Recv: echo:busy: processing
Recv: echo:MMU2:Disengaging idler
Recv:  T:223.39/225.00 B:60.63/60.00 X:37.17/36.00 A:47.15/0.00 @:101 B@:42 C@:26.80 HBR@:123
Recv: echo:MMU2:Command Error
Recv: echo:MMU2:FILAMENT EJECTED
Recv: echo:MMU2:Saving and parking
Recv: echo:MMU2:Heater cooldown pending
Recv: echo:MMU2:Cooling Timeout started
Recv: echo:MMU2:Command Error
   [... "echo:MMU2:Command Error" repeats many times, interleaved with
        "echo:busy: processing" and temperature reports, while the printer
        waits for the user to load new filament ...]
```

## Raw capture — part 2: resumed after loading new filament

```
Recv: ok
Send: N2448 G3 X128.644 Y122.128 I-2.896 J-2.329 E.05693*104
Recv: ok
Send: N2449 G3 X126.46 Y121.615 I-.732 J-1.792 E.081*109
Recv: ok
Send: N2450 G2 X125.149 Y120.583 I-2.897 J2.329 E.05696*73
Recv: ok
Send: N2451 G2 X122.966 Y121.096 I-.731 J1.792 E.08096*119
Recv: ok
Send: N2452 G3 X121.655 Y122.128 I-2.897 J-2.329 E.05696*110
Recv: ok
Send: N2453 G3 X119.471 Y121.615 I-.731 J-1.792 E.081*89
Recv: ok
Send: N2454 G2 X118.161 Y120.583 I-2.896 J2.329 E.05693*77
Recv: ok
Send: N2455 G2 X115.977 Y121.096 I-.731 J1.792 E.081*121
Recv: ok
Send: N2456 G3 X114.667 Y122.128 I-2.896 J-2.329 E.05693*105
Recv: ok
Send: N2457 G3 X112.483 Y121.615 I-.732 J-1.792 E.081*88
Recv: ok
Send: N2458 G2 X111.173 Y120.583 I-2.896 J2.329 E.05693*75
Recv: ok
Send: N2459 G2 X108.989 Y121.096 I-.732 J1.792 E.081*123
Recv: ok
Send: N2460 G3 X107.604 Y122.148 I-2.69 J-2.103 E.05953*92
Recv: ok
Send: N2461 G1 X107.604 Y118.772 E.11427*108
Recv: ok
Send: N2462 G2 X108.989 Y118.121 I-.031 J-1.863 E.05338*88
Recv: ok
Send: N2463 G3 X110.299 Y117.089 I2.896 J2.329 E.05693*98
Recv: ok
Send: N2464 G3 X112.483 Y117.602 I.731 J1.792 E.081*88
Recv: ok
Send: N2465 G2 X113.793 Y118.634 I2.896 J-2.329 E.05693*75
Recv: ok
Send: N2466 G2 X115.977 Y118.121 I.732 J-1.792 E.081*125
Recv: ok
Send: N2467 G3 X117.287 Y117.089 I2.896 J2.329 E.05693*110
Recv: ok
Send: N2468 G3 X119.471 Y117.602 I.732 J1.792 E.081*81
Recv: ok
Send: N2469 G2 X120.782 Y118.634 I2.897 J-2.329 E.05696*67
Recv: ok
Send: N2470 G2 X122.966 Y118.121 I.731 J-1.792 E.081*125
Recv: ok
Send: N2471 G3 X124.276 Y117.089 I2.896 J2.329 E.05693*103
Recv: ok
Send: N2472 G3 X126.46 Y117.602 I.731 J1.792 E.081*101
Recv: ok
Send: N2473 G2 X127.77 Y118.634 I2.896 J-2.329 E.05693*118
Recv: ok
Send: N2474 G2 X129.954 Y118.121 I.731 J-1.792 E.081*115
Recv:  T:230.44/225.00 B:60.06/60.00 X:36.17/36.00 A:47.46/0.00 @:113 B@:53 C@:26.58 HBR@:206
Recv: ok
Send: N2475 G3 X131.264 Y117.089 I2.896 J2.329 E.05693*100
Recv: ok
Send: N2476 G3 X133.448 Y117.602 I.732 J1.792 E.081*92
Recv: ok
Send: N2477 G2 X134.833 Y118.654 I2.69 J-2.104 E.05953*120
Recv: ok
Send: N2478 G1 X134.833 Y115.278 E.11427*108
Recv: ok
Send: N2479 G3 X133.448 Y114.627 I.031 J-1.863 E.05338*123
Recv: ok
Send: N2480 G2 X132.138 Y113.595 I-2.896 J2.329 E.05693*71
Recv: ok
Send: N2481 G2 X129.954 Y114.107 I-.732 J1.791 E.08099*112
Recv: ok
Send: N2482 G3 X128.644 Y115.14 I-2.896 J-2.328 E.05695*83
Recv: ok
Send: N2483 G3 X126.46 Y114.627 I-.732 J-1.792 E.081*108
Recv: ok
Send: N2484 G2 X125.149 Y113.595 I-2.896 J2.329 E.05696*70
Recv: ok
Send: N2485 G2 X122.966 Y114.107 I-.731 J1.791 E.08095*113
Recv: ok
Send: N2486 G3 X121.655 Y115.14 I-2.897 J-2.328 E.05698*82
Recv: ok
Send: N2487 G3 X119.471 Y114.627 I-.731 J-1.792 E.081*87
Recv: ok
Send: N2488 G2 X118.161 Y113.595 I-2.896 J2.329 E.05693*75
Recv: ok
Send: N2489 G2 X115.977 Y114.107 I-.731 J1.791 E.08099*117
Recv: ok
Send: N2490 G3 X114.667 Y115.14 I-2.896 J-2.328 E.05695*94
Recv: ok
Send: N2491 G3 X112.483 Y114.627 I-.732 J-1.792 E.081*85
Recv: ok
Send: N2492 G2 X111.173 Y113.595 I-2.896 J2.329 E.05693*74
Recv: ok
Send: N2493 G2 X108.989 Y114.107 I-.732 J1.791 E.08099*112
Recv: ok
Send: N2494 G3 X107.604 Y115.16 I-2.69 J-2.103 E.05955*111
Recv: ok
Send: N2495 G1 X107.604 Y111.784 E.11427*103
Recv: ok
Send: N2496 G2 X108.989 Y111.133 I-.031 J-1.864 E.05338*94
Recv: ok
Send: N2497 G3 X110.299 Y110.1 I2.896 J2.328 E.05695*105
Recv: ok
Send: N2498 G3 X112.483 Y110.613 I.731 J1.792 E.081*92
Recv: ok
Send: N2499 G2 X113.793 Y111.646 I2.896 J-2.328 E.05695*67
Recv: ok
Send: N2500 G2 X115.977 Y111.133 I.732 J-1.792 E.081*118
Recv: ok
Send: N2501 G3 X117.287 Y110.1 I2.896 J2.328 E.05695*111
Recv: ok
Send: N2502 G3 X119.471 Y110.613 I.732 J1.792 E.081*91
Recv: ok
Send: N2503 G2 X120.782 Y111.646 I2.897 J-2.328 E.05698*77
Recv: ok
Send: N2504 G2 X122.966 Y111.133 I.731 J-1.792 E.081*117
Recv: ok
Send: N2505 G3 X124.276 Y110.1 I2.896 J2.328 E.05695*101
Recv: ok
Send: N2506 G3 X126.46 Y110.613 I.731 J1.792 E.081*96
Recv: ok
Send: N2507 G2 X127.77 Y111.646 I2.896 J-2.328 E.05695*127
Recv: ok
Send: N2508 G2 X129.954 Y111.133 I.731 J-1.792 E.081*115
Recv: ok
Send: N2509 G3 X131.264 Y110.1 I2.896 J2.328 E.05695*110
Recv: ok
Send: N2510 G3 X133.448 Y110.613 I.732 J1.792 E.081*90
Recv: ok
Send: N2511 G2 X134.833 Y111.665 I2.69 J-2.103 E.05953*117
Recv: ok
Send: N2512 G1 X134.833 Y108.29 E.11424*88
Recv: ok
Send: N2513 G3 X133.448 Y107.638 I.031 J-1.864 E.0534*66
Recv: ok
Send: N2514 G2 X132.138 Y106.606 I-2.896 J2.329 E.05693*70
Recv: ok
Send: N2515 G2 X129.954 Y107.119 I-.732 J1.792 E.081*115
Recv: ok
Send: N2516 G3 X128.644 Y108.151 I-2.896 J-2.329 E.05693*100
Recv: ok
Send: N2517 G3 X126.46 Y107.638 I-.732 J-1.791 E.081*111
Recv: ok
Send: N2518 G2 X125.149 Y106.606 I-2.896 J2.329 E.05696*79
Recv: ok
Send: N2519 G2 X122.966 Y107.119 I-.731 J1.792 E.08096*120
Recv: ok
Send: N2520 M73 Q15 S18*45
Recv: ok
Send: N2521 G3 X121.655 Y108.151 I-2.897 J-2.329 E.05696*109
Recv: ok
Send: N2522 G3 X119.471 Y107.638 I-.731 J-1.791 E.081*86
Recv: ok
Send: N2523 G2 X118.161 Y106.606 I-2.896 J2.329 E.05693*70
Recv: ok
Send: N2524 G2 X115.977 Y107.119 I-.731 J1.792 E.081*124
Recv: ok
Send: N2525 G3 X114.667 Y108.151 I-2.896 J-2.329 E.05693*106
Recv: ok
Send: N2526 G3 X112.483 Y107.638 I-.732 J-1.791 E.081*87
Recv: ok
Send: N2527 G2 X111.173 Y106.606 I-2.896 J2.329 E.05693*72
Recv: ok
Send: N2528 G2 X108.989 Y107.119 I-.732 J1.792 E.081*126
Recv: ok
Send: N2529 G3 X107.604 Y108.171 I-2.69 J-2.103 E.05953*82
Recv: ok
Send: N2530 G1 X107.604 Y104.795 E.11427*109
Recv: ok
Send: N2531 G2 X108.989 Y104.144 I-.031 J-1.863 E.05338*81
Recv: ok
Send: N2532 G3 X110.299 Y103.112 I2.896 J2.329 E.05693*97
Recv:  T:229.92/225.00 B:60.06/60.00 X:35.90/36.00 A:47.53/0.00 @:122 B@:53 C@:26.69 HBR@:198
Recv: ok
Send: N2533 G3 X112.483 Y103.625 I.731 J1.792 E.081*91
Recv: ok
Send: N2534 G2 X113.793 Y104.657 I2.896 J-2.329 E.05693*70
Recv: ok
Send: N2535 G2 X115.977 Y104.144 I.732 J-1.792 E.081*116
Recv: ok
Send: N2536 G3 X117.287 Y103.112 I2.896 J2.329 E.05693*109
Recv: ok
Send: N2537 G3 X119.471 Y103.625 I.732 J1.792 E.081*90
Recv: ok
Send: N2538 G2 X120.782 Y104.657 I2.897 J-2.329 E.05696*78
Recv: ok
Send: N2539 G2 X122.966 Y104.144 I.731 J-1.792 E.081*127
Recv: ok
Send: N2540 G3 X124.276 Y103.112 I2.896 J2.329 E.05693*98
Recv: ok
Send: N2541 M117 38% L=10/100*86
Recv: ok
Send: N2542 G3 X126.46 Y103.625 I.731 J1.792 E.081*103
Recv: ok
Send: N2543 G2 X127.77 Y104.657 I2.896 J-2.329 E.05693*124
Recv: ok
Send: N2544 G2 X129.954 Y104.144 I.731 J-1.792 E.081*127
Recv: ok
Send: N2545 G3 X131.264 Y103.112 I2.896 J2.329 E.05693*96
Recv: ok
Send: N2546 G3 X133.448 Y103.625 I.732 J1.792 E.081*94
Recv: ok
Send: N2547 G2 X134.833 Y104.677 I2.69 J-2.103 E.05953*113
Recv: ok
Send: N2548 M73 P15 R14*47
Recv: ok
Send: N2549 G1 X134.833 Y101.301 E.11427*101
Recv: ok
Send: N2550 G3 X133.448 Y100.65 I.031 J-1.863 E.05338*68
Recv: ok
Send: N2551 G2 X132.138 Y99.618 I-2.896 J2.329 E.05693*127
Recv: ok
Send: N2552 G2 X129.954 Y100.131 I-.732 J1.792 E.081*125
Recv: ok
Send: N2553 G3 X128.644 Y101.163 I-2.896 J-2.329 E.05693*109
Recv: ok
Send: N2554 G3 X126.46 Y100.65 I-.732 J-1.792 E.081*82
Recv: ok
Send: N2555 G2 X125.149 Y99.618 I-2.897 J2.329 E.05696*127
Recv: ok
Send: N2556 G2 X122.966 Y100.131 I-.731 J1.792 E.08096*126
Recv: ok
Send: N2557 G3 X121.655 Y101.163 I-2.897 J-2.329 E.05696*100
Recv: ok
Send: N2558 G3 X119.471 Y100.65 I-.731 J-1.792 E.081*97
Recv: ok
Send: N2559 G2 X118.161 Y99.618 I-2.896 J2.329 E.05693*115
Recv: ok
Send: N2560 G2 X115.977 Y100.131 I-.731 J1.792 E.081*113
Recv: ok
Send: N2561 G3 X114.667 Y101.163 I-2.896 J-2.329 E.05693*98
Recv: ok
Send: N2562 G3 X114.452 Y101.236 I-.732 J-1.792 E.0077*107
Recv: ok
Send: N2563 G1 F11054*77
Recv: ok
Send: N2564 G3 X112.483 Y100.65 I-.517 J-1.865 E.0733*87
Recv: ok
Send: N2565 G2 X111.173 Y99.618 I-2.896 J2.329 E.05693*118
Recv: ok
Send: N2566 G2 X108.989 Y100.131 I-.732 J1.792 E.081*121
Recv: ok
Send: N2567 G3 X107.604 Y101.183 I-2.69 J-2.104 E.05953*91
Recv: ok
Send: N2568 G1 X107.604 Y99.183 E.0677*99
Recv: ok
Send: N2569 M204 P3000*110
Recv: ok
Send: N2570 M117 38% L=11/100*85
Recv: ok
Send: N2571 G92 E0.0*104
Recv: X:107.60 Y:99.18 Z:2.00 E:0.00 Count A:21969 B:1882 Z:1041
Recv: ok
Send: N2572 G1 E-.7 F2700*40
Recv: ok
Send: N2573 G1 X107.604 Y99.183 Z2 F21000*57
Recv: ok
Send: N2574 G1 X107.258 Y98.659 Z2.2 F2370.883*6
Recv: ok
Send: N2575 G1 X107.258 Y98.659 F21000*123
Recv: ok
Send: N2576 G1 Z2.2 F720*25
Recv: ok
Send: N2577 G1 E.7 F1500*1
Recv: ok
Send: N2578 M204 P6000*107
Recv: ok
Send: N2579 G1 F3627*119
Recv: ok
Send: N2580 G1 X135.179 Y98.659 E.94509*95
Recv: ok
Send: N2581 G1 X135.179 Y126.581 E.94513*103
Recv: ok
Send: N2582 G1 X107.258 Y126.581 E.94509*110
Recv: ok
Send: N2583 G1 X107.258 Y98.719 E.94309*94
Recv: ok
Send: N2584 M73 P16 R14*44
Recv: ok
Send: N2585 M204 P3000*108
Recv: ok
Send: N2586 G1 X106.851 Y98.252 F21000*122
Recv: ok
Send: N2587 M204 P6000*107
Recv: ok
Send: N2588 G1 F10200*74
Recv: ok
Send: N2589 G1 X135.586 Y98.252 E.97264*82
Recv: ok
Send: N2590 G1 X135.586 Y126.988 E.97268*110
Recv:  T:229.09/225.00 B:59.97/60.00 X:36.22/36.00 A:47.51/0.00 @:138 B@:58 C@:26.69 HBR@:205
Recv: ok
Send: N2591 M73 Q15 S17*40
Recv: ok
Send: N2592 G1 X106.851 Y126.988 E.97264*103
Recv: ok
Send: N2593 G1 X106.851 Y98.312 E.97065*88
Recv: ok
Send: N2594 G1 E-0.70000 F2100.000*8
Recv: ok
Send: N2595 M400*28
```
