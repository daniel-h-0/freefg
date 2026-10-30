<!-- Copy of packaging/public/README.md for this folder of the repository, written by release/export_tree.py --public with its links adjusted; edit packaging/public/README.md instead. -->
# FreeFG

FreeFG accelerates Intel XeSS Frame Generation (XeFG) on the **AMD BC-250**, in DirectX 12 games under Proton.
It runs its own shaders alongside Intel's unmodified runtime and paces the output for gamescope/VRR displays.
OptiScaler provides upscaling through **AMD FSR 4 RC12**, **HLX DLSS** or **HLX FSR 4** (HelixSR 3.1.0).

The default is **2× output: one generated frame per game-rendered frame**. An optional, separate
[MFG Unlocker](#3-and-4-with-mfg-unlocker) enables 3×/4×. Generated frames improve motion smoothness; they do not
increase the game's simulation rate.

Generated frames match the output size by default. Optional [generated-frame scaling](#generated-frame-scaling)
reduces their generation cost, at the expense of generated-frame detail. Game-rendered frames keep their output size.

By default, seven shaders use faster FP16 arithmetic, so generated pixels can differ from Intel's.
`BC250_XEFG_EXACT=1` disables those forms. Exact mode matched Intel in the comparisons performed, but not every
kernel is proven equivalent for every input. [Output differences and switches](packaging/public/ARCHITECTURE.md#fp16-forms-approximate-output-by-default).

![Cyberpunk 2077 2.5, High graphics, HelixSR Quality at 1440p on AMD BC-250. No FG and Intel/FreeFG at 2×, 3× and 4× in SDR and HDR10. 3×/4× are marked unofficial. Separate output FPS, game FPS and derived milliseconds per generated frame. Four runs per condition, 95% confidence intervals, reactive mask off.](docs/assets/cyberpunk-helixsr-fps.svg)

**25.5% more output FPS in SDR and 25.4% in HDR10** than Intel's shaders on the same XeFG 2× route.
The chart also compares 3×/4×; their **(unofficial)** labels identify the separate MFG Unlocker 1.6.0 requirement.
Cost is added milliseconds per generated frame, derived from game FPS rather than GPU timestamps.
Cyberpunk 2.5, High graphics, HelixSR Quality (1706×960 → 2560×1440), reactive mask off in every condition.
Four uncapped headless runs per condition after a warm-up; whiskers show 95% confidence intervals across runs.
[Method, cost formula and data](packaging/public/MEASUREMENTS.md#cyberpunk-25-with-helixsr) · [Compact chart](docs/assets/cyberpunk-helixsr-fps-narrow.svg).

## Requirements

| Item | Requirement or tested configuration |
| --- | --- |
| Hardware | AMD BC-250 (PCI ID `1002:13fe`). [Other GPUs are experimental](packaging/public/TROUBLESHOOTING.md#other-gpus). |
| System | x86-64 Linux, Mesa RADV and Proton. Current checks use CachyOS and GE-Proton11-11; [test systems](packaging/public/MEASUREMENTS.md#test-system). |
| Compositor | gamescope for automatic frame pacing. Current TV checks use 3.16.30. |
| Setup | Python 3.11+, `bsdtar` (libarchive), and Zenity for the desktop interface. Internet access for uncached downloads. |
| Game | A 64-bit DirectX 12 game with a supported input, registered in Steam, Heroic or Lutris, in an ASCII-only path. |

Run **Check system** or `python3 install.py doctor` to inspect dependencies. A BC-250 driver with a compute queue
also needs the matching kernel fixes; the dedicated queue is optional. Games with detected anti-cheat are refused
unless you use the explicit [per-game risk override](packaging/public/COMPATIBILITY.md#anti-cheat).

## Install

### Setup

1. Extract the [release archive](https://github.com/daniel-h-0/freefg/releases/latest) and run `Start-freefg.sh`
   in Desktop Mode.
2. Choose **Add games** and select each rendering `.exe`. Unreal Engine games often use an executable under
   `Binaries/Win64`, rather than the launcher in the game root.
3. Choose **Install**, **Automatic per game**, and an upscaler. Read the verdict and any game-specific steps.
   Close the selected games and their launchers when prompted.
4. Reopen the launcher. In the game, select the upscaler input named by Setup and configure frame generation:

| Input | In-game setting |
| --- | --- |
| DLSS FG | DLSS frame generation on; requires Streamline 2 or newer. |
| FSR 3.1 FG / FSR 3.0 FG | The game's FSR frame generation on. HUD elements can be interpolated too. |
| OptiFG | The selected upscaler on, the game's own frame generation off. OptiFG derives FG inputs from upscaling. |
| Native XeSS FG | The game's XeSS frame generation on. |

An explicit input applies to every selected game; install games with different input requirements separately.
The first start after installation or an input change can take longer while shaders compile.

### Command line

Run these from the extracted release folder:

```sh
python3 install.py check GAME.exe       # offline verdict; no changes
python3 install.py preview GAME.exe     # downloads dependencies, previews changes
python3 install.py install GAME.exe     # automatic input, FSR 4
python3 install.py configure GAME.exe --upscaler helixsr   # or fsr4
python3 install.py status GAME.exe
python3 install.py plan --all           # what an update would change; no changes
python3 install.py update --all         # update every installed game in place
python3 install.py rollback GAME.exe    # back to the release before the last update
python3 install.py pin GAME.exe         # keep a game on its release (unpin to undo)
python3 install.py restore GAME.exe
python3 install.py helixsr              # find or download HelixSR
python3 install.py doctor
```

`install` accepts `--fg-input dlssg|upscaler|fsrfg|fsrfg30`, `--route native`, `--upscaler helixsr` and
`--dlss-helper auto|no|yes`. HelixSR must be built locally first, as described below.

An existing OptiScaler installation must match a supported pinned build. Unknown DLLs, custom library paths and
other proxy mods can require manual integration. Check explains each refusal before Install writes game files.

## Upscaler: FSR 4 or HelixSR

Choose **Upscaler** in Setup, then **FSR 4**, **HLX DLSS** or **HLX FSR 4**. AMD FSR 4 remains the default.
HLX is a separate project by [lonewolf0622](https://github.com/lonewolf0622/HelixSR), under its own licence.
FreeFG ships neither Helix's code nor its locally built model data. Frame generation remains FreeFG/XeFG;
Helix's DLSS frame-generation files are never installed.

For HLX, choose an already prepared official **HelixSR 3.1.0** folder, or **Prepare HLX**. Preparation downloads the
complete official archive and Microsoft shader compilers, verifies their hashes, and runs Helix's build-only Python
entry point with networking disabled. It requires Wine, bubblewrap, Python numpy, and the local NVIDIA/AMD model
inputs identified in `dependencies.json`: NVIDIA DLSS **310.7.0** and `amdxcffx64.dll` **2.4.0.4370** from
AMD Software **26.10.1**. An already prepared folder avoids selecting these again. It never runs Helix's game installer. Prepare once for all games:

```sh
python3 install.py hlx --dlss-input /path/to/nvngx_dlss.dll --amd-input /path/to/amdxcffx64.dll
python3 install.py configure GAME.exe --upscaler hlx-dlss
python3 install.py configure GAME.exe --upscaler hlx-fsr4
```

Use `--helixsr /path/to/HelixSR-3.1.0` to import a prepared release elsewhere. Its complete model-bearing files must
match the qualified build. Archive identity distinguishes upstream reissues with the same version number.
HLX providers occupy separate OptiScaler custom folders; AMD FSR 4 remains available. A compatible update advances
legacy HelixSR 2.0.0 to HLX DLSS when preparation is ready. `--upscaler helixsr` is an alias for HLX DLSS in this release.
Provider selection, integration files and their settings share one recovery transaction. **Rollback** undoes the latest
switch or update; **Restore** removes the installation and returns the original files. User-edited Helix settings are retained.


## Generated-frame scaling

Close the game, open **Settings**, and choose **Generated frames**:

| Choice | Result |
| --- | --- |
| Match output | Full output size; the default. |
| Scale | 50–100% of output width and height. At 75%, 2560×1440 generates at 1920×1080. |
| 720p / 1080p / 1440p / 2160p limit | Fit inside that height's 16:9 box, preserving aspect ratio and never enlarging. An ultrawide or portrait output is fitted to both bounds. |

Reduced dimensions round down to even pixels, with a minimum of one. Match output, 100%, and an output already
inside its selected limit preserve odd dimensions. The game's output resolution, real frames, depth and motion-vector
resources stay unchanged. The reduced result is enlarged only after generation.

**Downscale** selects Bilinear or Area colour reduction. **Upscale** selects Bilinear, Bicubic (Catmull–Rom),
Lanczos2 or FSR1 (EASU, without RCAS sharpening). Bilinear is the default in both directions. These filters affect
generated frames; they are separate from the game's FSR 4 or HelixSR upscaler. Scaling deliberately changes the image,
including in Exact mode.

```sh
python3 install.py configure GAME.exe --percent 75 --downscale area --upscale fsr1
python3 install.py configure GAME.exe --limit 1080
python3 install.py configure GAME.exe --resolution output
```

Restart the game after changes. OptiScaler also exposes these settings under **Frame Generation → XeFG scaling**.
**Status** reports the last recorded scaling decision and actual generated dimensions. With MFG Unlocker, use
`XeFGModel=default` for scaling at 3×/4×. Unsupported observed layouts retain full output.
[Mechanism and limits](packaging/public/ARCHITECTURE.md#generated-frame-scaling).

## 3× and 4× with MFG Unlocker

[MFG Unlocker](https://github.com/dashdogy/MFG-Unlocker), by dashdogy, lifts Intel's non-Intel frame-count limit.
FreeFG does not ship or install it. The tested version is **1.6.0**.

For FreeFG's full acceleration beside it, use **an OptiScaler FG input** and **`XeFGModel=default`**.
A game's native XeSS FG context is not accelerated while another mod hooks Intel's runtime.

1. Install FreeFG with an OptiScaler input, verify 2×, and close the game.
2. Download `MFGUnlocker-v1.6.0.zip` from its Releases page and verify `SHA256SUMS.txt`.
3. Rename `MFGUnlocker.dll` to `MFGUnlocker.asi` and place it in `OptiScaler/plugins/` beside the game's `.exe`.
4. In `OptiScaler.ini`, set `[Plugins] LoadAsiPlugins=true` and `[XeFG] XeFGModel=default`.
   Setup already writes these in a fresh setup and preserves explicit existing choices.
5. Select 3× or 4× in OptiScaler's **Insert → Frame Generation** menu. Its frame limit counts output frames:
   117 FPS at 4× is about 29 game-rendered FPS.

| `XeFGModel` | Effect beside MFG Unlocker |
| --- | --- |
| `default` | Reuses Intel's 2× model at higher factors. FreeFG can accelerate the full network. Image placement at higher factors is not comprehensively validated. |
| unset | MFG Unlocker's model. In the tested Cyberpunk route, FreeFG replaced 7 of 13 programs. |

[Compatibility and mechanism](packaging/public/ARCHITECTURE.md#another-mod-on-intels-runtime) ·
[Current 2×/3×/4× measurements](packaging/public/MEASUREMENTS.md#cyberpunk-25-with-helixsr).

To remove MFG Unlocker, delete its `.asi` and `RTXMFG-*` files; keep a copy of `RTXMFG-Universal.json` if you want its
settings. Set 2× in OptiScaler. Leave `LoadAsiPlugins` enabled for OptiPatcher. Restore leaves third-party files it did
not install. Every new FreeFG Install resets its OptiScaler route to 2×.

## Game compatibility

Setup combines **19 curated BC-250 recipes**, **758 OptiScaler wiki entries** and executable detection. A recipe can
record an installation, a partial check or a failure; it is not a blanket gameplay guarantee. Automatic setups are
labelled separately. [Game observations, verdicts and refusals](packaging/public/COMPATIBILITY.md).

## In the game

- Use borderless or windowed mode. XeFG does not interpolate in exclusive fullscreen.
- Keep output below the display's refresh ceiling for VRR. Extra generated frames above that ceiling cannot all be shown.
- FPS counters differ: some count game-rendered frames, others include generated frames. The Cyberpunk 2.5 benchmark
  summary includes generated frames on the tested DLSS FG route; its per-frame CSV counts game-rendered frames.
- Output pacing can add a few milliseconds of delay. End-to-end latency has not been measured.
- Steam's screensaver can consume GPU time behind a running game. Disable it or use the [extra](#extras).

## What Setup changes

Setup checks downloads by SHA-256, backs up replaced files, installs beside the rendering `.exe`, and updates the
selected game's launcher entry and recipe settings. Existing launch options and wrappers are retained.
An existing supported OptiScaler keeps its proxy filename. Fresh setups also receive OptiScaler support files and
OptiPatcher; the NVIDIA DLSS helper is added only when the selected input needs it and no game copy is found.

The installation record and backups are in `.bc250-xefg-experimental`. Setup normally creates a private vkd3d cache
there so wave-size settings apply consistently. [Implementation](packaging/public/ARCHITECTURE.md#the-installer) ·
[Files, downloads and privacy](packaging/public/PRIVACY.md).

## Restore and uninstall

**Update:** extract the new package and choose **Update all** in Setup. Setup shows a plan, then updates every
available, unpinned installation without a per-game Restore/Install cycle. The command-line equivalent is
`python3 install.py plan --all`, followed by `python3 install.py update --all` (the latter applies immediately).
Updates include FreeFG, Intel’s runtime, the selected upscaler and compatible OptiScaler integration files.
Launcher migrations change only owned fields and preserve user additions. Close the games first; if the plan changes
launcher entries, close the affected launcher too. User settings and original backups are retained. A running,
unavailable or blocked game is reported separately while other games continue. **Rollback** returns one game to the
state before its most recent update; **Restore** returns the original game files.

Installations register automatically for later updates. **Register** adds an existing installation, and **Library**
shows a selectable table with versions, providers, last-session logs and recovery status. Log evidence is separate
from file integrity and does not certify gameplay or settings persistence. **Update selected** acts on the chosen rows. The optional local index can be deleted and rebuilt from launcher discovery or
Register; each game retains its own runtime and recovery files. **Pin** holds a game and all its components at their
current versions; **Unpin** resumes updates. CLI equivalents are `register`, `library`, `pin` and `unpin`.

Setup’s **Update upscalers** updates each selected provider while keeping the FreeFG core. On the CLI,
`--component core` updates FreeFG/Intel and their integration; `--component upscaler` updates the provider and any
required integration. Incompatible or unprepared providers are deferred. Changed owned binaries block the coupled
operation for that game. A missing preparation cache does not prevent checking an already-current portable install.

Compatible installations from 1.1.3.1, 1.1.4 and 1.1.5 update directly. Format 2 also imports format 1 records and
migrates OptiScaler DLLs, additive INI defaults and Steam/Heroic/Lutris launcher fields in place. An explicit
`--loader winmm.dll` on `plan`/`update` changes the loader and its Wine override together; it refuses occupied mod
filenames. Choosing another loader is a compatibility trial, not a guarantee that a game's startup issue is fixed.
Unknown layouts and conflicting user edits need reconciliation. Updater changes do not silently reset game quality,
reassert settings a game keeps rejecting, or overwrite saves.
Automatic updates are optional: a deployment job you configure can invoke `install.py update --all` from the newly
extracted package. FreeFG installs no background updater and downloads no new FreeFG release by itself. A nonzero
exit status reports deferred or failed work; successful games remain updated, with their own Rollback available.

**Change FG input:** use **Refresh recipe** for this release’s tested integration and launcher settings. The CLI is
`plan GAME.exe --refresh-recipe`, then `update GAME.exe --refresh-recipe`. Only gameplay-qualified recipes are
offered; the plan lists manual game settings and does not change quality or saves. For custom inputs, use OptiScaler’s
menu, save and restart. Use **Upscaler** to switch providers without
changing the FG input.

Restore puts back replaced files and removes files and launcher settings it added. It reverts recipe settings key by
key while preserving later user edits. It reports changed game files that need attention rather than overwriting them.
Backups and logs remain in a `.bc250-xefg-experimental-restored-…` folder.

To uninstall completely, Restore every game, run each installed extra's `uninstall.sh`, then remove the extracted
package and unneeded backup/cache folders. The default download cache is `~/.cache/bc250-xefg-testers`; HelixSR's own
setup also uses `~/.local/share/HelixSR`.

## Extras

Optional helpers in the release's `extras/` folder each include installation and removal instructions:

- **gamescope-cap-sys-nice:** grants gamescope `CAP_SYS_NICE` for scheduling priority. It requires sudo and can affect
  environment variables in nested gamescope launches.
- **steam-screensaver-in-game:** disables Steam's screensaver while a game runs, then restores your timeout.
  It uses Steam's local DevTools endpoint.

[Privileges and local interfaces](packaging/public/SECURITY.md#what-runs-on-your-computer).

## Status

**1.1.6 candidate.** Adds in-place Update all, OptiScaler/launcher migrations, HLX providers, per-game rollback and optional pins, a library table, and
compatible selected-upscaler updates. The runtime and shader payload are unchanged from 1.1.5.

**1.1.5 (28 October 2026).** Reduces scaling overhead and fixes history invalidation and Restore
metadata. All 43 SDK starts and 13 Cyberpunk starts pass, as do installer/Restore, reproducible public builds and
pinned local CI. Echo's fresh checks were blocked before startup by Steam Cloud synchronization failure. The matched
Cyberpunk 4K/1440p-generation comparison improves output FPS by 1.52% over 1.1.4.
[Checks and limits](packaging/public/MEASUREMENTS.md#scaling-overhead-in-115).
The charts above describe the October 26 campaign with 1.1.3.1; scaling measurements are separate datasets.
[1.1.3.1 release checks](packaging/public/MEASUREMENTS.md#checks-of-1131) · [TV pacing checks](packaging/public/MEASUREMENTS.md#checks-of-113) ·
[Changelog](packaging/public/CHANGELOG.md).

## Known limitations

- Qualified on one BC-250 under Proton. Flatpak launchers and other GPUs are not qualified.
- Default FP16 output can differ numerically from Intel's; perceptual equivalence has not been established.
  Exact mode matched in the tested scenes; F4Q-family arithmetic is not proven equivalent for every input. [Details](packaging/public/ARCHITECTURE.md#f4q-rounding-and-tested-equivalence).
- Only the first eligible XeFG context is accelerated. Unsupported runtime layouts can trigger a fallback or close the
  game. [Fallback behavior](packaging/public/ARCHITECTURE.md#stepping-aside).
- Generated-frame scaling trades image detail for lower generation cost. Gains and visual quality vary by game,
  scale and filter; Exact mode does not make a scaled frame equal to a full-resolution frame.
- Frame pacing cannot remove every game/CPU stall. Higher-factor image quality and end-to-end latency remain incompletely
  measured; throughput gains alone do not establish either.

## Troubleshooting

Start with **Status**, **Check system** and [TROUBLESHOOTING.md](packaging/public/TROUBLESHOOTING.md).

## Credits and licences

FreeFG's code is MIT-licensed. Intel, OptiScaler, FSR 4, HelixSR and MFG Unlocker retain their own terms and credits;
this project is independent of their authors. Intel's runtime is downloaded unmodified, but FreeFG changes part of
its GPU work while it runs. [Licences, source offers and terms](NOTICE.md) · [Security and rights-holder contact](packaging/public/SECURITY.md).

## Documents

[Compatibility](packaging/public/COMPATIBILITY.md) · [Troubleshooting](packaging/public/TROUBLESHOOTING.md) · [Architecture](packaging/public/ARCHITECTURE.md) ·
[Measurements](packaging/public/MEASUREMENTS.md) · [Privacy](packaging/public/PRIVACY.md) · [Notices](NOTICE.md) · [Building](packaging/public/BUILDING.md) ·
[Changelog](packaging/public/CHANGELOG.md) · [Contributing](packaging/public/CONTRIBUTING.md) · [Security](packaging/public/SECURITY.md)
