# Measurements

All numbers on this page were measured on **one AMD BC-250**, in **one game** (Cyberpunk 2077) plus a synthetic XeFG
test scene, and a live install in a second game. Most were measured **without a display** (a private headless
gamescope); one campaign ran **on a TV with VRR** ([On a TV with VRR](#on-a-tv-with-vrr)). Headless and TV figures
are not comparable with each other. Some comparisons **cross two days**. Read them as evidence that FreeFG is
faster on this hardware with identical output and even pacing. They are not a prediction for your games, settings or
display.

The build measured is the one released: `libxess_fg.dll` sha256
`3bb43859ccff3a98786dd3c931e430523dbd05676f8d721515973ea73f935410`, with the pacing layer `libxefg_wave.so` sha256
`d5f9800d0f52903f16b5a71af42599d89640bc41fc0bfc4dad66248f30ac3271` and Intel's XeFG runtime 1.3.1.78 (sha256
`ec5e0c65e075570c6ede72618bb666d0be0c2e10b2ea9762c0fe8cb8e375ab27`), unmodified.

## Test system

| | |
| --- | --- |
| Hardware | AMD BC-250 (Cyan Skillfish APU), GPU clock limit 1850 MHz, 6 GiB GTT (`ttm.pages_limit=1572864`) |
| Software | CachyOS, kernel `linux-cachyos-bc250` 7.2.8; Mesa 26.2.2 RADV, a BC-250 build with the compute queue enabled; Wine/Proton: GE-Proton 11-7 through umu-launcher; gamescope 3.16.28 |
| Display | Headless sections: none (`gamescope --backend headless`, 2560×1440 at 120 Hz, no VRR). TV section: an LG G5 OLED TV at 2560×1440 and 120 Hz with VRR, through a DisplayPort-to-HDMI adapter, in Steam Game Mode (gamescope outputs HDR10). |

## Generated images: bit-identical

**Test:** a synthetic XeFG scene (scene 3 of this project's SDK test program) runs with Intel's runtime at 2×. The
generated images are read back and their hashes compared.

| Configuration (2560×1440 unless noted) | FreeFG vs reference | Frames | Compared directly with Intel's shaders |
| --- | --- | --- | --- |
| SDR, engine motion vectors | identical | 5 of 5 | **identical** (same scene, same runtime, Intel's shaders) |
| SDR, pixel motion vectors | identical | 5 of 5 | not compared |
| HDR10, engine motion vectors | identical | 5 of 5 | not compared |
| HDR10, pixel motion vectors | identical | 5 of 5 | not compared |
| SDR, 3840×2160 | identical | 5 of 5 | not compared |
| SDR, repeat run | identical to the first run | 5 of 5 | — |

The **reference** is an internal, unreleased build with the same 28 shaders and the same kernels, entered through a
different loader. Its own images matched Intel's shaders where that was checked (the SDR, engine-motion row above, on
2026-10-15). In the other four rows, identity with Intel's shaders follows from the exact arithmetic described in
[ARCHITECTURE.md](ARCHITECTURE.md) but was **not measured directly**. Every run logged the accelerated path (27
coefficient buffers owned, the Winograd kernels executing), two presents per frame, and no failure.

Not covered: real game content, pixel comparisons in games, other resolutions, long sessions.

## Frame rate: Cyberpunk 2077

**Setup:** Cyberpunk 2077 (GOG build, launched with umu-launcher) in the headless gamescope above. 2560×1440 output,
FSR 4 Performance upscaling, the game's native XeSS frame generation at 2×, pacing layer on
(`BC250_XEFG_PACE=auto`). Each run is one pass of the game's built-in benchmark. Its average FPS counts generated frames.
On each day the arms alternated in ABBA blocks (2026-10-16: `b p p b b p p b` for SDR, `b p p b` for HDR10, b being the
reference and p FreeFG). Figures are means ± sample standard deviation.

| Arm | Date | SDR 2× (FPS) | HDR10 2× (FPS) |
| --- | --- | --- | --- |
| **FreeFG** | 2026-10-16 | **103.28 ± 0.09** (103.40, 103.18, 103.28, 103.25) | **101.58 ± 0.16** (101.69, 101.47) |
| Reference: same kernels, internal loader (not released) | 2026-10-16 | 103.03 ± 0.14 | 101.28 ± 0.25 |
| Reference, same harness | 2026-10-15 | 103.05 ± 0.07 | — |
| **Intel's shaders** (XeFG with no acceleration, `BC250_XEFG_DISABLE=1`, same harness) | 2026-10-15 | **85.31 ± 0.09** (85.27, 85.25, 85.44, 85.30) | not measured |

- **FreeFG vs Intel's shaders, SDR 2×: +21.1%** (103.28 vs 85.31 FPS; 9.68 vs 11.72 ms per displayed frame). This
  crosses days. The reference build, measured on both days in the same harness (103.05, then 103.03), is the bridge.
  It moved by 0.02%. Treat the figure as indicative, not as a same-session A/B.
- **FreeFG vs the reference, same session:** +0.24% SDR (both blocks positive: +0.31%, +0.17%), +0.30% HDR10.
  FreeFG's loader is not slower than the internal one.
- Minimum FPS reported by the benchmark: FreeFG 94.0–94.4 (SDR) and 93.3 (HDR10); Intel's shaders 79.6–79.9 (SDR).
- The Intel's-shaders arm ran through the internal loader with its acceleration switched off. It had the same pacing
  layer, and that layer held presents while XeFG generated.
- In every FreeFG run: the proxy reported Intel's runtime ready, the accelerated path was active from the first
  context, XeFG reported two presented frames per game frame, no `FAIL`, `FAST_SKIP` or `FAST_FALLBACK` line, and the
  pacing layer held presents while XeFG generated.

**Not covered:** other games; other resolutions and upscaler modes; a real display, VRR and gamescope's real refresh
behaviour (the headless compositor runs a fixed 120 Hz timer, so these numbers are not comparable with figures measured
on a TV; see [On a TV with VRR](#on-a-tv-with-vrr) for one display); input latency; frame-time distribution and pacing
quality (not evaluated in this campaign); HDR10 against Intel's shaders; stock Mesa without the compute queue; other
GPUs; power and temperature; sessions longer than one benchmark pass.

## On a TV with VRR

**Setup:** the same Cyberpunk 2077 benchmark and settings as above (2560×1440, FSR 4 Performance, native XeSS frame
generation at 2×, `BC250_XEFG_PACE=auto`), on the live Steam Game Mode display: an LG G5 OLED TV at 1440p and 120 Hz.
VRR was active in every run, read back from the display driver and gamescope before and after each capture. A test
harness started the game (not Steam or Heroic), with no save loaded. FreeFG's proxy, pacing layer and shader profile
were placed in the game folder by hand rather than by Setup; the OptiScaler DLL there was an earlier build of the same
source (only its version string differs), and a few files of the other arm stayed in the folder without being loaded.
The comparison arm is an **earlier private build** that is not part of this release: it replaces more of the runtime's
shaders than FreeFG does. The arms alternated in ABBA blocks, 4 runs per arm in SDR and 4 in HDR10, on 2026-10-18/19.
Each run recorded the benchmark's own frame count, the pacing layer's present times and a 30-second kernel trace of
gamescope's display commits, taken at the same point of the benchmark in both arms.

| | SDR: earlier private build | SDR: FreeFG | HDR10: earlier private build | HDR10: FreeFG |
| --- | --- | --- | --- | --- |
| Benchmark FPS (mean ± sd) | 100.18 ± 0.21 | **99.29 ± 0.07** | 98.55 ± 0.11 | **97.24 ± 0.11** |
| Presents per game frame | 2.000 | **2.000** | 2.000 | **2.000** |
| Pacing layer: release interval SD (ms) | 0.536 | **0.536** | 0.542 | **0.549** |
| Display commit interval p5 / p50 / p95 (ms) | 8.83 / 9.82 / 10.82 | 8.88 / 9.93 / 11.02 | 8.96 / 9.95 / 11.04 | 9.09 / 10.15 / 11.19 |
| Display commit interval SD (ms) | 0.646 | 0.709 | 0.661 | 0.681 |
| Commit intervals over 1.5× the median, in 4 × 30 s | 3 | 7 | 3 | 3 |
| Commit intervals over 25 ms (below the TV's 40 Hz VRR floor) | 0 | 0 | 0 | 0 |

- **Pacing:** the layer hands frames to gamescope at the same cadence in both builds. FreeFG's SDR commit spread is
  0.06 ms wider; all 7 of its long intervals were on the display side (the layer released the frame on time and
  gamescope committed it late). In HDR10 the spread is equal. Watching both builds on the TV, the maintainer saw no
  difference (a subjective check).
- **Frame rate:** FreeFG is 0.89% lower in SDR (ABBA blocks −0.97% and −0.81%) and 1.33% lower in HDR10 (−1.41%,
  −1.25%) than the earlier private build. Headless measurements predicted a gap of this size: it comes from the passes
  that FreeFG leaves to Intel's shaders.
- On the TV the benchmark runs about 3% below the headless figures above (about 99 against 103 FPS). Compare TV figures
  only with TV figures.

**Not covered:** gameplay (benchmark only, no save loaded); a game started by Steam or Heroic (the harness runs the
game beside Steam's own interface, which can delay gamescope's commits differently); the OptiFG route; what the TV
itself shows (commit intervals mark when gamescope's frame reaches the kernel; the TV's own frame repeats or re-locks
are not measured); input latency; other displays, games and GPUs.

## Live install and Restore

**Setup:** two installed games on the same BC-250, on 2026-10-18 and 2026-10-19, with the installer's command line
(`install.py`, which Setup runs) and the Automatic input, in two rounds. Each round hashed every file of both game
folders before the change and after Restore (the second round also their permissions and file times) and compared the
launcher entries.

| | Echo Point Nova (Steam) | Cyberpunk 2077 (GOG, through Heroic) |
| --- | --- | --- |
| Input the recipe picked | OptiFG | native XeSS FG |
| Files placed | OptiScaler as `winmm.dll`, FreeFG's `libxess_fg.dll`, Intel's runtime as `bc250_xefg_original.dll`, XeLL, the FSR 4 DLL, the pacing layer and shader profile | the same, with OptiScaler as `dxgi.dll` |
| Launcher settings written | the game's launch options in both local Steam accounts | the game's Heroic settings |
| Start | from Steam, four times to the main menu (no save loaded): the accelerated path active and XeFG generating, 120 presents per second at the display's 120 Hz | the benchmark, started by the test harness with the launch settings the installer wrote (not by Heroic, so its cloud-save sync was not involved): **2.001 presents per game frame**, 102.76 and 103.28 FPS (headless) |
| Restore | every file in the game folder as before (content, permissions, file time), apart from OptiScaler's own log of the last start; some folder times differ. The Steam launch options as before | the same for the game folder; Heroic's settings file byte-identical, with its permissions and file time |

- In the first round (2026-10-18), Restore left four kinds of small difference: OptiScaler's re-saved `OptiScaler.ini`
  with different spacing, Heroic's and Steam's files in a slightly different layout (a final newline, other string
  escapes), an empty folder the installation had created, and an earlier log that it moved. The installer was changed
  to avoid all four, and the second round (2026-10-19) returned both games as the table says.
- On the OptiFG route nothing reports the number of generated frames, so the ratio there was not measured.

**Not covered:** gameplay; a game started from Heroic itself (with its cloud saves); the desktop Setup window; Lutris;
Flatpak launchers.

## Present pacing

In all six headless runs the layer logged that it held presents while XeFG generated, and that it passed them through
otherwise. On a display, see [On a TV with VRR](#on-a-tv-with-vrr).

## Reproducing

The SDK scene, the headless and TV harnesses and the benchmark driver are part of the project's research tooling, which
is not published with this release. The release tree has what you need to reproduce the build and its CPU-side checks
([BUILDING.md](BUILDING.md)), but not these GPU measurements.
