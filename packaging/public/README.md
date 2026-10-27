# FreeFG

FreeFG accelerates Intel XeSS Frame Generation (XeFG) on the **AMD BC-250**, in DirectX 12 games under Proton.
It runs its own shaders alongside Intel's unmodified runtime and paces the output for gamescope/VRR displays.
OptiScaler provides upscaling through **FSR 4 RC12** or **HelixSR 2.0.0**.

The default is **2× output: one generated frame per game-rendered frame**. An optional, separate
[MFG Unlocker](#3-and-4-with-mfg-unlocker) enables 3×/4×. Generated frames improve motion smoothness; they do not
increase the game's simulation rate.

By default, seven shaders use faster FP16 arithmetic, so generated pixels can differ from Intel's.
`BC250_XEFG_EXACT=1` disables those forms. Exact mode matched Intel in the comparisons performed, but not every
kernel is proven equivalent for every input. [Output differences and switches](ARCHITECTURE.md#fp16-forms-approximate-output-by-default).

![Cyberpunk 2077 2.5, High graphics, HelixSR Quality at 1440p on AMD BC-250. No FG and Intel/FreeFG at 2×, 3× and 4× in SDR and HDR10. 3×/4× are marked unofficial. Separate output FPS, game FPS and derived milliseconds per generated frame. Four runs per condition, 95% confidence intervals, reactive mask off.](../../docs/assets/cyberpunk-helixsr-fps.svg)

**25.5% more output FPS in SDR and 25.4% in HDR10** than Intel's shaders on the same XeFG 2× route.
The chart also compares 3×/4×; their **(unofficial)** labels identify the separate MFG Unlocker 1.6.0 requirement.
Cost is added milliseconds per generated frame, derived from game FPS rather than GPU timestamps.
Cyberpunk 2.5, High graphics, HelixSR Quality (1706×960 → 2560×1440), reactive mask off in every condition.
Four uncapped headless runs per condition after a warm-up; whiskers show 95% confidence intervals across runs.
[Method, cost formula and data](MEASUREMENTS.md#cyberpunk-25-with-helixsr) · [Compact chart](../../docs/assets/cyberpunk-helixsr-fps-narrow.svg).

## Requirements

| Item | Requirement or tested configuration |
| --- | --- |
| Hardware | AMD BC-250 (PCI ID `1002:13fe`). [Other GPUs are experimental](TROUBLESHOOTING.md#other-gpus). |
| System | x86-64 Linux, Mesa RADV and Proton. Current checks use CachyOS and GE-Proton11-11; [test systems](MEASUREMENTS.md#test-system). |
| Compositor | gamescope for automatic frame pacing. Current TV checks use 3.16.30. |
| Setup | Python 3.11+, `bsdtar` (libarchive), and Zenity for the desktop interface. Internet access for uncached downloads. |
| Game | A 64-bit DirectX 12 game with a supported input, registered in Steam, Heroic or Lutris, in an ASCII-only path. |

Run **Check system** or `python3 install.py doctor` to inspect dependencies. A BC-250 driver with a compute queue
also needs the matching kernel fixes; the dedicated queue is optional. Games with detected anti-cheat are refused
unless you use the explicit [per-game risk override](COMPATIBILITY.md#anti-cheat).

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
python3 install.py restore GAME.exe
python3 install.py helixsr              # find or download HelixSR
python3 install.py doctor
```

`install` accepts `--fg-input dlssg|upscaler|fsrfg|fsrfg30`, `--route native`, `--upscaler helixsr` and
`--dlss-helper auto|no|yes`. HelixSR must be built locally first, as described below.

An existing OptiScaler installation must match a supported pinned build. Unknown DLLs, custom library paths and
other proxy mods can require manual integration. Check explains each refusal before Install writes game files.

## Upscaler: FSR 4 or HelixSR

FSR 4 RC12 is the default. [HelixSR](https://github.com/lonewolf0622/HelixSR), by lonewolf0622, is a separate upscaler
that runs NVIDIA's DLSS network on other GPUs. Frame generation remains XeFG with either choice.

To use HelixSR:

1. Choose **HelixSR** in Setup. It offers the pinned official 2.0.0 download if no supported copy is available.
2. Run its own setup once in the downloaded folder:
   `./helixsr-setup.sh --no-fg`. It asks before downloading NVIDIA's DLL and builds the network locally.
   At the first game-install question, press **Ctrl+C**, or answer **n** for each game. Let FreeFG install it.
3. Select HelixSR again in Setup. For an existing FreeFG installation, use **Upscaler** or the `configure` command.

For a copy elsewhere, pass `--helixsr /path/to/HelixSR-2.0.0`; Setup remembers that folder.
Use FreeFG's Restore for games it installed. [Downloads and privacy](PRIVACY.md#helixsr-optional) ·
[HelixSR and NVIDIA terms](NOTICE.md#helixsr).

Cyberpunk 2.5's HelixSR recipe disables the reactive/bias mask input to avoid observed startup faults. This changes
a temporal-reconstruction input; equivalent image quality with the mask enabled has not been established.
[Details](TROUBLESHOOTING.md#cyberpunk-25-with-helixsr-stops-at-the-first-rendered-frames).

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

[Compatibility and mechanism](ARCHITECTURE.md#another-mod-on-intels-runtime) ·
[Current 2×/3×/4× measurements](MEASUREMENTS.md#cyberpunk-25-with-helixsr).

To remove MFG Unlocker, delete its `.asi` and `RTXMFG-*` files; keep a copy of `RTXMFG-Universal.json` if you want its
settings. Set 2× in OptiScaler. Leave `LoadAsiPlugins` enabled for OptiPatcher. Restore leaves third-party files it did
not install. Every new FreeFG Install resets its OptiScaler route to 2×.

## Game compatibility

Setup combines **19 curated BC-250 recipes**, **758 OptiScaler wiki entries** and executable detection. A recipe can
record an installation, a partial check or a failure; it is not a blanket gameplay guarantee. Automatic setups are
labelled separately. [Game observations, verdicts and refusals](COMPATIBILITY.md).

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
there so wave-size settings apply consistently. [Implementation](ARCHITECTURE.md#the-installer) ·
[Files, downloads and privacy](PRIVACY.md).

## Restore and uninstall

**Update or change FG input:** Restore with the existing package, then Install from the new package.
Use **Upscaler** to switch FSR 4/HelixSR without changing the FG input.

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

[Privileges and local interfaces](SECURITY.md#what-runs-on-your-computer).

## Status

**1.1.3.1, 25 October 2026.** Includes the October 25 OptiScaler fork, Cyberpunk 2.5 recipe, one global wave64
workaround, and 1.1.3's 3×/4× pacing changes. The October 25 HelixSR 2× comparison passed six warm-ups and
24 measurements. The expanded October 26 chart above covers 2×/3×/4×: all 14 warm-ups and 56 measurements passed.
Echo Point Nova passed 2×/3×/4× starts. Installer/Restore and pinned builds passed.
[Release checks](MEASUREMENTS.md#checks-of-1131) · [TV pacing checks](MEASUREMENTS.md#checks-of-113) ·
[Changelog](CHANGELOG.md).

## Known limitations

- Qualified on one BC-250 under Proton. Flatpak launchers and other GPUs are not qualified.
- Default FP16 output can differ numerically from Intel's; perceptual equivalence has not been established.
  Exact mode matched in the tested scenes; F4Q-family arithmetic is not proven equivalent for every input. [Details](ARCHITECTURE.md#f4q-rounding-and-tested-equivalence).
- Only the first eligible XeFG context is accelerated. Unsupported runtime layouts can trigger a fallback or close the
  game. [Fallback behavior](ARCHITECTURE.md#stepping-aside).
- Generated frames use full output resolution; a subnative generated-frame option is a future goal.
- Frame pacing cannot remove every game/CPU stall. Higher-factor image quality and end-to-end latency remain incompletely
  measured; throughput gains alone do not establish either.

## Troubleshooting

Start with **Status**, **Check system** and [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Credits and licences

FreeFG's code is MIT-licensed. Intel, OptiScaler, FSR 4, HelixSR and MFG Unlocker retain their own terms and credits;
this project is independent of their authors. Intel's runtime is downloaded unmodified, but FreeFG changes part of
its GPU work while it runs. [Licences, source offers and terms](NOTICE.md) · [Security and rights-holder contact](SECURITY.md).

## Documents

[Compatibility](COMPATIBILITY.md) · [Troubleshooting](TROUBLESHOOTING.md) · [Architecture](ARCHITECTURE.md) ·
[Measurements](MEASUREMENTS.md) · [Privacy](PRIVACY.md) · [Notices](NOTICE.md) · [Building](BUILDING.md) ·
[Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)
