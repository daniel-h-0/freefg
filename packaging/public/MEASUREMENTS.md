# Measurements

All numbers on this page were measured on **one AMD BC-250**, in **one game** (Cyberpunk 2077) plus a synthetic XeFG
test scene, and a live install in a second game. Most were measured **without a display** (a private headless
gamescope); one campaign ran **on a TV with VRR** ([On a TV with VRR](#on-a-tv-with-vrr)). Headless and TV figures
are not comparable with each other. Some comparisons **cross two days**. Read them as evidence that FreeFG is
faster on this hardware with identical output and even pacing. They are not a prediction for your games, settings or
display.

The figures on this page are drawn from data files in the repository (`docs/data/<figure>/data.json`, each with its
`plot.py`), which name their sources. Some figures also show runs from other days (Intel's shaders, earlier private
builds) for context; the figure and the text mark them.

The build measured is FreeFG 0.9.0, the 2×-only pre-release: `libxess_fg.dll` sha256
`3bb43859ccff3a98786dd3c931e430523dbd05676f8d721515973ea73f935410`, with the pacing layer `libxefg_wave.so` sha256
`d5f9800d0f52903f16b5a71af42599d89640bc41fc0bfc4dad66248f30ac3271` and Intel's XeFG runtime 1.3.1.78 (sha256
`ec5e0c65e075570c6ede72618bb666d0be0c2e10b2ea9762c0fe8cb8e375ab27`), unmodified. FreeFG 1.0.0 ships the same layer
and the same 28 shaders for 2×, plus five for the multi-frame network, with a new build of the proxy:
`libxess_fg.dll` sha256 `77f2625174fb88c149a3f76e6c4ae829382d620b256e4a3213a64eca56ea42a7`, from the same source with
the multi-frame code compiled in. The measurements on this page were not repeated with it; what was checked with
1.0.0 is in [README.md](README.md#status). Nothing on this page measures 3× or 4×.

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

![Cyberpunk 2077 at 2× on an AMD BC-250, 2560×1440, FSR 4 Performance, native XeSS frame generation. Headless: XeFG with Intel's shaders 85.31 FPS (SDR, 15 October 2026) and FreeFG 103.28 FPS (SDR, 16 October), +21.1% measured a day apart; FreeFG in HDR10 101.58 FPS. On an LG G5 TV at 120 Hz with VRR: FreeFG 99.29 FPS in SDR and 97.24 FPS in HDR10 (18–19 October). Headless and TV figures are not comparable with each other.](../../docs/assets/cyberpunk-2x-fps.svg)

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

The figure below shows the commit intervals behind the FreeFG SDR column, under two rows from an earlier session
with the same harness and TV (2026-09-29, earlier private builds, no compute queue): XeFG with an earlier pacing layer
passing presents through, and with a later one pacing them from the game's queue. Those two rows show what pacing does;
they are not FreeFG measurements. The figure counts long intervals against each run's own median, as the table above
does.

![Frame pacing on an LG G5 TV with VRR at 2×, Cyberpunk 2077, 2560×1440, SDR: intervals between display commits. Without pacing (29 September 2026, earlier private builds, no compute queue), the intervals alternate between about 5 and 16 ms (5th to 95th percentile 4.8 to 16.4 ms, 577 intervals over 1.5 times their run's median in 60 seconds). In the same session, a layer that paces from the game's queue gives 9.0 to 11.1 ms with 3 such intervals in 90 seconds. FreeFG 0.9.0's proxy, layer and shaders with a compute queue (18–19 October): 8.9 to 11.0 ms, 7 such intervals in 120 seconds, none over 25 ms.](../../docs/assets/vrr-pacing.svg)

**Not covered:** gameplay (benchmark only, no save loaded); a game started by Steam or Heroic (the harness runs the
game beside Steam's own interface, which can delay gamescope's commits differently); the OptiFG route; what the TV
itself shows (commit intervals mark when gamescope's frame reaches the kernel; the TV's own frame repeats or re-locks
are not measured); input latency; other displays, games and GPUs.

## GPU time per generated frame

**Setup:** the SDK test program (headless, output 2560×1440, SDR, engine motion vectors, 2×) with a GPU timestamp around
every dispatch of the frame-generation graph; the time of a stage is the sum of its dispatches. FreeFG: 0.9.0's
proxy, 3 runs of 220 generated frames of the synthetic scene with 1280×720 inputs, 2026-10-18. Intel's shaders: Intel's
runtime alone, 1 run of 180 generated frames of replayed game inputs at 2560×1440, 2026-09-27. The two bars are **not
one session and not the same inputs**: the passes FreeFG leaves to Intel's shaders took 1.57 ms in one and 2.11 ms
in the other (the motion splat runs on a 4× larger grid with the larger inputs). In the stages FreeFG replaces, the
time falls from 7.65 to 2.93 ms (−4.7 ms); the remaining 0.55 ms of the 5.26 ms total gap comes from the inputs. The
reference run used another of Intel's 2× warp variants (same dispatch grid), and Intel's 224- and 64-channel flow passes
are matched to FreeFG's by dispatch grid and call count.

| | Intel's shaders | FreeFG | Who runs it in FreeFG |
| --- | --- | --- | --- |
| Reconstruction network | 5.12 ms | 1.93 ms | own shaders |
| Optical flow, 224-channel layers | 1.24 ms | 0.44 ms | own shaders |
| Optical flow, 64-channel refinement | 1.29 ms | 0.56 ms | own shaders |
| Warp | 0.82 ms | 0.82 ms | Intel's shader |
| Other optical-flow passes | 0.60 ms | 0.46 ms | Intel's shaders |
| Motion splat and compose | 0.69 ms | 0.29 ms | Intel's shaders |
| **Sum of dispatches** | **9.76 ms** | **4.50 ms** | 2.93 ms own, 1.57 ms Intel's |

For scale: in the Cyberpunk benchmark above, the time per real frame at 2× fell by 4.08 ms (from 23.44 to 19.36 ms;
85.31 to 103.28 FPS). That is a whole game frame, with the game's own work and waits, so the two numbers need not
match.

![GPU time per generated frame on the AMD BC-250, XeFG at 2×, output 2560×1440 SDR, from two runs with different inputs (Intel's shaders: replayed game inputs at 2560×1440, 27 September 2026; FreeFG: a synthetic scene with 1280×720 inputs, 18 October 2026). Intel's shaders: 9.76 ms. FreeFG: 4.50 ms, of which 2.93 ms are its own shaders and 1.57 ms Intel's. In the stages FreeFG replaces, 7.65 against 2.93 ms (−4.7 ms); the rest of the total gap (0.55 ms) comes from the different inputs. By stage, Intel's shaders against FreeFG: reconstruction network 5.12 against 1.93 ms (own shaders), optical-flow 224-channel layers 1.24 against 0.44 ms (own), optical-flow 64-channel refinement 1.29 against 0.56 ms (own), warp 0.82 against 0.82 ms (Intel's in both, another of Intel's warp variants in the reference run), other optical-flow passes 0.60 against 0.46 ms, motion splat and compose 0.69 against 0.29 ms (Intel's in both).](../../docs/assets/gpu-time-per-generated-frame.svg)

**Not covered:** games (the test program's scene and replayed inputs only); HDR10, pixel motion vectors and 4K in this
form; one session for both arms.

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
