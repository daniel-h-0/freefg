<!-- Copy of packaging/public/README.md for this folder of the repository, written by release/export_tree.py --public with its links adjusted; edit packaging/public/README.md instead. -->
# FreeFG

FreeFG accelerates Intel XeSS Frame Generation (XeFG) on the **AMD BC-250** in DirectX 12 games under Proton. It
uses its own shaders with Intel's unmodified runtime and paces output for gamescope and VRR. OptiScaler supplies
AMD FSR 4, HLX DLSS or HLX FSR 4 upscaling.

The default is **2×**: one generated frame for each game-rendered frame. Generated frames improve smoothness, not
the game's simulation rate. Optional generated-frame scaling can reduce cost, and a separate MFG Unlocker can enable
3× or 4×.

![Cyberpunk 2.5 game and output FPS and added frame cost for Intel and FreeFG at 2×, 3× and 4×, in SDR and HDR10.](https://raw.githubusercontent.com/daniel-h-0/freefg/5de9a40317ff07511c69c006bad22b36d3250f03/docs/assets/cyberpunk-helixsr-fps.svg)

Cyberpunk 2.5 on one BC-250, FreeFG 1.1.3.1, HelixSR Quality at 1440p; four headless runs per condition. Higher
factors require MFG Unlocker. [Methods, data and limitations](packaging/public/MEASUREMENTS.md#cyberpunk-25-with-helixsr).

## Requirements

- AMD BC-250, x86-64 Linux, Mesa RADV and Proton. [Other GPUs are experimental](packaging/public/TROUBLESHOOTING.md#other-gpus).
- A 64-bit DirectX 12 game with a supported input, registered in Steam, Heroic or Lutris
  ([or another launcher](packaging/public/INSTALLATION.md#other-launchers)), in an ASCII-only path.
- Python 3.11+, `bsdtar` and Zenity for Setup; internet access for uncached dependencies.
- gamescope for automatic pacing. A BC-250 driver with a compute queue also needs the matching kernel fixes.

Run **Check system** or `python3 install.py doctor` to inspect the host. Detected anti-cheat blocks installation
unless you explicitly accept the [per-game risk](packaging/public/COMPATIBILITY.md#anti-cheat).

## Install

<a id="setup"></a>

1. Extract the [latest release](https://github.com/daniel-h-0/freefg/releases/latest) and run `Start-freefg.sh` in
   Desktop Mode.
2. Choose **Add games**, then select each rendering `.exe`—often under `Binaries/Win64` for Unreal Engine games.
3. Choose **Install**, **Automatic per game** and an upscaler. Read the verdict and close games and launchers when
   prompted. Enable the requested input in the game after installation.

[Installation and updates](packaging/public/INSTALLATION.md) covers input choices, the command line, Library, pins and recovery.
<a id="in-the-game"></a>
<a id="what-setup-changes"></a>
<a id="game-compatibility"></a>
[Compatibility](packaging/public/COMPATIBILITY.md) explains the verdicts; detection alone does not establish working generation.

<a id="command-line"></a>

## Updates and recovery

<a id="restore-and-uninstall"></a>

Extract a new release, choose games in **Library**, then use **Update selected**; or choose **Update all**. Update all
discovers installations through launchers as well as the local index; choose specific games for a narrower scope.
**Rollback** undoes the most recent update or provider switch. **Restore** returns the original installation files.

Close the affected games first and close their launchers when the plan changes launcher entries. Updates are
per-game, so a blocked game does not prevent other selected games from updating.
[Update, rollback and uninstall instructions](packaging/public/INSTALLATION.md#updates-and-recovery).

<a id="upscaler-fsr-4-or-helixsr"></a>
<a id="generated-frame-scaling"></a>
<a id="3-and-4-with-mfg-unlocker"></a>

## Configuration

**Settings** controls generated-frame size and filters. **Upscaler** selects AMD FSR 4, HLX DLSS or HLX FSR 4;
HLX needs a one-time local preparation. MFG Unlocker is separate and is not shipped with FreeFG.
[Configuration guide](packaging/public/CONFIGURATION.md) · [Troubleshooting](packaging/public/TROUBLESHOOTING.md).

<a id="status"></a>
**Status** reports the installation and last recorded session. [Logs and diagnostics](packaging/public/TROUBLESHOOTING.md#logs).

Default FP16 shaders can change generated pixels. `BC250_XEFG_EXACT=1` disables those forms; the remaining F4Q
paths matched the reported tests but are not proven equivalent for every input. Scaling also changes the generated
image. See [output differences](packaging/public/ARCHITECTURE.md#fp16-forms-approximate-output-by-default).

## Known limitations

- Validation is limited to one BC-250 under Proton. Flatpak launcher operation and other GPUs are unqualified.
- Only the first eligible XeFG context is accelerated. Runtime mismatches can fall back or end the game.
- Perceptual equivalence, higher-factor image quality and end-to-end latency are not established. Pacing cannot
  remove every game or CPU stall.

<a id="extras"></a>
<a id="troubleshooting"></a>
<a id="credits-and-licences"></a>

## Documents

- [Installation and recovery](packaging/public/INSTALLATION.md) · [Configuration](packaging/public/CONFIGURATION.md) · [Compatibility](packaging/public/COMPATIBILITY.md) · [Troubleshooting](packaging/public/TROUBLESHOOTING.md)
- [Measurements](packaging/public/MEASUREMENTS.md) · [Architecture](packaging/public/ARCHITECTURE.md) · [Building](packaging/public/BUILDING.md) · [Changelog](packaging/public/CHANGELOG.md)
- [Optional extras](packaging/public/INSTALLATION.md#uninstall-and-extras) · [Privacy](packaging/public/PRIVACY.md) · [Notices and licences](NOTICE.md) · [Security](packaging/public/SECURITY.md) · [Contributing](packaging/public/CONTRIBUTING.md)

FreeFG is independent of Intel, AMD, NVIDIA, OptiScaler and HelixSR. Intel's runtime is downloaded unmodified, but
FreeFG changes part of its GPU work; see [notices and terms](NOTICE.md).
