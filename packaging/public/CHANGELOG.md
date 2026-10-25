# Changelog

Changes in each release of FreeFG. The private test builds made before 0.9.0 are not covered.

## 1.1.3.1 – 2026-10-25

- Use wave64 for the 224-channel Winograd input-transform shader on the BC-250. Its wave32 selection triggered an
  early GPU fault in Cyberpunk 2077 2.5 with HelixSR; changing only this wave setting passed the full SDR and HDR10
  benchmarks. The choice applies to this shader in every game, at every frame-generation factor, without a game recipe.
- The shader bytes and arithmetic are unchanged. The proxy is rebuilt to accept the updated profile; OptiScaler,
  the presentation layer, upscalers and game recipes remain 1.1.3's. The exact cause beneath the wave32 trigger is still
  under investigation. [Checks and scope](MEASUREMENTS.md#checks-of-1131).
- Update through Restore in the existing release, then Install from 1.1.3.1. Copying just `waves.txt` is insufficient:
  the proxy verifies its profile's hashes.

## 1.1.3 – 2026-10-25

- Restore adaptive game-frame starts at 3×/4× through the bundled OptiScaler's XeLL output. Sustained short/long
  simulation intervals are corrected before they become uneven motion. The controller resets after a burst of stalls;
  `BC250_XELL_PACE=0` disables it for comparison.
- Let the VRR presentation layer adapt its jitter allowance to the SDK's actual frame count (5/10/15 ms ceilings at
  2×/3×/4×), with enough hold range for 4×. Reserve extra swapchain images, within the surface's limit, so held frames
  do not block new GPU work and cause a slow recovery after a hitch. The timing policy at 2× keeps its previous values.
- Keep the shader profile, Intel runtime, FSR 4 and HelixSR selection unchanged. The library-path correction
  below is included. The source README also incorporates the wording changes made on GitHub after 1.1.2.
- Live pacing checks: CONTROL Resonant, HelixSR, GE-Proton 11-11, 2560×1440 HDR/VRR at 120 Hz, 2×/3×/4×, camera motion,
  factor changes and controlled stalls. [Measurements and limits](MEASUREMENTS.md#checks-of-113).
- Fix the bundled OptiScaler's library-path reader: `XeSSPath`, `XeFGPath` and `XeLLPath` now configure their own
  libraries. Previously, the FG and latency paths could become the XeSS upscaler path and be saved under that key,
  causing a failed XeSS load.
- Install and Settings repair the known saved `XeSSPath` values pointing to `libxess_fg.dll` or `libxell.dll`, using
  automatic XeSS upscaler discovery. Other custom upscaler paths and unrelated settings are preserved. Updating an
  existing installation still uses Restore, then Install from this release, to replace the bundled OptiScaler DLL.

## 1.1.2 – 2026-10-24

Faster U-Net and refinement kernels, and FSR 4 RC12. By default the generated frames differ slightly from Intel's (the
FP16 forms below); `BC250_XEFG_EXACT=1` gives output identical to Intel's in every test. The proxy, the shader profile and
the FSR 4 build change; the pacing layer, OptiScaler and Intel's runtime pin are 1.1.1's. Setup and Status are 1.1.1's
plus the new key, the log line and the FSR 4 build's name.

In Cyberpunk 2077 (headless, one block per condition, n = 6 per arm, both builds with FSR 4 RC12), 1.1.2 at its default
shows 1.64% (SE 0.08) more frames per second than 1.1.1 at 2× in SDR and 1.50% (SE 0.11) in HDR10. Shader caches: new
for each block, filled by one warm-up start per build ([MEASUREMENTS.md](MEASUREMENTS.md#checks-of-112)).

### Changed

- **FP16 forms, on by default** (while F4Q is on): seven U-Net kernels run in faster forms whose outputs differ slightly
  from the exact forms' ([ARCHITECTURE.md](ARCHITECTURE.md#fp16-forms-the-default-slightly-different)). F4Q2's three
  F(4×4) kernels read their coefficients as FP16 pairs; four F(2×2) kernels multiply and add in packed FP16. With a test
  build of the same kernels, on 19 synthetic SDK scenes, the generated images differ from Intel's in 0.12–16.2% of
  pixels, with an error against the scenes' analytic truth of 0.985–1.007× Intel's. No quality gate has passed these
  images.
- **Exact switch**: `BC250_XEFG_EXACT=1` in the launch options, or `Exact=1` under `[BC250]` in the game folder's
  `BC250-XeFG/settings.ini`, turns the FP16 forms off. Every kernel then runs its exact form, and the generated images
  were identical to Intel's in every test. Setup keeps the key on reinstall; the launch option wins. Its frame rate in a
  game was not measured.
- F4Q2, on by default while F4Q is on: the U-Net encoders `1a3b0782`, `e83e868f` and `9e0080ee` run Winograd F(4×4)
  kernels instead of F(2×2), as F4Q's two layers do since 1.1.0. `BC250_XEFG_F4Q2=0` or `F4Q2=0` turns F4Q2 off: those
  three layers then run their F(2×2) kernels, also by default (without their FP16 form).
- F4Q3, on by default while F4Q is on: the U-Net row layers `60edebbb` and `b3ddf030` run F(4×4) kernels instead of their
  1D F(2,3) kernel. No switch of its own.
- F4Q, F4Q2 and F4Q3 were identical to the kernels they replace in every test, but are not proven for every input
  ([ARCHITECTURE.md](ARCHITECTURE.md#f4q-identical-in-every-test-not-proven)). F4Q's switch (`BC250_XEFG_F4Q=0`, `F4Q=0`)
  turns off all of them and the FP16 forms: the U-Net then runs 1.1.1's F(2×2) and 1D kernels.
- Exact by construction, no switch: F4Q's decoder fills and transforms in packed 16-bit arithmetic; F4Q's two kernels
  skip thread groups wholly below the output; the fused flow refinement runs 32 × 4 px groups and divides by a shift.
- GPU time in the SDK test program, measured with test builds of the same kernels (2× at 2560×1440, ms per generated
  frame, SDR / HDR10): F4Q2 0.097 / 0.142–0.146; F4Q3 and the exact changes 0.117 / 0.169; the FP16 forms on top 0.125 /
  0.185. The HDR10 runs ran at lower GPU clocks than games do (1,220–1,490 MHz), so their figures overstate the saving at
  game clocks ([MEASUREMENTS.md](MEASUREMENTS.md#checks-of-112)).
- `waves.txt` lists 142 shaders (1.1.1: 130): the new kernels at wave size 32. `dispatch-scale.txt` gains identity rows
  for the two row layers.
- The shader profile holds 61 files, 52 of them shaders (1.1.1: 49 and 40). The package's `settings.ini` has `F4Q2=1`
  and `Exact=0` lines.
- The FSR 4 option installs the BC-250 build RC12 (`4.1.1r12`) instead of RC11, and Status names the build a game has.
  In its project's checks RC12's images were byte-identical to RC11's; its GPU time per frame was 0.41–0.43 ms lower at
  1920×1080 output and unchanged at 2560×1440 ([RC12](https://github.com/daniel-h-0/bc250-fsr4-fork/releases/tag/v4.0.0-rc12)).

### Added

- Fast-log lines `FP16_CONFIG` (the FP16 forms' state and what set it), `FP16_SEGMENT`, `FP16_REPLACE`, `FP16_FALLBACK`,
  `F4Q2_CONFIG`, `F4Q3_CONFIG`, `WINO_REF64_GROUPS`; with `BC250_XEFG_F4Q_SHADOW=1`, the diagnostic also covers F4Q2's
  and F4Q3's layers ([TROUBLESHOOTING.md](TROUBLESHOOTING.md#logs)). Status and Check name the output form of the last
  session (`Output:` line).
- Release builds use the pinned toolchain: `release/toolchain.py` unpacks the package files pinned in
  `release/ci/ci.lock.json` into a folder of their own, and `XEMFG_TOOLCHAIN=pinned` builds with it
  ([BUILDING.md](BUILDING.md#the-pinned-toolchain)). With it, 1.1.1's proxy and pacing layer rebuild byte for byte on a
  host whose own compilers no longer do.

### Checked

Results, conditions and what was not checked: [MEASUREMENTS.md](MEASUREMENTS.md#checks-of-112).

## 1.1.1 – 2026-10-21

Wave sizes now apply on every start, and Setup sets `XeFGModel=default` for MFG Unlocker. Only the installer
and the documents change; the proxy, pacing layer, shader profile and OptiScaler are 1.1.0's.

In Cyberpunk 2077 (headless, one block), 1.1.0's files with 1.1.1's launch settings show 0.36% more frames per second
than with 1.1.0's at 2× in SDR, 0.64% in HDR10 and 0.58% at 3× with MFG Unlocker and `XeFGModel=default`. Shader
caches: Mesa's warm from 1.0.x, the new vkd3d-proton cache filled by 1 to 9 earlier starts on the same route
([MEASUREMENTS.md](MEASUREMENTS.md#shader-caches)).

### Changed

- Setup adds two launch settings for vkd3d-proton:
  - `VK_EXT_shader_module_identifier` is added to `VKD3D_DISABLE_EXTENSIONS`, after any entries already there.
  - `VKD3D_SHADER_CACHE_PATH` names a new folder, `vkd3d-cache`, in the game's backup folder `.bc250-xefg-experimental`.
    A cache path you set yourself is kept, including `0` (no cache).
  - Effect: vkd3d-proton keeps each pipeline's shader code in its cache, so the pacing layer sets the wave size of every
    shader in `waves.txt` on every start.
  - Before: vkd3d-proton cached only an identifier, and a pipeline compiled before its line existed came back without
    it. That left 1.1.0's five new lines for Intel's shaders inert for players who had run 1.0.x.
- The first start after an installation takes longer: vkd3d-proton translates every pipeline's shader into its new
  cache once. In these runs it took 2–4 s longer in Cyberpunk 2077; the first start on a computer that ran 1.0.x was
  not timed. The cache holds 35–37 MB in Cyberpunk 2077. Later starts were within 1 s of 1.1.0's.
- Restore puts both launch settings back as they were and deletes the `vkd3d-cache` folder. A new installation starts
  a new one.
- A game folder whose path is longer than 178 characters minus the length of the `.exe` name (161 for
  `Cyberpunk2077.exe`) gets neither setting, as in 1.1.0, and Setup says so: vkd3d-proton cuts longer cache file names
  short.
- `install.py status` names the cache folder and its size.
- Setup writes `[XeFG] XeFGModel=default` to `OptiScaler.ini` where it is unset, on both routes, and keeps a value you
  set, also across Restore and a new installation. Only MFG Unlocker reads the key; with `default`, FreeFG's shaders
  run the whole network beside it, at every frame count ([README](README.md#3-and-4-with-mfg-unlocker)).
- Status and Check name a partial acceleration (MFG Unlocker's own model), a skipped one (the game's own XeSS frame
  generation beside MFG Unlocker) or a context that stepped aside, and how to fix it. Status says when
  `BC250-XeFG-fast.log` is from an earlier session. Status and Check read only the logs beside the `.exe` written since
  the installation: in the live install, before the first start, Status had reported a log a private test build from
  before 0.9.0 left under `OptiScaler/` as the last run (fixed after it; checked in the installer tests).

### Documents

- MEASUREMENTS' [Shader caches](MEASUREMENTS.md#shader-caches) adds 1.1.1's checks and block. The figures stay on
  1.1.0's block, with 1.1.0's launch settings.
- MEASUREMENTS adds [4K](MEASUREMENTS.md#4k): Cyberpunk 2077 at 3840×2160 with 1.1.0's files. FreeFG saves 9.0 ms per
  generated frame against Intel's shaders (4.3 ms at 1440p) and equals v30, a private test build, at full output size
  and 2×.
- README's [MFG Unlocker section](README.md#3-and-4-with-mfg-unlocker) starts with its two conditions (OptiScaler's
  frame generation, `XeFGModel=default`); README notes that on OptiScaler's frame generation the game's FPS counter
  counts only rendered frames.
- TROUBLESHOOTING adds [Frame generation adds little](TROUBLESHOOTING.md#frame-generation-adds-little): the log lines of
  each case, what to do, and why earlier test builds' 1080p limit is faster at 4K.

### Checked

- Without a GPU: the installer tests (385 tests, 23 new: the launch settings in Steam, Heroic and Lutris, Restore
  byte for byte, reinstall, a cache path you set, a game folder path too long for vkd3d-proton's file names;
  `XeFGModel` and the new Status and Check lines), the release-tool tests and the public-tree export. The new Status
  and Check lines also classified the logs of the 35 Cyberpunk 2077 runs of [4K](MEASUREMENTS.md#4k) as measured.
- Cyberpunk 2077, headless, untimed (3 starts at native 2× and 3 at 3×, Mesa's cache warm from 1.0.x): with 1.1.1's
  launch settings, every start applied 1.1.0's new lines for the Intel shaders its route uses, including each route's
  first start, which compiled the pipelines not yet compiled with their lines (three at 2×, two at 3×). With 1.1.0's
  settings, none applied.
- Cyberpunk 2077, headless, timed: one block of 28 starts, 1.1.1's launch settings against 1.1.0's, on the same
  files ([MEASUREMENTS.md](MEASUREMENTS.md#shader-caches)). One discarded 3× warm-up start with 1.1.0's settings
  closed during start-up; every measured start ran the benchmark.
- Live install, once on each route, with the installer's command line and the Automatic input
  ([MEASUREMENTS.md](MEASUREMENTS.md#live-install-and-restore)): Echo Point Nova from Steam to the main menu (OptiFG;
  2×, 3× with MFG Unlocker and `XeFGModel=default`, 3× with MFG Unlocker's own model) and Cyberpunk 2077's benchmark
  (native XeSS FG, headless, with the settings Setup wrote for Heroic). Setup wrote both launch settings and
  `XeFGModel=default`; the wave lines applied in every start whose shaders use them; Status and Check named full
  acceleration (13 of 13 programs) with `default` and partial (7 of 13) with the fix on MFG Unlocker's own model;
  Restore left both game folders and launcher entries as before.

### Known limitations

- In the live install, one of three 3× starts in Echo Point Nova (MFG Unlocker's own model) ended during start-up; its
  repeat ran ([MEASUREMENTS.md](MEASUREMENTS.md#start-up-exits-at-3)).
- Not checked: the Setup window, a game started from Heroic itself, gameplay, a VRR display, other games, and caches
  filled by the game's own XeSS frame generation before any FreeFG install. In that last state the effect is expected
  to be the same, because the cache folder is new, but it was not measured.

## 1.1.0 – 2026-10-21

Faster generated frames. The proxy and the shader profile change; the pacing layer, OptiScaler, Intel's runtime pin
and the installer are 1.0.1's.

In Cyberpunk 2077 (headless, one block, warm shader caches), 1.1.0 shows 1.4% more frames per second than 1.0.x at 2×
in SDR and 1.2% in HDR10; with MFG Unlocker and `XeFGModel=default`, 2.1% more at 3× and 2.6% at 4× (2 runs per arm).
Against Intel's shaders it shows 22% more at 2× ([MEASUREMENTS.md](MEASUREMENTS.md#frame-rate-cyberpunk-2077)). The
gain comes from the faster U-Net shaders and F4Q; the new wave sizes for five of Intel's shaders took no effect in
these runs.

### Changed

- Nine of the network's U-Net shaders compute their input transform in FP16 pairs, which hold its small integers
  exactly; their results are unchanged.
- F4Q, on by default: two U-Net layers (the decoder `b3941ac8` and the encoder `f030948d`) run Winograd F(4×4)
  kernels instead of F(2×2), which need fewer multiplications. Their results were identical in every test, but they
  are not proven for every input ([ARCHITECTURE.md](ARCHITECTURE.md#f4q-identical-in-every-test-not-proven)). To turn
  F4Q off, set `BC250_XEFG_F4Q=0` in the launch options or `F4Q=0` under `[BC250]` in the game folder's
  `BC250-XeFG/settings.ini`; Setup keeps either on reinstall.
- `waves.txt` lists 130 shaders (1.0.x: 123): F4Q's two kernels, and five of Intel's shaders (four 2× warp shaders and
  a convolution) at wave size 32. These five lines took no effect in the Cyberpunk measurements, because the shader
  caches kept the pipelines compiled before the lines existed; no gain is claimed for them
  ([MEASUREMENTS.md](MEASUREMENTS.md#shader-caches)).
- The shader profile holds 49 files, 40 of them shaders (1.0.x: 42 and 33). The package's `settings.ini` has an
  `F4Q=1` line.

### Added

- `BC250_XEFG_F4Q_SHADOW=1`, a diagnostic: F4Q's kernels run beside the F(2×2) kernels, which keep the output, and
  the fast log counts equal and differing outputs ([TROUBLESHOOTING.md](TROUBLESHOOTING.md#environment-variables)).

### Documents

- Both figures show 1.1.0's block, in frames shown per second; 1.0.0's series are earlier series in MEASUREMENTS.
  README's 2× figure follows the intro.
- MEASUREMENTS adds [Shader caches](MEASUREMENTS.md#shader-caches), the cache state of the measurements.

### Checked

Results, conditions and what was not checked: [MEASUREMENTS.md](MEASUREMENTS.md#checks-of-110).

- Without a GPU: reproducible build hashes (also from the public source export), the shaders rebuilt byte for byte,
  the static check with no allowance, the Wine loader check with ten F4Q cases, the installer tests.
- On one BC-250, the SDK test program: generated images identical to Intel's shaders' in 20 configurations, with F4Q
  on and with it off.
- Cyberpunk 2077, headless: F4Q's diagnostic compared fingerprints of the two layers' outputs 96,480 times in 7
  benchmark runs (2× and 3×, SDR), none differing; one frame-rate block of 54 starts against 1.0.x and Intel's
  shaders; one start with `BC250_XEFG_F4Q=0`, which turned F4Q off.

### Known limitations

- F4Q is identical in every test, not proven for every input. In games it was compared only in Cyberpunk 2077, at 2×
  and 3× in SDR, with its diagnostic on.
- A `waves.txt` line applies only to pipelines that the shader caches do not already hold compiled without it. 1.1.0's
  new lines for five of Intel's shaders take no effect in a game that ran with 1.0.x, and are expected to take none in
  a game that ran its own XeSS frame generation before (not measured).
- Not checked with 1.1.0: a live install with Setup, other games, a VRR display, gameplay, MFG Unlocker's own model,
  HDR10 at 3× and 4×.

## 1.0.1 – 2026-10-20

The installer and the documents change. The proxy, pacing layer, shader profile and OptiScaler are byte-identical to
1.0.0's.

### Added

- An override of the anti-cheat refusal per game, at the risk of an account ban: Setup's **Override anti-cheat
  refusal...** or `install.py --accept-anticheat-risk` ([COMPATIBILITY.md](COMPATIBILITY.md#anti-cheat)). **Install
  anyway** and `--accept` still never lift it. Status and Check show the override until Restore.

### Changed

- Check lists anti-cheat as a refusal of its own kind (`[anticheat, risk, refused]`, before: `hard`) and names the
  override.

### Documents

- README and COMPATIBILITY name the 758 games with an OptiScaler wiki entry beside the 19 verified recipes.
- The figures carry less text; their captions give the conditions.
- MEASUREMENTS adds the two measurement series under Checked, with a figure. README recommends
  `XeFGModel=default` with MFG Unlocker for speed.

### Checked

- Without a GPU: the installer tests, an offline install and Restore, and CI.
- The payload is byte-identical to 1.0.0's, so 1.0.0's GPU [checks](MEASUREMENTS.md#checks-of-100) apply to it.
- Two measurement series with 1.0.0's files on one BC-250, Cyberpunk 2077 headless:
  - [1.0.0 against 0.9.0 at 2×](MEASUREMENTS.md#100-against-090-at-2-same-day), the same day: no measurable difference
    in an existing OptiScaler setup (−0.12%, SE 0.11); a fresh setup, which loads OptiPatcher, −0.45% (SE 0.25).
  - [3× and 4× with MFG Unlocker](MEASUREMENTS.md#3-and-4-with-mfg-unlocker), against MFG Unlocker alone with
    `XeFGModel=default`: +34% and +43% game frame rate (pacing off, 1–2 runs per arm). Also HDR10, Dynamic MFG, and no
    start-up exit in 18 starts at 3×.

## 1.0.0 – 2026-10-20

First public release. The proxy `libxess_fg.dll` is a new build with the multi-frame code compiled in. The figures in
[MEASUREMENTS.md](MEASUREMENTS.md) were measured with 0.9.0 and not repeated with this build.

### Added

- 3× and 4× with MFG Unlocker by dashdogy (<https://github.com/dashdogy/MFG-Unlocker>), a separate OptiScaler plugin
  that lifts Intel's limit of one generated frame per real frame on GPUs other than Intel's. FreeFG neither lifts
  that limit nor ships MFG Unlocker. With it, FreeFG's shaders run on the work that is still Intel's at every frame
  count, including five kernels of the multi-frame network (33 shaders in the package, 28 in 0.9.0). Without it,
  FreeFG generates 2×. Steps: [3× and 4× with MFG Unlocker](README.md#3-and-4-with-mfg-unlocker).
- Coexistence with a module that hooks Intel's runtime. The proxy passes each call on with the caller that module
  expects and accelerates only OptiScaler's own frame generation. Where it meets work it has not verified, it steps
  aside for that session (`FAST_ASIDE` in its log) instead of ending the game ([ARCHITECTURE.md](ARCHITECTURE.md)).
- Upscaler choice in Setup: FSR 4 (default) or HelixSR, a separate project by lonewolf0622. When HelixSR is chosen, the
  installer downloads its complete official release, pinned by hash; FreeFG ships none of it
  ([NOTICE.md](NOTICE.md#helixsr)).
- A compatibility verdict for every game, decided offline before anything is written (Setup's **Check**,
  `install.py check`): verified on BC-250, community-reported, automatic (guided by the OptiScaler wiki, or from
  detection), or not supported with the reason and the way forward. It comes from a read-only scan of the game and its
  launcher entry ([PRIVACY.md](PRIVACY.md) lists what is read). For a game without a recipe, Automatic takes the
  executable, route, input and DirectX 12 switch from the scan.
- Refusals before any download, some of them soft (accepted per game with **Install anyway**). Check also names what in
  the game folder Install would refuse. The list, with codes and ways forward:
  [COMPATIBILITY.md](COMPATIBILITY.md#refusals).
- OptiScaler wiki data at revision `9812e2d` (17 October 2026), with every condition a page states checked against your
  setup. An input the wiki reports broken is not chosen automatically. Six wiki fixes, reviewed by an agent and awaiting
  a maintainer's confirmation, are applied only where the game is identified by its launcher ID or by its executable and
  title (today FINAL FANTASY VII REBIRTH and Soulstice). Other wiki advice is shown with its condition.
- Community recipes from other BC-250 owners, with a report form and a review checklist
  ([CONTRIBUTING.md](CONTRIBUTING.md#game-recipes)). Their game settings are applied and restored key by key, as a
  verified recipe's are.
- Figures in README.md and MEASUREMENTS.md (Cyberpunk 2077 frame rate, GPU time per generated frame,
  VRR pacing, what Setup changes), each drawn from a data file in the repository.

### Changed

- OptiScaler is rebased on upstream master of 19 October 2026 (`c2e44a8b`), fork tag `bc250-f971ed1`
  ([NOTICE.md](NOTICE.md)). The start-up deadlock fix keeps upstream's Streamline plugin locks and takes them after the
  Windows loader lock, instead of reverting the upstream change.
- The proxy also counts the frames the runtime reports presented. The pacing layer therefore holds presents while XeFG
  generates at any frame count, also with Intel's shaders (`BC250_XEFG_DISABLE=1`) and on other GPUs, which 0.9.0 did
  not pace. `BC250_XEFG_STATUS_POLL=0` turns the proxy's own per-frame status read off.
- OptiScaler's built-in game fixes are read from the shipped build (`f971ed14`). The installer never writes a key one of
  them sets, and adds only fixes newer than that build: for 1 game (5 in 0.9.0).
- A fresh OptiScaler setup loads OptiPatcher (`LoadAsiPlugins=true`), which unlocks the upscaler inputs of about 200
  games on GPUs other than NVIDIA's; 0.9.0 placed it without loading it. Not yet checked in a game.
- On the OptiFG route, a game without a verified recipe whose only upscaler is DLSS, and which ships no
  `nvngx_dlss.dll`, gets NVIDIA's DLSS helper. Not yet checked in a game.
- Install reports "Launch option added" only when it added one.

### Known limitations

The full list is in [README.md](README.md#known-limitations). New or specific to 1.0.0:

- Setup writes 2× only; 3× and 4× are set in OptiScaler's menu and need MFG Unlocker.
- With MFG Unlocker loaded, a game's own XeSS frame generation runs MFG Unlocker's and Intel's shaders at every frame
  count; FreeFG accelerates only OptiScaler's frame generation there.
- Beside another module, only the checks of the network's make-up step aside; the other checks still end the game.
- With MFG Unlocker and `XeFGModel=default`, one of two 3× starts in Echo Point Nova ended during start-up with no error
  in any log; the next start worked. The cause is not known.
- No automatic setup outside the 19 verified recipes has been checked in play. Check and Install label those verdicts as
  automatic; the promoted wiki fixes await a maintainer's confirmation.
- BC-250 only (other GPUs untested), Linux and Proton only, no generated-frame scaling.

### Checked

A proof-of-life qualification. Its results, conditions and what it did not check are in
[MEASUREMENTS.md](MEASUREMENTS.md#checks-of-100).

- Without a GPU: reproducible build hashes, the installer tests, an offline install and Restore, the Wine loader check
  (callers kept beside a stand-in hooking module, only OptiScaler's contexts accelerated) and the static check.
- On one BC-250, one short start per question: synthetic scenes at 2× (bit-identical to 0.9.0); Echo Point Nova at 2×,
  at 3× and 4× with MFG Unlocker v1.6.0, and with HelixSR 2.0.0; one Cyberpunk 2077 benchmark run (102.08 FPS); Restore
  in both games; CONTROL Resonant with this OptiScaler build, 32 of 32 starts.

## 0.9.0 – 2026-10-19

The first release: a private pre-release for review. The figures in [MEASUREMENTS.md](MEASUREMENTS.md) were measured
with this build.

### Added

- XeSS frame generation at 2× accelerated on the AMD BC-250. A `libxess_fg.dll` proxy forwards to Intel's unmodified
  XeFG runtime 1.3.1.78 and runs part of its GPU work with this project's own shaders (13 pipeline replacements and 15
  Winograd-domain kernels), which read the network's coefficients at run time. Generated images were bit-identical
  wherever compared. Cyberpunk 2077, 1440p, FSR 4 Performance, headless: 103.3 FPS against 85.3 with Intel's shaders
  (+21%, measured on two days).
- Frame pacing for VRR under gamescope: a Vulkan layer holds each frame until its turn while XeFG generates. It presents
  from a compute queue where the driver has one, otherwise from the game's queue, and wakes stock gamescope so that it
  shows a held frame at once.
- FSR 4 upscaling through OptiScaler, with a BC-250 build of AMD's FSR 4 (RC11, INT8).
- An installer with a desktop front end (Setup): Add games, Install, Restore, Status and Check system. It writes Steam,
  Heroic and Lutris launch settings, applies per-game recipes for 19 games and lists OptiScaler wiki advice for about
  750 more. Restore puts everything back and keeps what the user or a game update changed.
- Pinned downloads, each checked by SHA-256 and downloaded once: Intel's runtime from Intel's repository, the FSR 4 DLL,
  OptiScaler's nightly support files and, only where a DLSS input needs it, NVIDIA's DLSS helper.
- Optional extras: realtime priority for gamescope; Steam's screensaver off while a game runs.
- A reproducible build of the proxy and the layer, byte for byte on the pinned toolchain, with CI and a static check
  that the package contains no Intel file and none of Intel's shaders or weight tables.

### Known limitations

- 2× only, no generated-frame scaling, BC-250 only (other GPUs untested), Linux and Proton only.
- With Intel's shaders (`BC250_XEFG_DISABLE=1` or another GPU), presents are not paced.

### Checked

Results and conditions: [MEASUREMENTS.md](MEASUREMENTS.md).

- Without a GPU: reproducible build hashes, the installer tests, an offline install and Restore, the Wine loader check.
- Synthetic scene on a BC-250: generated images identical in five 2× configurations. Six headless Cyberpunk 2077
  benchmark runs.
- Live install and Restore on a BC-250 in Echo Point Nova (Steam, OptiFG; started to the main menu) and Cyberpunk 2077
  (Heroic entry, native XeSS FG; benchmark at 2.001 presents per game frame). Restore returned both game folders and
  launcher entries as they were. These runs used the installer before its messages were reworded for 0.9.0; its install
  and Restore steps are the same.
- LG G5 TV at 1440p and 120 Hz with VRR, Cyberpunk 2077's benchmark: 2.000 presents per game frame and the same pacing
  as an earlier private build, at a 0.9% (SDR) and 1.3% (HDR10) lower frame rate.
- Not checked: gameplay (only benchmarks and menus were run).
