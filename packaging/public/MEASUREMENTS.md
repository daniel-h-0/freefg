# Measurements

The numbers describe FreeFG on this hardware; they are not a prediction for other games, settings, displays or GPUs.

## Scope

- One AMD BC-250 ([test system](#test-system)).
- 1.1.0 had the [checks](#checks-of-110), then one block with three arms (Intel's shaders, 1.0.x, 1.1.0):
  [2× in SDR and HDR10](#frame-rate-cyberpunk-2077) and [3× and 4× with MFG Unlocker](#3-and-4-with-mfg-unlocker), all
  with [warm shader caches](#shader-caches).
- 1.1.1 changes only the installer: [shader caches](#shader-caches) gives its checks and its block,
  [live install](#live-install-and-restore) its live check.
- One series at [4K](#4k) with 1.1.0's files, 2× to 4×, against Intel's shaders and v30, a private test build from before 0.9.0.
- 1.0.0 had the shorter [checks](#checks-of-100), then three same-day blocks: [against 0.9.0 at
  2×](#100-against-090-at-2-same-day), against Intel's shaders at 2× and at 3× and 4× (now earlier series in those
  sections). 1.0.1 ships 1.0.0's proxy, pacing layer, shader profile and OptiScaler; "1.0.x" means both.
- The other measurements are at 2× with 0.9.0, the 2×-only pre-release, whose 2× shaders 1.0.x keeps. They do not
  include 1.1.0's faster shaders.
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
| `libxess_fg.dll` | 0.9.0 | `3bb43859ccff3a98786dd3c931e430523dbd05676f8d721515973ea73f935410` |
| `libxess_fg.dll` | 1.0.0 and 1.0.1 | `77f2625174fb88c149a3f76e6c4ae829382d620b256e4a3213a64eca56ea42a7` |
| `libxess_fg.dll` | 1.1.0 and 1.1.1 | `830be46e9c515b63dfe637f5b601eba7e81676b2d51f01a6aebfdf66bcdf186a` |
| Shader profile, digest of its files | 1.1.0 and 1.1.1: 49 files, 130 `waves.txt` entries | `a35efb131305708d4fa7b719bd3d2472952f540a52dc52cf755548710004cdbf` |
| Pacing layer `libxefg_wave.so` | 0.9.0 to 1.1.1 | `d5f9800d0f52903f16b5a71af42599d89640bc41fc0bfc4dad66248f30ac3271` |
| `OptiScaler.dll` | 0.9.0 | `244eca5c0927dff802d7f2a506afe9e7776bcdc489bdc3acdf56e9c92f7b437d` |
| `OptiScaler.dll` | 1.0.0 to 1.1.1 | `5e570dff6299866c508b60634d0dcfc5a53975840888f2aa5e69ba31c3819da6` |
| Installer `install.py` | 1.1.1 | `8701a13286d10eeb76ef640bdd72d42acb6bfcab5dae609d04869c659c4be1e7` |
| Installer `launcher_config.py` (the launch settings) | 1.1.1 | `094667194ea353ea247d52a540395af39d80b00892c6bea5c695f4d2921c0c0d` |
| Intel's XeFG runtime, unmodified | 1.3.1.78 | `ec5e0c65e075570c6ede72618bb666d0be0c2e10b2ea9762c0fe8cb8e375ab27` |
| MFG Unlocker `MFGUnlocker.dll`, not shipped | 1.6.0 | `161b9e1245a3736dc462ee83f4ad51e6125d8e7e73ce3eedde89d2eed60c69fa` |

The shader profile's digest is the SHA-256 of its files' sorted `<file name><TAB><SHA-256>` lines, one per line.

## Test system

| | |
| --- | --- |
| Hardware | AMD BC-250 (Cyan Skillfish APU), GPU clock limit 1850 MHz, 6 GiB GTT (`ttm.pages_limit=1572864`) |
| Software | CachyOS, kernel `linux-cachyos-bc250` 7.2.8; Mesa 26.2.2 RADV, a BC-250 build with the compute queue enabled; GE-Proton 11-7 through umu-launcher; gamescope 3.16.28; Python 3.14 for the installer |
| Headless runs | `gamescope --backend headless`, 2560×1440 at a fixed 120 Hz (240 Hz for [3× and 4×](#3-and-4-with-mfg-unlocker)); 3840×2160 at 240 Hz for [4K](#4k); no VRR |
| TV runs | LG G5 OLED TV at 2560×1440 and 120 Hz with VRR (range 40–165 Hz), through a DisplayPort-to-HDMI adapter, in Steam Game Mode (gamescope outputs HDR10) |

## Checks of 1.1.0

1.1.0's qualification on the [test system](#test-system), 2026-10-20 to 21.

| Check | Result |
| --- | --- |
| Build | Reproducible byte for byte from source on the pinned toolchain, also from the public source export ([BUILDING.md](BUILDING.md)); the 40 shaders rebuild byte for byte with the pinned compiler. |
| Static check | Passes with no allowance ([NOTICE.md](NOTICE.md#the-shader-profile)). |
| Installer | Unit tests pass. The installer is 1.0.1's; the package's `settings.ini` gains `F4Q=1`, so Setup keeps a user's `F4Q=0`. |
| Wine loader check, no GPU | As for 1.0.0, plus ten F4Q cases: on by default, off by the launch option and by `settings.ini`, the launch option over the file, fallback to F(2×2) when a pipeline cannot be created, a network layout F4Q does not know, the diagnostic. |
| Software rasteriser, no GPU | F4Q's kernels and the F(2×2) kernels gave byte-identical outputs on the test inputs. |
| Synthetic scenes (SDK), 20 configurations | 2560×1440 SDR and HDR10 with engine and pixel motion vectors and 3840×2160 SDR, four scenes each: 704 of 704 generated images identical to the images Intel's shaders give, with F4Q on and with it off (`F4Q=0` in `settings.ini`). With F4Q on, both its kernels ran; off, neither. |
| Cyberpunk 2077, F4Q's diagnostic (`BC250_XEFG_F4Q_SHADOW=1`), headless | 7 benchmark runs: 4 at native 2× and 3 at 3× with MFG Unlocker (`XeFGModel=default`), SDR. 96,480 comparisons of the two layers' outputs (14,784 at each of three points at 2×, 17,376 at 3×), none differing, none skipped. |
| Cyberpunk 2077, frame-rate block, headless | 54 of 54 starts valid; F4Q on in every 1.1.0 run, with both kernels ([below](#frame-rate-cyberpunk-2077)). |
| Cyberpunk 2077, F4Q's off switch, headless | One benchmark start at native 2× with F4Q at its default and one with `BC250_XEFG_F4Q=0`, which the test harness set in the game's environment (not through a Steam or Heroic launch option). With the variable, the fast log reported F4Q off by it (`F4Q_CONFIG mode=off source=BC250_XEFG_F4Q`) and F4Q created neither of its pipelines; without it, F4Q was on with both. Both runs accelerated, 2.0 frames shown per game frame, no `FAIL` line. |

Not covered: F4Q compared in a game in HDR10, at 4×, in other games, or without the diagnostic (in a game the default
path was run, not compared); a live install with Setup; a VRR display; MFG Unlocker's own model (benchmarked only at
[4K](#4k)); games without a recipe; gameplay.

## Shader caches

Two caches decide whether the pacing layer can set a shader's wave size from `waves.txt`
([how](ARCHITECTURE.md#wave-sizes-bc-250-only)): Mesa's holds compiled pipelines, vkd3d-proton's what vkd3d-proton
needs to create them again.

| Release | vkd3d-proton's cache | `waves.txt` lines for Intel's shaders |
| --- | --- | --- |
| 1.0.x, 1.1.0 | the game's default, with shader module identifiers | apply only where Mesa's cache does not already hold that pipeline compiled without the line |
| 1.1.1 | a folder of the installation's own, with shader code (Setup's two launch settings) | apply on every start |

**1.1.0's block** (2026-10-20 to 21): every frame-rate run had warm caches from 1.0.x and from test builds of 1.1.0,
as on a computer that ran 1.0.x in the game and then installed 1.1.0, from the second start on.

- No run of the block set a wave size for 1.1.0's five new lines for Intel's shaders (four 2× warp shaders and a
  convolution; 0 of 54), so no 1.1.0 figure contains a gain from them. The lines for FreeFG's own shaders, F4Q's
  included, and the lines 1.0.0 already had applied in every run.
- With empty caches (one benchmark start at native 2×), the three of these lines that this route uses applied. That
  start took 39 s longer than one with warm caches and wrote 18.8 MB of cache. No frame rate is given for this state.

**1.1.1** (2026-10-21, Cyberpunk 2077, headless, settings as in [Frame rate](#frame-rate-cyberpunk-2077) and
[3× and 4×](#3-and-4-with-mfg-unlocker)): 1.1.0's files, with 1.1.1's launch settings set by the test harness, not by
Setup. The harness put the new vkd3d-proton folders (one per route, new in each block) outside the game folder. Mesa's
cache was warm from 1.0.x: it held the pipelines of the five lines compiled without them. The untimed starts (short
starts, not benchmark runs) ran first. Their first start with 1.1.1's settings on each route compiled its route's
pipelines into Mesa's cache with their lines: all three at 2×, two at 3×, where the 2× start had already compiled
`df0a8d1d`. The timed block's starts found them there.

- With 1.1.1's settings the lines applied in all 6 untimed starts, from each route's first, which compiled them, and in
  all 14 starts of the timed block. Native 2× uses three of the five lines; 3× with MFG Unlocker uses three, two of
  them different from native's.
- With 1.1.0's settings, in the same session, none applied (2 untimed starts and the timed block's 14).
- First start with 1.1.1's settings on each route: 2–4 s longer than 1.1.0's start before it, where compared. Untimed
  starts, which also compiled the pipelines: 59 s against 57 s on both routes, with frame generation up 2.3 s later at
  2× and 1.9 s at 3×. Timed block, which found them in Mesa's cache: the benchmark start took 122 s against 118 s at
  2×; at 3× it took 121 s, with no comparison (1.1.0's start ended during start-up). vkd3d-proton translates every
  pipeline into the new folder once. The first start on a computer that ran 1.0.x was not timed.
- Later starts: within 1 s of 1.1.0's (benchmark starts 118–120 s against 117–121 s).
- The folder held 35.5–36.2 MB after its first benchmark start and 36.0–36.7 MB after later ones.
- Frame rate in one block, 1.1.1's launch settings against 1.1.0's on the same files:

  | Condition | n | 1.1.0's settings | 1.1.1's settings | Difference |
  | --- | --- | --- | --- | --- |
  | 2× SDR | 4 | 104.28 ± 0.08 | 104.66 ± 0.18 | +0.36% ± 0.09 |
  | 2× HDR10 | 4 | 102.50 ± 0.13 | 103.15 ± 0.12 | +0.64% ± 0.09 |
  | 3× SDR, MFG Unlocker, `XeFGModel=default` | 3 | 127.87 ± 0.07 | 128.61 ± 0.08 | +0.58% ± 0.05 |

  Frames shown per second, mean ± SD; difference ± SE; one discarded warm-up start per arm and condition (1.1.0's at 3×
  ended during start-up, so that arm ran without one). Shader caches: Mesa's warm from 1.0.x in both arms, with the
  five pipelines compiled with their lines by the untimed starts; vkd3d-proton's warm identifier cache in 1.1.0's arm.
  In 1.1.1's arm, vkd3d-proton's new folder for the route, filled by the block's earlier starts on that route: from the
  2× SDR warm-up on at native 2× (HDR10 reused that folder), from the 3× warm-up on at 3×. A measured start had 1 to 4
  earlier starts in the folder at 2× SDR, 6 to 9 in HDR10 and 1 to 3 at 3×.
- [Live install](#live-install-and-restore), with the settings Setup wrote and the folder empty before each game's
  first start: the lines applied in every start whose shaders use them (3 of 3 in each of three starts). The folder held
  15.1 MB after Echo Point Nova's first start and 16.7 MB after its last, 35.5 MB after Cyberpunk 2077's one start.
  The timed block's first start on an empty folder (its discarded 2× SDR warm-up, same Mesa cache) ran at 104.52 FPS
  with no frame over 40 ms, the longest 33.1 ms.

Not measured: caches filled by XeSS frame generation without FreeFG (the game's own, or OptiScaler's) before
FreeFG was installed. With 1.1.0's launch settings, 1.0.0's wave sizes for four of Intel's shaders (five at 3× and 4×
on OptiScaler's frame generation) are expected to take no effect there either; with 1.1.1's, the lines are expected to
apply, because the cache folder is new.

## Checks of 1.0.0

1.0.0's proof-of-life qualification ([Status](README.md#status)) on the [test system](#test-system).

| Check | Result |
| --- | --- |
| Build | Reproducible byte for byte from source on the pinned toolchain ([BUILDING.md](BUILDING.md)). |
| Static check | Passes with no allowance ([NOTICE.md](NOTICE.md#the-shader-profile)). |
| Installer | Unit tests pass; an offline install and Restore return a throwaway game folder to its original files. |
| Wine loader check, no GPU | Loads and forwards to Intel's runtime; refuses a missing or altered runtime. With a stand-in module hooking eight of Intel's entry points, each call reaches it once with the caller it would see without FreeFG; only OptiScaler's contexts are accelerated (also a unit test). |
| Synthetic scenes, 2× | Generated images bit-identical to 0.9.0's (which match Intel's shaders where compared, [below](#generated-images-bit-identical)) in SDR 1440p, HDR10 1440p with pixel motion vectors and SDR 4K, five images each. Coefficient buffers verified; 2 frames per present. |
| Echo Point Nova (Steam, OptiScaler's frame generation) | 2×: accelerated, 2 frames per present. MFG Unlocker v1.6.0 with `XeFGModel=default`: 4× at 4 and 3× at 3 frames per present on FreeFG's shaders; one of two 3× starts ended during start-up with no error in any log, and the next start worked ([later starts](#start-up-exits-at-3)). MFG Unlocker's own model: 3× at 3, accelerated. HelixSR 2.0.0: its network ran, 2× accelerated at 2; OptiScaler's FSR 4 settings left its DLL alone; switching back to FSR 4 worked. |
| Cyberpunk 2077 (GOG through Heroic, the game's own XeSS FG), headless | Benchmark accelerated, 2.0 presents per game frame, 102.08 FPS: one run, not compared on the same day (0.9.0: 103.28 FPS on 16 October). A later same-day comparison found no measurable difference ([below](#100-against-090-at-2-same-day)). |
| Restore | Both game folders exactly as they were. |
| CONTROL Resonant (DLSS FG input), this release's OptiScaler | 32 of 32 starts reached the game; 2 presents per game frame in the 12 starts measured. |

Echo Point Nova was installed by this build's installer; its OptiScaler DLL was then replaced by hand with the one the
1.0.0 package ships.

Speed and further 3× and 4× checks: the two sections below.

Not covered: 3× and 4× on a VRR display and in their picture; changing the frame count in OptiScaler's menu while a game
runs; a game's own XeSS frame generation beside MFG Unlocker; games without a recipe; Flatpak Steam or Heroic; gameplay
and longer play sessions; pixel comparisons in games.

## 1.0.0 against 0.9.0 at 2×, same day

Setup:

- The Cyberpunk 2077 benchmark of [Frame rate](#frame-rate-cyberpunk-2077): headless, 2560×1440 SDR, FSR 4 Performance,
  the game's native XeSS frame generation at 2×, pacing layer on; 2026-10-20.
- Four arms (table). Each had one discarded warm-up start, then 4 runs in mirrored order (`A B B1 C C B1 B A`, twice).
  The rules were fixed before the first run: a run more than 1.0% from its arm's median is an outlier; between arms
  that differ in one component (B against A, A against C, B1 against B), a difference over 0.35% is a finding. B
  against C and B1 against C are summary lines, without that threshold.
- All 20 runs valid: 2.000 presents per game frame, accelerated, no `FAIL` line, no GPU error in the kernel log. No
  outliers.

| Arm | Proxy and shader profile | OptiScaler | `OptiScaler.ini` | FPS (presented), mean ± SD (n = 4) |
| --- | --- | --- | --- | --- |
| C | 0.9.0 | 0.9.0 | as 0.9.0 and 1.0.0 write it into an existing OptiScaler setup | 103.17 ± 0.20 |
| A | 0.9.0 | 1.0.0 | the same | 102.86 ± 0.37 |
| B | 1.0.0 | 1.0.0 | the same | 103.05 ± 0.11 |
| B1 | 1.0.0 | 1.0.0 | as 1.0.0 writes it into a fresh setup (`LoadAsiPlugins=true`: OptiPatcher loaded) | 102.71 ± 0.49 |

| Comparison | What differs | Difference (SE) |
| --- | --- | --- |
| B against C | 1.0.0 against 0.9.0 | −0.12% (0.11) |
| B against A | proxy and shader profile | +0.19% (0.19) |
| A against C | OptiScaler | −0.31% (0.20) |
| B1 against B | OptiPatcher loaded | −0.33% (0.24) |
| B1 against C | a fresh 1.0.0 setup against 0.9.0 | −0.45% (0.25) |

Results:

- In an existing OptiScaler setup, no measurable difference between 1.0.0 and 0.9.0 at 2× (−0.12%, SE 0.11), nor from
  the new proxy and shader profile alone (+0.19%, SE 0.19).
- The rebased OptiScaler and OptiPatcher loading are each about −0.3%, under the 0.35% threshold; most of each arm's
  spread comes from one low run (A 102.31, B1 102.02 FPS).
- A fresh 1.0.0 setup, which loads OptiPatcher, is −0.45% (SE 0.25) against 0.9.0: over 0.35% as a point estimate,
  under two standard errors. It is the sum of the three single changes (−0.31%, −0.33%, +0.19%), each under the
  threshold.
- 0.9.0 ran at 103.17 FPS, as in its [earlier series](#frame-rate-cyberpunk-2077) (103.28). The single 1.0.0 run of the
  [checks](#checks-of-100), about 1% lower on another day, did not repeat.

Not covered: HDR10; the OptiFG route; a display; other games.

## 3× and 4× with MFG Unlocker

Setup:

- The Cyberpunk 2077 benchmark, headless, 2560×1440 SDR, FSR 4 Performance, on OptiScaler's frame generation (OptiFG)
  with the game's own frame generation off, MFG Unlocker v1.6.0 as in [README.md](README.md#3-and-4-with-mfg-unlocker)
  with `XeFGModel=default`, at 3× or 4×.
- The block of [Frame rate](#frame-rate-cyberpunk-2077) (2026-10-20 to 21), same three arms. MFG Unlocker alone is the
  Intel's-shaders arm: 1.1.0's files with `BC250_XEFG_DISABLE=1`, so the proxy only forwards and MFG Unlocker runs with
  Intel's shaders. The layer also set wave size 32 for five of Intel's shaders there (lines 1.0.0 already had), as in
  the other arms. Shader caches [warm](#shader-caches), 1.1.0's launch settings.
- Headless output at 240 Hz, so no arm reached the refresh limit. Pacing layer off (`BC250_XEFG_PACE=0`), as in the
  [earlier series](#earlier-series-100-both-models). Frames shown per second = frames per present × game FPS (the
  benchmark's frames over its duration); every run had 3 or 4 frames per present as set.
- Per frame count, one discarded warm-up per arm, then mirrored runs (`I A C C A I I A C C A I` at 3×, `C A I I A C` at
  4×; I is MFG Unlocker alone, A 1.0.x, C 1.1.0): 4 runs per arm at 3×, 2 at 4×. All runs valid; no outliers at 3×
  (with 2 runs, 4× has no outlier rule).

| Frame count | MFG Unlocker alone | FreeFG 1.0.x | FreeFG 1.1.0 | 1.1.0 against MFG Unlocker alone (SE) | 1.1.0 against 1.0.x (SE) |
| --- | --- | --- | --- | --- | --- |
| 3× (n = 4), frames shown per second | 93.50 ± 0.11 | 125.31 ± 0.03 | 127.91 ± 0.18 | +36.80% (0.13) | +2.08% (0.07) |
| 3×, game FPS | 31.17 | 41.77 | 42.64 | | |
| 4× (n = 2), frames shown per second | 97.65 ± 0.06 | 139.87 ± 0.08 | 143.52 ± 0.08 | +46.98% (0.09) | +2.61% (0.06) |
| 4×, game FPS | 24.41 | 34.97 | 35.88 | | |

Results:

- 1.1.0 saves 4.32 ms (3×) and 4.36 ms (4×) per generated frame against MFG Unlocker alone, and 0.24 ms against
  1.0.x at both. Saved per generated frame = (1 / game FPS alone − 1 / game FPS FreeFG) / (frames per present − 1).
- 1.0.x against MFG Unlocker alone: +34.01% (3×) and +43.23% (4×), as in the earlier series (+34.1%, +43.1%).
- The 4× figures have 2 runs per arm.

![Cyberpunk 2077 frames shown per second with MFG Unlocker and XeFGModel=default on an AMD BC-250 (2560×1440 SDR, FSR 4 Performance, headless): at 3×, MFG Unlocker alone 93.50 and FreeFG 1.1.0 127.91 (+36.8%); at 4× (2 runs per arm), 97.65 and 143.52 (+47.0%).](../../docs/assets/mfg-3x4x-fps.svg)

Frames shown per second (frames per present × game FPS), as in the 2× figure. Headless at 240 Hz, SDR, pacing off,
warm shader caches; n = 4 per arm at 3×, n = 2 at 4×.

### Earlier series: 1.0.0, both models

Setup:

- The benchmark and settings above, on 2026-10-20 (morning), in their own blocks.
- 1.0.0's files as its installer writes them, plus MFG Unlocker v1.6.0 as in
  [README.md](README.md#3-and-4-with-mfg-unlocker), at 3× or 4×, with `XeFGModel=default` and without it (MFG
  Unlocker's own model).
- FreeFG, accelerated beside MFG Unlocker, against MFG Unlocker alone: the same files with `BC250_XEFG_DISABLE=1`, so
  the proxy only forwards. The network then runs on Intel's shaders, except the programs MFG Unlocker's own model
  replaces.
- The headless output ran at 240 Hz, so no arm reached the refresh limit (at most 140 presents per second; at 120 Hz, 3×
  and 4× are capped by the refresh rate).
- Pacing layer off (`BC250_XEFG_PACE=0`) in every run, by a rule fixed beforehand: in a check run, the paced 3× arms'
  release intervals differed by more than 10%, following their present rates. One paced run per arm at 3× gave the
  same gain (+33.9%).
- Per model, one discarded warm-up start per arm, then 2 runs per arm in mirrored order. Game FPS counts real frames
  (the benchmark's frames over its duration).
- Excluded by the same rules: 3 of the 16 timed runs, all at 4×, during which another process used 28–61% of a CPU
  core. With them, the 4× gains are +43.1% (`default`) and +17.0%.

| Frame count, model | MFG Unlocker alone, game FPS | FreeFG, game FPS | Gain | Saved per generated frame |
| --- | --- | --- | --- | --- |
| 3×, `default` | 31.14 (n = 2) | 41.77 (n = 2) | +34.1% (SE 0.1) | 4.09 ms |
| 4×, `default` | 24.44 (n = 1) | 34.98 (n = 1) | +43.1% | 4.11 ms |
| 3×, MFG Unlocker's model | 31.43 (n = 2) | 34.77 (n = 2) | +10.6% (SE 0.4) | 1.52 ms |
| 4×, MFG Unlocker's model | 23.93 (n = 1) | 27.92 (n = 2) | +16.7% | 1.99 ms |

Saved per generated frame = (1 / FPS alone − 1 / FPS FreeFG) / (frames per present − 1).

Results:

- With `XeFGModel=default`, FreeFG saves 4.1 ms per generated frame at both 3× and 4×; the game runs 34% faster at
  3× and 43% at 4×. At 2×, the same formula gives 4.02 ms in the [Cyberpunk benchmark](#frame-rate-cyberpunk-2077)
  (the game's own XeSS frame generation, pacing on).
- On MFG Unlocker's model, FreeFG replaces 7 shaders instead of 13 and gains 11% and 17%. With FreeFG, `default`
  is 20% (3×) and 25% (4×) faster than MFG Unlocker's model; MFG Unlocker alone is within about 2% on either model.
- Presents per second (frames per present × game FPS), `default`: FreeFG 125 at 3× and 140 at 4×, MFG Unlocker alone
  93 and 98.
- Every run at a fixed frame count had 3 or 4 frames per present as set, no `FAIL` line and no GPU error in the kernel
  log; the warm-ups were within 0.3% of the measured runs.

HDR10, FreeFG with `default`, one run each after a warm-up (MFG Unlocker alone was not run in HDR10, so there is no
HDR10 gain):

| | 3× | 4× |
| --- | --- | --- |
| HDR10, game FPS | 40.61 | 33.78 |
| SDR (table above) | 41.77 | 34.98 |
| HDR10 cost | −2.8% | −3.4% |

Dynamic MFG: one run with `[XeFG] DynamicMFG=true` (at most 4×) at 120 Hz. OptiScaler changed the frame count six
times between 4× and 2×; the proxy followed each change, stayed accelerated and logged no `FAIL` line (48.0 game FPS).

### Start-up exits at 3×

In 1.0.0's [checks](#checks-of-100), one of two 3× starts in Echo Point Nova ended during start-up. In the 1.0.0
series above, none of 18 starts at 3× with `default` ended early: 14 with FreeFG (12 SDR, 8 of them with empty shader
caches; 2 HDR10) and 4 with MFG Unlocker alone. The 8 empty-cache starts were short starts, not benchmark runs: each ran
until 3 frames per present were seen and 10 s more, half of them under Wine debug tracing. From that series alone, the
rate per start with FreeFG in this game is at most 19.3% at 95% confidence. That series' 23 other starts (2× to 4×,
both models, Dynamic MFG) also ran to the end. In 1.1.0's block, all 24 starts at 3× and 4× (8 of them with 1.1.0) ran
to the end. In 1.1.1's timed block ([shader caches](#shader-caches)), one of 8 starts at 3×, all with FreeFG 1.1.0's
files and MFG Unlocker, ended during start-up 32 s in, after its first present (exit code 0, no kernel message): a
discarded warm-up with 1.1.0's launch settings. In 1.1.1's [live install](#live-install-and-restore), one of three
starts at 3× in Echo Point Nova (one with `default`, two with MFG Unlocker's own model) ended during start-up 15 s in,
with MFG Unlocker's own model, after the XeFG context was created and before any present (no kernel message); its
repeat ran to the main menu. None of the three exits is explained.

Not covered: a VRR display, and the picture at 3× and 4× (MFG Unlocker's authors report misplaced outer frames with
`default` at 6×); pacing on, beyond one run per arm at 3× with 1.0.0; HDR10 with MFG Unlocker alone; 1.1.0 on MFG
Unlocker's own model and in HDR10 at 3× and 4×; other games; a game's own XeSS frame generation, where FreeFG
accelerates nothing beside MFG Unlocker; gameplay. At 3840×2160, [4K](#4k) has single runs of the cases in 1.1.0.

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

1.1.0 was compared directly with Intel's shaders' images in 20 configurations, F4Q on and off:
[checks of 1.1.0](#checks-of-110).

Not covered: real game content; pixel comparisons in games; other resolutions; long sessions.

## Frame rate: Cyberpunk 2077

Setup:

- Cyberpunk 2077 2.31 (GOG build, started by the test harness with no save loaded), built-in benchmark, one pass per
  run, headless; 2560×1440 output at a fixed 120 Hz, FSR 4 Performance, ray tracing off, the game's native XeSS frame
  generation at 2×, pacing layer on. FPS is the benchmark's average, which counts generated frames: frames shown per
  second.
- One block, 2026-10-20 to 21, with three arms: Intel's shaders, FreeFG 1.0.x (1.0.0's files) and FreeFG 1.1.0
  (its proxy and shader profile, F4Q on by default, no switch set). The test harness placed each arm's files, not
  Setup. The Intel's-shaders arm is 1.1.0's files with `BC250_XEFG_DISABLE=1`: the proxy accelerates no context, so
  Intel's runtime runs its own shaders, with the same OptiScaler, `OptiScaler.ini` and pacing layer. The layer also set
  wave size 32 for four of Intel's shaders there (lines 1.0.0 already had), as in the other arms; XeFG without the
  layer was not measured. Shader caches [warm](#shader-caches), 1.1.0's launch settings.
- Per condition, one discarded warm-up start per arm, then 4 runs per arm in mirrored order (SDR `I A C C A I I A C C A
  I`, HDR10 `C A I I A C C A I I A C`; I is Intel's shaders, A 1.0.x, C 1.1.0). The rules were fixed before the first
  start. All runs valid: 2.000 presents per game frame, no `FAIL` line, no GPU error in the kernel log. No outliers.
  Figures are means ± sample standard deviation.

| Condition | Intel's shaders, FPS (n = 4) | FreeFG 1.0.x, FPS (n = 4) | FreeFG 1.1.0, FPS (n = 4) | 1.1.0 against Intel's shaders (SE) | 1.1.0 against 1.0.x (SE) |
| --- | --- | --- | --- | --- | --- |
| SDR | 85.30 ± 0.07 | 102.93 ± 0.05 | 104.34 ± 0.06 | +22.31% (0.06) | +1.37% (0.04) |
| HDR10 | 83.98 ± 0.22 | 101.24 ± 0.07 | 102.45 ± 0.07 | +22.00% (0.16) | +1.20% (0.05) |

Results:

- 1.1.0 against Intel's shaders: +22.31% in SDR and +22.00% in HDR10; 9.58 against 11.72 and 9.76 against 11.91 ms
  per displayed frame. 1.0.x in the same block: +20.66% and +20.56%.
- 1.1.0 against 1.0.x: +1.37% (SE 0.04) in SDR and +1.20% (SE 0.05) in HDR10, 0.26 and 0.23 ms less per generated
  frame. Of 1.1.0's changes, the faster U-Net shaders and F4Q ran; the new wave sizes for five of Intel's shaders did
  not ([shader caches](#shader-caches)). In an earlier block (2026-10-20, SDR, warm caches), a build with 1.1.0's
  faster U-Net shaders and no F4Q code was +0.75% (SE 0.14) faster than 1.0.0, and F4Q, in a test build with the same
  kernels, added +0.50% (SE 0.08).
- Every FreeFG run took the accelerated path, with no `FAST_SKIP` or `FAST_FALLBACK` line; every 1.1.0 run logged
  F4Q on (`F4Q_CONFIG mode=on source=default`) with both its kernels and no `F4Q_FALLBACK`. No run with Intel's shaders
  replaced a shader.
- Benchmark minimum FPS: 1.1.0 94.5–95.4 (SDR) and 93.1–93.7 (HDR10); 1.0.x 93.3–93.7 and 92.1–92.7; Intel's shaders
  79.5–79.7 and 78.1–78.6.
- The layer held presents while XeFG generated in every run; its median release interval was 1000 / FPS in each arm.
- Earlier series:
  - 1.0.0, same day (2026-10-20, n = 4 per arm, two arms): Intel's shaders 85.40 ± 0.08 and 84.16 ± 0.07, FreeFG
    103.09 ± 0.13 and 101.28 ± 0.08 FPS (SDR and HDR10), +20.72% (SE 0.10) and +20.34% (SE 0.07). The 1.0.x and
    Intel's-shaders arms above are within 0.22% of these.
  - 0.9.0 on two days: 103.28 ± 0.09 FPS in SDR (n = 4) and 101.58 ± 0.15 in HDR10 (n = 2) on 2026-10-16; Intel's
    shaders, through an internal reference build's loader, 85.31 ± 0.08 in SDR (n = 4) on 2026-10-15. The SDR gain
    across the two days, +21.1% (bridged by the reference build: 103.05, then 103.03 FPS), agrees with 1.0.0's
    same-day result within 0.4 points.

Figure: [README.md](README.md).

Not covered: other resolutions (except [4K](#4k)) and upscaler modes; a real display, VRR and gamescope's real refresh behaviour (the
headless compositor runs a fixed 120 Hz timer); input latency; frame-time distribution and pacing quality; stock Mesa
without the compute queue; power and temperature; longer sessions; other shader-cache states
([shader caches](#shader-caches)).

## 4K

Setup:

- The Cyberpunk 2077 2.31 benchmark as in [Frame rate](#frame-rate-cyberpunk-2077), at 3840×2160, headless at 240 Hz
  (no arm reached it), FSR 4 Performance, SDR unless noted, 2026-10-21. 1.1.0's files, which 1.1.1 ships unchanged,
  with 1.1.0's launch settings, placed by the test harness; shader caches [warm](#shader-caches).
- Native: the game's own XeSS frame generation, pacing layer on (off for v30 at 3×); FPS is the benchmark's average.
  OptiScaler: OptiScaler's frame generation (OptiFG), with MFG Unlocker v1.6.0 where noted, pacing off; frames shown
  per second = frames per present × game FPS. The 2× OptiScaler rows are therefore not a route comparison with the
  native rows.
- Intel's shaders: 1.1.0's files with `BC250_XEFG_DISABLE=1`; at 3× that is MFG Unlocker alone with `XeFGModel=default`.
- v30, a private test build from before 0.9.0, on the native route: at full output size, and with its generated
  frames limited to 1080p (its generated-frame scaling). At 3× it ran through its own bundled multi-frame enabler, not
  MFG Unlocker.
- 2× rows with n ≥ 2: one discarded warm-up per arm, then mirrored runs. The 3× block was cut short, so its warm-ups
  count as runs. Rows with n = 1 are single starts. Every run had the set frames per present and no `FAIL` line.

| Frame count, arm | Route | n | Frames shown per second | Gain over no FG | FreeFG's shaders run on |
| --- | --- | --- | --- | --- | --- |
| No frame generation | – | 4 | 36.06 ± 0.07 | – | – |
| 2×, Intel's shaders | native | 3 | 42.70 ± 0.03 | +6.6 | – |
| 2×, FreeFG | native | 3 | 52.82 ± 0.04 | +16.8 | the whole network (13 `REPLACE` lines) |
| 2×, FreeFG, HDR10 | native | 1 | 51.92 | – | the whole network |
| 2×, FreeFG | OptiScaler | 1 | 53.25 | +17.2 | the whole network |
| 2×, FreeFG + MFG Unlocker, its own model | OptiScaler | 1 | 42.61 | +6.5 | part (7 `REPLACE` lines) |
| 2×, game's own XeSS FG with MFG Unlocker loaded | native | 1 | 39.80 | +3.7 | nothing (not accelerated) |
| 2×, v30, full size | native | 2 | 52.62 ± 0.07 | +16.6 | (v30) |
| 2×, v30, 1080p limit | native | 2 | 61.08 ± 0.11 | +25.0 | (v30) |
| 3×, MFG Unlocker alone, `default` | OptiScaler | 2 | 46.07 (45.97, 46.16) | +10.0 | – |
| 3×, FreeFG + MFG Unlocker, `default` | OptiScaler | 2 | 63.80 (63.87, 63.74) | +27.7 | the whole network |
| 3×, FreeFG + MFG Unlocker, its own model | OptiScaler | 1 | 50.73 | +14.7 | part (7 `REPLACE` lines) |
| 3×, FreeFG + MFG Unlocker, `default`, HDR10 | OptiScaler | 1 | 61.76 | – | the whole network |
| 3×, v30, full size / 1080p limit | native | 1 / 1 | 64.2 / 78.1 | +28.1 / +42.0 | (v30) |
| 4×, FreeFG + MFG Unlocker, `default` | OptiScaler | 1 | 70.8 | +34.8 | the whole network |

Means ± sample standard deviation; gains in frames shown per second. HDR10 has no run without frame generation, so no
gain.

Results:

- FreeFG saves 9.0 ms per generated frame against Intel's shaders at 4K: 8.97 ms at 2× and 9.05 ms at 3×, against
  4.28 and 4.32 ms at 1440p ([Frame rate](#frame-rate-cyberpunk-2077), [3× and 4×](#3-and-4-with-mfg-unlocker)): 2.1
  times the saving for 2.25 times the pixels. Saved per generated frame = (1 / game FPS Intel's shaders − 1 / game FPS
  FreeFG) / (frames per present − 1). At 2×, frames shown per second +23.7% (SE 0.06).
- At full output size and 2×, FreeFG matches v30 within 0.4% (+0.38%, SE 0.10). v30's 1080p limit was faster:
  +15.6% at 2×, and +22% at 3× (v30: one warm-up start, on the native route with its own enabler, against
  OptiScaler's frame generation with MFG Unlocker). FreeFG generates frames at the full output size; it has no
  generated-frame scaling.
- On MFG Unlocker's own model, FreeFG's shaders replace 7 of Intel's programs instead of 13 at every frame count:
  at 2×, 42.61 against 53.25 frames shown per second without MFG Unlocker; at 3×, 50.73 against 63.80 with
  `default`.
- With the game's own XeSS frame generation and MFG Unlocker loaded, FreeFG did not accelerate that context, as
  designed ([ARCHITECTURE.md](ARCHITECTURE.md#optiscalers-contexts-only)): 39.80, below Intel's shaders without MFG
  Unlocker.

Not covered: other games; a real display and VRR; gameplay; HDR10 without frame generation; 4× with Intel's shaders or
v30; pacing on with OptiScaler's frame generation.

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
- On the TV the benchmark runs about 4% below the headless figures (about 99 against 103 FPS in SDR, 97 against 101 in
  HDR10).

The figure's first two rows come from an earlier session with the same harness and TV (2026-09-29; earlier private
builds, no compute queue; 2 runs without pacing and 3 with a layer that paces from the game's queue, 30 s each). They
show what pacing does and are not FreeFG measurements; the FreeFG row pools the four SDR runs of the table above.
Commit intervals over 1.5× their run's median: 577 without pacing, 3 with it.

![Intervals between display commits on a VRR TV, Cyberpunk 2077 at 2×, SDR, 5th to 95th percentile: earlier build unpaced 4.8–16.4 ms and paced 9.0–11.1 ms; FreeFG 0.9.0 8.9–11.0 ms.](../../docs/assets/vrr-pacing.svg)

Not covered: Intel's shaders; gameplay; a game started by Steam or Heroic (the harness runs the game beside Steam's own
interface, which can delay gamescope's commits differently); the OptiFG route; what the TV itself shows (commit
intervals mark when gamescope's frame reaches the kernel; the TV's own frame repeats or re-locks are not measured);
input latency; other displays.

## GPU time per generated frame

Setup:

- Measured with 0.9.0's shaders, which 1.0.x keeps at 2×; 1.1.0's faster U-Net shaders and F4Q are not in this
  breakdown.
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

For scale: in the Cyberpunk benchmark, the time per real frame at 2× fell by 4.02 ms with 1.0.0 (23.42 to 19.40 ms;
85.40 to 103.09 FPS) and by 4.28 ms with 1.1.0 in its own block (23.45 to 19.17 ms; 85.30 to 104.34 FPS), a whole game
frame with the game's own work and waits, so the numbers need not match.

![GPU time per generated frame at 2×: 9.76 ms with Intel's shaders, 4.50 ms with FreeFG 0.9.0; in the stages it replaces, 5.12 to 1.93, 1.24 to 0.44 and 1.29 to 0.56 ms.](../../docs/assets/gpu-time-per-generated-frame.svg)

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
- On the OptiFG route nothing reports the number of generated frames, so the ratio there was not measured in these
  two rounds.

**1.1.1** (2026-10-21, the second round's method and games, with 1.1.1's package): Setup wrote both vkd3d-proton launch
settings (in Steam's launch options in both accounts, in Heroic's settings) and `XeFGModel=default` under `[XeFG]`.
Echo Point Nova started from Steam to the main menu; Cyberpunk 2077's benchmark was started headless by the test harness
with the settings Setup wrote for Heroic.

| Start | `waves.txt` lines for Intel's shaders | Status after the start | Frames shown per game frame |
| --- | --- | --- | --- |
| Echo Point Nova, 2× | 3 of 3 applied | full, 13 of 13 programs | 2.00 |
| Cyberpunk 2077, native 2× | 3 of 3 applied | full, 13 of 13 programs | 2.001 |
| Echo Point Nova, 3×, MFG Unlocker, `XeFGModel=default` | 3 of 3 applied | full, 13 of 13 programs | 3.01 |
| Echo Point Nova, 3×, MFG Unlocker's own model | none used | partial, 7 of 13 programs, and the fix (`XeFGModel=default`) | 3 (SDK status) |

- Echo Point Nova's ratios are indirect: from the count the add-on writes for the pacing layer, per present,
  calibrated on the Cyberpunk 2077 start. FreeFG's SDK status line gave 2 and 3 frames per present. Check gave
  the same acceleration lines as Status.
- Before the first start, Status reported a log a private test build from before 0.9.0 had left under `OptiScaler/` as
  the last run ("full", 16 programs in Echo Point Nova, 19 in Cyberpunk 2077). Fixed after the live install: Status and
  Check read only the logs beside the `.exe` written since the installation (installer tests; not repeated live).
- One 3× start ended during start-up ([start-up exits](#start-up-exits-at-3)).
- After Restore: as in the second round, with the `vkd3d-cache` folder and the `XeFGModel` line gone. Before Restore,
  MFG Unlocker's files were removed and Echo Point Nova's `OptiScaler.ini`, which OptiScaler and the MFG Unlocker steps
  had changed, was set back to the bytes Setup wrote, so Restore met an unchanged file. The kernel logged no GPU
  message.

Not covered: gameplay; a game started from Heroic itself (with its cloud saves); the desktop Setup window; Lutris;
Flatpak launchers.
