# Changelog

Release changes since 0.9.0. Measurements describe the named release and test conditions, not every later build.

## 1.1.7 candidate

- Replace Setup's chain of Zenity dialogs with a window built on GTK 4 and libadwaita 1.5+: the game library grouped by
  what needs attention, a page per game with its state and only the actions that state allows, and every change run
  as an `install.py` command with its progress, outcome and next steps in view. Zenity remains the fallback.
- Add games from the installed Steam and Heroic games with their rendering executable proposed; each is checked as
  soon as it is listed. Install shows the verdict for the chosen input, and soft refusals are accepted per game.
- Review every game's update plan, grouped by outcome, before one confirmation. A game's page checks its program files
  and launch settings against the installation record and edits generated-frame settings in place.

- Cancel pending Install checks without starting a command; re-check input choices changed while a check is running.
- Keep newer installations read-only in this Setup and isolate malformed records in the library.
- Reuse checked, installer-owned HLX files after the shared preparation cache is removed; distinguish legacy HelixSR
  from its HLX successor when switching providers.
- Keep 1.1.6's FreeFG runtime, shaders, OptiScaler and dependency pins. This candidate changes Setup and record handling.

## 1.1.6 – 2026-10-30

- Update compatible installed games in place with Setup's **Update all** or `install.py update --all`; import
  1.1.3.1, 1.1.4 and 1.1.5 records and store an explicit contract for future compatible releases.
- Add distinct HLX DLSS and HLX FSR 4 providers from HelixSR 3.1.0, prepared once locally through its build-only
  entry point. Legacy HelixSR advances to HLX DLSS; AMD FSR 4 remains a separate choice. Complete prepared hashes
  identify the upstream archive revision. Provider switches use the shared rollback engine.
- Migrate OptiScaler, additive defaults, loader names and owned launcher fields in place, preserving unrelated
  settings. Import format 1 records into format 2. Keep update/rollback recovery consistent across files and launchers.
- Add explicit recipe refresh for tested input/launcher changes; retire obsolete pending game-setting writes.
- Add a native selectable library table and Update selected. Keep last-session logs distinct from installation state.
  Incorporate Deep Rock and Deadzone input findings and document the unresolved Hogwarts/Black Flag/Tainted Grail/RDR2 cases.
- Add a rebuildable library index, Register/Library and Pin/Unpin actions. Batch operations report running,
  unavailable, deferred and failed games separately and continue with other games.
- Harden generation recovery, original-backup validation, drift checks and settings merges. Rollback preserves
  saved timestamps/permissions and later user settings; interrupted rollback finishes before a new update starts.
- Keep the 1.1.5 runtime and shader payload. No background updater or automatic library rollout is installed.

[Qualification and limits](MEASUREMENTS.md#checks-of-116).

## 1.1.5 – 2026-10-28

- Reduce scaling overhead: synthesis writes directly into the enlargement input, and unchanged SDK colour histories
  keep their cached reductions across frames. Eligible colour intermediates allow lossless render-target compression.
- Simplify zero-padded boundary reads in the 25 bounded convolution forms. Scaling filters, storage precision,
  full-output shader forms and wave sizes retain their previous behavior.
- Invalidate cached histories on later writes, abandoned command-list recordings and aliasing barriers, including
  barriers with wildcard resource identities. Add CPU tests for those cache lifetimes.
- Restore original modification times when an upscaler switch or interrupted Restore has already returned a file's
  original bytes. Files changed by the game or user keep their current contents and timestamps.

[Qualification and measurements](MEASUREMENTS.md#scaling-overhead-in-115). Update through Restore in the old release,
then Install from this one so the proxy and its shader profile stay together. Match output remains the default.

## 1.1.4 – 2026-10-27

- Restore optional generated-frame scaling: 50–100%, or aspect-preserving 720p/1080p/1440p/2160p limits. Match output
  remains the default. Real frames, depth and motion-vector inputs retain their original sizes.
- Add owned colour resampling, bounded convolution variants and Bilinear/Area reduction with Bilinear, Bicubic,
  Lanczos2 or AMD FSR 1 EASU enlargement. Intel's original preprocessing, warp and final pipelines remain unchanged.
- Expose scaling in Setup and retain OptiScaler's settings interface. Saved choices apply after restart; Status shows
  the last actual decision. Support default-model MFG phases and re-observation after size/format changes.
- Preserve odd output dimensions and bound every reduced pyramid/network level, including tiny, portrait and
  ultrawide inputs. Share read-only colour reductions within one frame and command list; source copies and list resets
  invalidate reuse. [Scaling checks and measurements](MEASUREMENTS.md#generated-frame-scaling-in-114).

- Clarify the measurement campaigns, cache exceptions, troubleshooting, download checks and community recipe selection.
- Extend the HelixSR charts to matched 2×/3×/4× SDR and HDR10 measurements, mark the MFG Unlocker
  categories `(unofficial)`, and show derived milliseconds per generated frame. Preserve the prior 2× dataset.
- Review all public documentation against 1.1.3.1: shorten explanations, correct shader counts and dependency
  provenance, distinguish curated recipes from gameplay validation, and date historical measurements.
- Correct Check system's description of the multi-frame build, fallback pacing and current test environment.
- Make the game-report form distinguish initialization from observed frame generation.

## 1.1.3.1 – 2026-10-25

- Use wave64 for the 224-channel Winograd input-transform shader in every game. A Cyberpunk 2.5 bisection associated
  its wave32 selection with early GPU faults. The shader's arithmetic is unchanged; the rebuilt proxy accepts the new
  profile. The underlying cause remains unresolved. [Checks](MEASUREMENTS.md#checks-of-1131).
- Update OptiScaler and its support files to the 25 October nightly (`08e13adf`), retaining independent library paths,
  automatic settings saving and adaptive frame starts. Source tag: `bc250-03db4f8`.
- Change Cyberpunk 2.5 to DLSS upscaling input and DLSS FG input → XeFG. Keep its XeSS DLL, disable XeSS upscaler
  input and native Anti-Lag 2, enable Reflex, and enable compute/graphics state restoration for this route.
- Disable the reactive/bias mask for Cyberpunk with HelixSR. Configure restores a recipe-owned value when switching to
  FSR 4 and preserves explicit user choices. Removing this upscaler input may affect image quality.
- Replace the primary chart with Cyberpunk 2.5, High graphics and HelixSR Quality at 1440p: no FG, Intel XeFG 2× and
  FreeFG 2×, in SDR/HDR10, with separate game/output FPS and confidence intervals.
  [Method and data](MEASUREMENTS.md#cyberpunk-25-with-helixsr).

Update with Restore in the old release, then Install from this one. Copying only `waves.txt` fails the proxy's profile
checks. The presentation layer and upscalers retain 1.1.3's bytes.

## 1.1.3 – 2026-10-25

- Add adaptive 3×/4× game-frame starts through OptiScaler's XeLL output, correcting sustained short/long intervals
  and resetting after large stalls. `BC250_XELL_PACE=0` disables this correction.
- Adapt the presentation layer's jitter allowance to the SDK factor (5/10/15 ms ceilings at 2×/3×/4×). Allow longer
  holds at 4× and reserve extra swapchain images within the surface limit to improve recovery after hitches.
  The 2× timing policy retains its previous values.
- Fix OptiScaler's `XeSSPath`, `XeFGPath` and `XeLLPath` reader so each key configures its own library. Install and
  Settings repair known saved XeSS paths pointing to `libxess_fg.dll` or `libxell.dll`; other custom paths are kept.
- Keep 1.1.2's shaders, Intel runtime and upscalers.

[TV checks](MEASUREMENTS.md#checks-of-113): CONTROL Resonant, HelixSR, 1440p120 HDR/VRR, 2×/3×/4×, camera motion and
stalls. These checks do not establish library-wide pacing or end-to-end latency.

## 1.1.2 – 2026-10-24

- Enable seven faster FP16 U-Net forms by default. Generated images differ numerically from Intel's. In 19 synthetic
  configurations, 0.12–16.2% of pixels differ; error against analytic truth is 0.985–1.007× Intel's. The image-quality
  gate did not pass overall. `BC250_XEFG_EXACT=1` or `Exact=1` in `settings.ini` disables these forms.
- Extend Winograd F(4×4) to three encoders (F4Q2) and two row layers (F4Q3). These non-FP16 forms matched Intel's in
  all comparisons, but equivalence is not proven for every input. `F4Q2=0` disables the three encoders; `F4Q=0`
  disables all F(4×4) and approximate FP16 forms. Environment variables override the file.
- Speed up the decoder's exact transforms, skip wholly out-of-bounds thread groups, and change flow refinement's
  group shape and division. The profile now contains 52 shaders and 9 control files, with 142 wave-table entries.
- Install FSR 4 RC12 instead of RC11. Status names the installed FSR build; Status and Check report the last
  session's output form. Add FP16/F4Q2/F4Q3 log lines and extend the shadow diagnostic.
- Use the pinned toolchain for release builds, independent of host compiler updates.

[Checks](MEASUREMENTS.md#checks-of-112): the release's default matches the tested candidate in 640 SDK images;
Exact mode matches Intel's in 704. Cyberpunk 2.31 native 2× gains 1.64% in SDR and 1.50% in HDR10 over 1.1.1, both
using RC12 (six runs per arm). The pacing layer, OptiScaler and Intel runtime retain 1.1.1's bytes.

## 1.1.1 – 2026-10-21

- Give each installation a vkd3d-proton shader cache and disable shader-module identifiers. This makes wave overrides
  apply even when Mesa has a pipeline compiled before the override existed. Preserve user cache settings; omit both
  changes with an explanation if the cache filename would be too long. Restore removes the new cache and restores
  launch settings; Status reports its size.
- Set `XeFGModel=default` where unset, preserving user choices. This lets FreeFG accelerate the whole network
  beside MFG Unlocker on an OptiScaler route.
- Report full, partial, skipped and abandoned acceleration, with suggested fixes. Ignore old logs outside the
  executable folder or from before installation, and identify a fast log left by an earlier session.

Runtime binaries are 1.1.0's. [Cache checks](MEASUREMENTS.md#shader-caches) measured +0.36%/+0.64% at 2× SDR/HDR10
and +0.58% at 3× SDR from the launch settings. [Install/Restore checks](MEASUREMENTS.md#live-install-and-restore)
covered Echo Point Nova and Cyberpunk. Unexplained 3× startup exits are recorded in
[Measurements](MEASUREMENTS.md#start-up-exits-at-3).

## 1.1.0 – 2026-10-21

- Use exact packed FP16 input transforms in nine U-Net shaders.
- Enable F4Q: two U-Net layers use Winograd F(4×4), reducing multiplications. Outputs matched in every test;
  equivalence is not proven for every input. Add `F4Q=0`/`BC250_XEFG_F4Q=0` and a shadow diagnostic.
- Add five wave32 choices for Intel shaders. Warm caches prevented these from applying in this release's benchmark
  block; 1.1.1 addresses that. The profile contains 40 shaders, 9 control files and 130 wave entries.

[Checks](MEASUREMENTS.md#checks-of-110): 704 SDK images match Intel's with F4Q on and off; 96,480 diagnostic
comparisons differ nowhere. Cyberpunk gains over 1.0.x were 1.37%/1.20% at 2× SDR/HDR10, 2.08% at 3× and 2.61% at
4× (two runs per arm at 4×). The installer, pacing layer, OptiScaler and Intel runtime remain 1.0.1's.

## 1.0.1 – 2026-10-20

- Add a per-game anti-cheat override, requiring explicit risk acceptance. Ordinary **Install anyway** and `--accept`
  do not override anti-cheat refusals. Status and Check show the exception until Restore.
- Classify anti-cheat as its own refusal type and document the 19 curated recipes and 758 bundled wiki entries.
- Add same-day 2× comparisons and MFG Unlocker measurements to the docs.

Runtime payloads are byte-identical to 1.0.0. Installer tests, offline Install/Restore and CI passed.

## 1.0.0 – 2026-10-20

First public release.

- Add 3×/4× acceleration beside separately installed MFG Unlocker 1.6.0. FreeFG does not lift Intel's factor cap or
  distribute the unlocker. Five multi-frame kernels bring the shader count to 33.
- Preserve caller identity when forwarding beside a module that hooks Intel's runtime. Accelerate only OptiScaler's
  contexts in that case; unfamiliar network layouts step aside, while other safety checks can still stop the game.
- Add FSR 4/HelixSR selection. HelixSR is lonewolf0622's separate project, downloaded from its pinned official release.
- Add offline compatibility checks, per-game refusals, automatic selection for games without recipes, reviewed wiki
  advice and community recipes. Bundle the 17 October OptiScaler wiki snapshot (`9812e2d`).
- Rebase OptiScaler on 19 October master (`c2e44a8b`), source tag `bc250-f971ed1`, and retain the startup deadlock fix.
  Respect its built-in game fixes. Enable OptiPatcher in fresh setups and fetch a DLSS helper only when needed.
- Pace output using SDK status at every frame count, including Intel-shader fallback. Add `BC250_XEFG_STATUS_POLL=0`.

[Initial checks](MEASUREMENTS.md#checks-of-100) covered SDK output at 2×, Echo Point Nova at 2×/3×/4× and with HelixSR,
one native Cyberpunk benchmark, Restore, and 32 CONTROL starts. One Echo 3× startup exit was unexplained. Automatic
recipes, gameplay and longer sessions were not qualified by this initial check.

## 0.9.0 – 2026-10-19

Private prerelease for review.

- Accelerate XeSS FG at 2× on AMD BC-250 through a proxy to Intel's unmodified runtime: 13 replacements and 15 helper
  kernels, with coefficients read at runtime. Images matched wherever compared.
- Add gamescope/VRR presentation pacing, FSR 4 RC11 through OptiScaler, Setup and CLI installation, 19 game recipes,
  Steam/Heroic/Lutris launch settings, pinned downloads and Restore.
- Add optional gamescope priority and Steam screensaver helpers, reproducible builds, CI and a package-content check.

[Measurements](MEASUREMENTS.md) include synthetic images, headless Cyberpunk benchmarks, live Install/Restore in
Echo and Cyberpunk, and Cyberpunk on a VRR TV. No gameplay qualification. This build supported 2× only and did not
pace Intel-shader fallback; Linux/Proton and BC-250 were the tested platform.
