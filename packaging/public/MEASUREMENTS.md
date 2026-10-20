# Measurements

The numbers describe FreeFG on this hardware; they are not a prediction for other games, settings, displays or GPUs.

## Scope

- One AMD BC-250 ([test system](#test-system)).
- Every measurement is at 2× with 0.9.0, the 2×-only pre-release. 1.0.0 keeps its pacing layer and 28 shaders for 2×
  and adds five multi-frame shaders, with a proxy built from the same source with the multi-frame code compiled in. The
  measurements were not repeated with 1.0.0, which had the shorter [checks](#checks-of-100), including 3× and 4×.
- Most runs are headless; one campaign ran [on a TV with VRR](#on-a-tv-with-vrr). Headless and TV figures are not
  comparable. Some comparisons cross two days, as marked.
- Each figure is drawn from `docs/data/<figure>/data.json` in the repository (with its `plot.py`), which names its
  sources; context runs from other days or earlier private builds are marked.
- The SDK scene, the headless and TV harnesses and the benchmark driver belong to the project's unpublished research
  tooling. The release tree reproduces the build and its CPU-side checks ([BUILDING.md](BUILDING.md)), not these GPU
  measurements.

## Builds

| Component | Version | SHA-256 |
| --- | --- | --- |
| `libxess_fg.dll` (measured) | 0.9.0 | `3bb43859ccff3a98786dd3c931e430523dbd05676f8d721515973ea73f935410` |
| `libxess_fg.dll` (released) | 1.0.0 | `77f2625174fb88c149a3f76e6c4ae829382d620b256e4a3213a64eca56ea42a7` |
| Pacing layer `libxefg_wave.so` | 0.9.0 and 1.0.0 | `d5f9800d0f52903f16b5a71af42599d89640bc41fc0bfc4dad66248f30ac3271` |
| Intel's XeFG runtime, unmodified | 1.3.1.78 | `ec5e0c65e075570c6ede72618bb666d0be0c2e10b2ea9762c0fe8cb8e375ab27` |

## Test system

| | |
| --- | --- |
| Hardware | AMD BC-250 (Cyan Skillfish APU), GPU clock limit 1850 MHz, 6 GiB GTT (`ttm.pages_limit=1572864`) |
| Software | CachyOS, kernel `linux-cachyos-bc250` 7.2.8; Mesa 26.2.2 RADV, a BC-250 build with the compute queue enabled; GE-Proton 11-7 through umu-launcher; gamescope 3.16.28; Python 3.14 for the installer |
| Headless runs | `gamescope --backend headless`, 2560×1440 at a fixed 120 Hz, no VRR |
| TV runs | LG G5 OLED TV at 2560×1440 and 120 Hz with VRR (range 40–165 Hz), through a DisplayPort-to-HDMI adapter, in Steam Game Mode (gamescope outputs HDR10) |

## Checks of 1.0.0

1.0.0's proof-of-life qualification ([Status](README.md#status)) on the [test system](#test-system).

| Check | Result |
| --- | --- |
| Build | Reproducible byte for byte from source on the pinned toolchain ([BUILDING.md](BUILDING.md)). |
| Static check | Passes with no allowance ([NOTICE.md](NOTICE.md#the-shader-profile)). |
| Installer | Unit tests pass; an offline install and Restore return a throwaway game folder to its original files. |
| Wine loader check, no GPU | Loads and forwards to Intel's runtime; refuses a missing or altered runtime. With a stand-in module hooking eight of Intel's entry points, each call reaches it once with the caller it would see without FreeFG; only OptiScaler's contexts are accelerated (also a unit test). |
| Synthetic scenes, 2× | Generated images bit-identical to 0.9.0's (which match Intel's shaders where compared, [below](#generated-images-bit-identical)) in SDR 1440p, HDR10 1440p with pixel motion vectors and SDR 4K, five images each. Coefficient buffers verified; 2 frames per present. |
| Echo Point Nova (Steam, OptiScaler's frame generation) | 2×: accelerated, 2 frames per present. MFG Unlocker v1.6.0 with `XeFGModel=default`: 4× at 4 and 3× at 3 frames per present on FreeFG's shaders; one of two 3× starts ended during start-up with no error in any log, and the next start worked. MFG Unlocker's own model: 3× at 3, accelerated. HelixSR 2.0.0: its network ran, 2× accelerated at 2; OptiScaler's FSR 4 settings left its DLL alone; switching back to FSR 4 worked. |
| Cyberpunk 2077 (GOG through Heroic, the game's own XeSS FG), headless | Benchmark accelerated, 2.0 presents per game frame, 102.08 FPS: one run, not compared on the same day (0.9.0: 103.28 FPS on 16 October). |
| Restore | Both game folders exactly as they were. |
| CONTROL Resonant (DLSS FG input), this release's OptiScaler | 32 of 32 starts reached the game; 2 presents per game frame in the 12 starts measured. |

Echo Point Nova was installed by this build's installer; its OptiScaler DLL was then replaced by hand with the one the
1.0.0 package ships.

Not covered: same-day speed comparisons (1.0.0 against 0.9.0 at 2×; FreeFG against MFG Unlocker alone at 3× and 4×);
3× and 4× on a VRR display, in HDR10 and in their picture; changing the frame count while a game runs, and OptiScaler's
Dynamic MFG; a game's own XeSS frame generation beside MFG Unlocker; games without a recipe; Flatpak Steam or Heroic;
gameplay and longer play sessions; pixel comparisons in games.

## Generated images: bit-identical

Setup: a synthetic XeFG scene (scene 3 of this project's SDK test program) runs with Intel's runtime at 2×; the
generated images are read back and their hashes compared.

| Configuration (2560×1440 unless noted) | FreeFG against the reference | Frames | Directly against Intel's shaders |
| --- | --- | --- | --- |
| SDR, engine motion vectors | identical | 5 of 5 | the reference's images identical (same scene, same runtime, 2026-10-15) |
| SDR, pixel motion vectors | identical | 5 of 5 | not compared |
| HDR10, engine motion vectors | identical | 5 of 5 | not compared |
| HDR10, pixel motion vectors | identical | 5 of 5 | not compared |
| SDR, 3840×2160 | identical | 5 of 5 | not compared |
| SDR, repeat run | identical to the first run | 5 of 5 | — |

The reference is an internal, unreleased build with the same 28 shaders and kernels, entered through a different loader.
In the four rows not compared with Intel's shaders, identity with them follows from the exact arithmetic
([ARCHITECTURE.md](ARCHITECTURE.md#exact-arithmetic)) but was not measured. Every run logged the accelerated path (27
coefficient buffers owned, the Winograd kernels executing), two presents per frame, and no failure.

Not covered: real game content; pixel comparisons in games; other resolutions; long sessions.

## Frame rate: Cyberpunk 2077

Setup:

- Cyberpunk 2077 2.31 (GOG build, started with umu-launcher), built-in benchmark, one pass per run, headless; 2560×1440
  output, FSR 4 Performance, ray tracing off, the game's native XeSS frame generation at 2×, pacing layer on
  (`BC250_XEFG_PACE=auto`). FPS is the benchmark's average, which counts generated frames.
- Arms alternated in ABBA blocks each day (2026-10-16: `b p p b b p p b` for SDR, `b p p b` for HDR10; b is the
  reference, p is FreeFG). Figures are means ± sample standard deviation.
- The Intel's-shaders arm ran XeFG through the reference's loader with acceleration off (`BC250_XEFG_DISABLE=1`) and the
  same pacing layer, which held presents while XeFG generated.

| Arm | Date | SDR 2× (FPS) | HDR10 2× (FPS) |
| --- | --- | --- | --- |
| FreeFG | 2026-10-16 | 103.28 ± 0.09 (103.40, 103.18, 103.28, 103.25) | 101.58 ± 0.15 (101.69, 101.47) |
| Reference (same kernels, internal loader) | 2026-10-16 | 103.03 ± 0.14 | 101.28 ± 0.25 |
| Reference | 2026-10-15 | 103.05 ± 0.07 | — |
| Intel's shaders | 2026-10-15 | 85.31 ± 0.08 (85.27, 85.25, 85.44, 85.30) | not measured |

Results:

- FreeFG against Intel's shaders, SDR: +21.1% (103.28 against 85.31 FPS; 9.68 against 11.72 ms per displayed frame),
  on different days, bridged by the reference build run on both days in the same harness (103.05, then 103.03 FPS, a
  change of 0.02%); indicative, not a same-session comparison.
- Against the reference, same session: +0.24% in SDR (blocks +0.31%, +0.17%) and +0.30% in HDR10; FreeFG's loader is
  not slower than the internal one.
- Benchmark minimum FPS: FreeFG 94.0–94.4 (SDR) and 93.3 (HDR10); Intel's shaders 79.6–79.9 (SDR).
- In all six FreeFG runs: Intel's runtime reported ready, the accelerated path active from the first context, two
  presented frames per game frame, no `FAIL`, `FAST_SKIP` or `FAST_FALLBACK` line, and presents held while XeFG
  generated and passed through otherwise.

Figure: [README.md](README.md#status).

Not covered: other resolutions and upscaler modes; a real display, VRR and gamescope's real refresh behaviour (the
headless compositor runs a fixed 120 Hz timer); input latency; frame-time distribution and pacing quality; HDR10 against
Intel's shaders; stock Mesa without the compute queue; power and temperature; longer sessions.

## On a TV with VRR

Setup:

- The benchmark and settings [above](#frame-rate-cyberpunk-2077) on the live Steam Game Mode display (the [test
  system](#test-system)'s TV), started by a test harness (not Steam or Heroic) with no save loaded. VRR was active in
  every run, read back from the display driver and gamescope before and after each capture.
- FreeFG's proxy, pacing layer and shader profile were placed by hand, not by Setup, beside an OptiScaler DLL of an
  earlier build of the same source (only its version string differs). A few unloaded files of the other arm stayed in
  the folder.
- The comparison arm is an earlier private build, not part of this release, which replaces more of the runtime's
  shaders.
- ABBA blocks, 4 runs per arm in SDR and 4 in HDR10, 2026-10-18/19. Per run: the benchmark's frame count, the layer's
  present times, and a 30-second kernel trace of gamescope's display commits at the same benchmark point in both arms.

| | SDR: earlier build | SDR: FreeFG | HDR10: earlier build | HDR10: FreeFG |
| --- | --- | --- | --- | --- |
| Benchmark FPS (mean ± sd) | 100.18 ± 0.21 | 99.29 ± 0.07 | 98.55 ± 0.11 | 97.24 ± 0.11 |
| Presents per game frame | 2.000 | 2.000 | 2.000 | 2.000 |
| Pacing layer: release interval SD (ms) | 0.536 | 0.536 | 0.542 | 0.549 |
| Display commit interval p5 / p50 / p95 (ms) | 8.83 / 9.82 / 10.82 | 8.88 / 9.93 / 11.02 | 8.96 / 9.95 / 11.04 | 9.09 / 10.15 / 11.19 |
| Display commit interval SD (ms) | 0.646 | 0.709 | 0.661 | 0.681 |
| Commit intervals over 1.5× the run's median, in 4 × 30 s | 3 | 7 | 3 | 3 |
| Commit intervals over 25 ms (below the TV's 40 Hz VRR floor) | 0 | 0 | 0 | 0 |

Results:

- Pacing: the layer released frames at the same cadence in both builds. In SDR, FreeFG's commit interval SD is 0.06
  ms higher, and all 7 of its long intervals were on the display side (released on time, committed late by gamescope);
  in HDR10 the SDs differ by 0.02 ms. The maintainer saw no difference on the TV (a subjective check).
- Frame rate: FreeFG is 0.89% lower in SDR (blocks −0.97%, −0.81%) and 1.33% lower in HDR10 (−1.41%, −1.25%), a gap
  headless measurements predicted; it comes from the passes FreeFG leaves to Intel's shaders.
- On the TV the benchmark runs about 3% below the headless figures (about 99 against 103 FPS).

![Frame pacing on an LG G5 TV with VRR at 2×, Cyberpunk 2077, 2560×1440, SDR: intervals between display commits. The first two rows, from an earlier session with the same harness and TV (29 September 2026, earlier private builds, no compute queue), show what pacing does and are not FreeFG measurements. Without pacing the intervals alternate between about 5 and 16 ms (5th to 95th percentile 4.8 to 16.4 ms, 577 intervals over 1.5 times their run's median in 60 seconds). In the same session, a layer that paces from the game's queue gives 9.0 to 11.1 ms with 3 such intervals in 90 seconds. FreeFG 0.9.0 with a compute queue (18–19 October): the SDR column of the table above.](../../docs/assets/vrr-pacing.svg)

Not covered: gameplay; a game started by Steam or Heroic (the harness runs the game beside Steam's own interface, which
can delay gamescope's commits differently); the OptiFG route; what the TV itself shows (commit intervals mark when
gamescope's frame reaches the kernel; the TV's own frame repeats or re-locks are not measured); input latency; other
displays.

## GPU time per generated frame

Setup:

- The SDK test program, headless: output 2560×1440, SDR, engine motion vectors, 2×, with a GPU timestamp around every
  dispatch of the frame-generation graph. A stage's time is the sum of its dispatches, without the gaps between them
  (0.25–0.27 ms per frame).
- FreeFG: 0.9.0's proxy, 3 runs of 220 generated frames of the synthetic scene with 1280×720 inputs, 2026-10-18.
- Intel's shaders: Intel's runtime alone, 1 run of 180 generated frames of replayed game inputs at 2560×1440,
  2026-09-27.

The arms differ in session and inputs. The passes FreeFG leaves to Intel's shaders took 1.57 ms in one and 2.11 ms in
the other (the motion splat runs on a 4× larger grid with the larger inputs). In the stages FreeFG replaces, the time
falls from 7.65 to 2.93 ms (−4.7 ms); the other 0.55 ms of the 5.26 ms total gap comes from the inputs. The reference
run used another of Intel's 2× warp variants (same dispatch grid); Intel's 224- and 64-channel flow passes are matched
to FreeFG's by dispatch grid and call count.

| Stage | Intel's shaders | FreeFG | Who runs it in FreeFG |
| --- | --- | --- | --- |
| Reconstruction network | 5.12 ms | 1.93 ms | own shaders |
| Optical flow, 224-channel layers | 1.24 ms | 0.44 ms | own shaders |
| Optical flow, 64-channel refinement | 1.29 ms | 0.56 ms | own shaders |
| Warp | 0.82 ms | 0.82 ms | Intel's shader |
| Other optical-flow passes | 0.60 ms | 0.46 ms | Intel's shaders |
| Motion splat and compose | 0.69 ms | 0.29 ms | Intel's shaders |
| Sum of dispatches | 9.76 ms | 4.50 ms | 2.93 ms own, 1.57 ms Intel's |

For scale: in the Cyberpunk benchmark, the time per real frame at 2× fell by 4.08 ms (23.44 to 19.36 ms; 85.31 to
103.28 FPS), a whole game frame with the game's own work and waits, so the two numbers need not match.

![GPU time per generated frame by stage, as in the table above.](../../docs/assets/gpu-time-per-generated-frame.svg)

Not covered: games (the test program's scene and replayed inputs only); HDR10, pixel motion vectors and 4K in this
form; both arms in one session.

## Live install and Restore

Setup: two installed games, two rounds (2026-10-18 and 2026-10-19), the installer's command line (`install.py`, which
Setup runs) and the Automatic input. Each round hashed every file of both game folders before the change and after
Restore (the second round also their permissions and file times) and compared the launcher entries.

| | Echo Point Nova (Steam) | Cyberpunk 2077 (GOG, through Heroic) |
| --- | --- | --- |
| Input the recipe picked | OptiFG | native XeSS FG |
| Files placed | OptiScaler as `winmm.dll`, FreeFG's `libxess_fg.dll`, Intel's runtime as `bc250_xefg_original.dll`, XeLL, the FSR 4 DLL, the pacing layer and shader profile | the same, with OptiScaler as `dxgi.dll` |
| Launcher settings written | launch options in both local Steam accounts | the game's Heroic settings |
| Start | from Steam, four times to the main menu (no save loaded): accelerated, XeFG generating, 120 presents per second at 120 Hz | the benchmark, started by the test harness with the installer's launch settings: 2.001 presents per game frame, 102.76 and 103.28 FPS (headless) |
| After Restore (second round) | every file as before (content, permissions, file time) except OptiScaler's log of the last start; some folder times differ; the Steam launch options as before | the same for the game folder; Heroic's settings file byte-identical, with its permissions and file time |

- The first round left four kinds of small difference after Restore: OptiScaler's re-saved `OptiScaler.ini` with
  different spacing; Heroic's and Steam's files in a slightly different layout (a final newline, other string escapes);
  an empty folder the installation had created; and an earlier log that it had moved. The installer was changed to avoid
  all four.
- On the OptiFG route nothing reports the number of generated frames, so the ratio there was not measured.

Not covered: gameplay; a game started from Heroic itself (with its cloud saves); the desktop Setup window; Lutris;
Flatpak launchers.
