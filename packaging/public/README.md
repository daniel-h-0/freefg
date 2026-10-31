# FreeFG

FreeFG accelerates Intel XeSS Frame Generation (XeFG) on the **AMD BC-250** in DirectX 12 games under Proton. It
uses its own shaders with Intel's unmodified runtime and paces output for gamescope and VRR. OptiScaler supplies
AMD FSR 4, HLX DLSS or HLX FSR 4 upscaling.

The default is **2×**: one generated frame for each game-rendered frame. Generated frames improve smoothness, not
the game's simulation rate. Optional generated-frame scaling can reduce cost, and a separate MFG Unlocker can enable
3× or 4×.

![Cyberpunk 2.5 game and output FPS and added frame cost for Intel and FreeFG at 2×, 3× and 4×, in SDR and HDR10.](https://raw.githubusercontent.com/daniel-h-0/freefg/5de9a40317ff07511c69c006bad22b36d3250f03/docs/assets/cyberpunk-helixsr-fps.svg)

Cyberpunk 2.5 on one BC-250, FreeFG 1.1.3.1, HelixSR Quality at 1440p; four headless runs per condition. Higher
factors require MFG Unlocker. [Methods, data and limitations](MEASUREMENTS.md#cyberpunk-25-with-helixsr).

**1.2.0 candidate.** The redesigned library window and expanded compatibility planning are being qualified together.
This branch is not a published release; the FreeFG runtime and dependency pins remain at 1.1.6.

## Requirements

- AMD BC-250, x86-64 Linux, Mesa RADV and Proton. [Other GPUs are experimental](TROUBLESHOOTING.md#other-gpus).
- A 64-bit DirectX 12 game with a supported input, registered in Steam, Heroic or Lutris, in an ASCII-only path.
- Python 3.11+ and `bsdtar`; PyGObject, GTK 4 and libadwaita 1.5+ for Setup’s window (Zenity fallback).
  Internet access for uncached dependencies.
- gamescope for automatic pacing. A BC-250 driver with a compute queue also needs the matching kernel fixes.

Run **System Check** or `python3 install.py doctor` to inspect the host. Detected anti-cheat blocks installation
unless you explicitly accept the [per-game risk](COMPATIBILITY.md#anti-cheat).

## Install

<a id="setup"></a>

1. Extract the [latest release](https://github.com/daniel-h-0/freefg/releases/latest) and run `Start-freefg.sh` in
   Desktop Mode.
2. Choose **Add a Game**, pick an installed game or choose its rendering `.exe`, then open its page.
3. Choose **Install…**, keep **Automatic** or select an input, and choose an upscaler. Read the verdict and close
   games and launchers when prompted. Enable the requested input in the game after installation.

[Installation and updates](INSTALLATION.md) covers input choices, the command line, Library, pins and recovery.
<a id="in-the-game"></a>
<a id="what-setup-changes"></a>
<a id="game-compatibility"></a>
[Compatibility](COMPATIBILITY.md) explains the verdicts; detection alone does not establish working generation.

<a id="command-line"></a>

## Updates and recovery

<a id="restore-and-uninstall"></a>

Extract a new release and use **Update…** on a game’s page, or **Update All Games…** in the menu. Update All Games
discovers installations through launchers as well as the local index; choose specific games for a narrower scope.
**Rollback** undoes the most recent update or provider switch. **Restore** returns the original installation files.

Close the affected games first and close their launchers when the plan changes launcher entries. Updates are
per-game, so a blocked game does not prevent other selected games from updating.
[Update, rollback and uninstall instructions](INSTALLATION.md#updates-and-recovery).

<a id="upscaler-fsr-4-or-helixsr"></a>
<a id="generated-frame-scaling"></a>
<a id="3-and-4-with-mfg-unlocker"></a>

## Configuration

Each game’s page controls generated-frame size and filters. **Change…** beside **Upscaler** selects AMD FSR 4, HLX DLSS or HLX FSR 4;
HLX needs a one-time local preparation. MFG Unlocker is separate and is not shipped with FreeFG.
**Wiki settings** reviews additional INI suggestions, their sources and conditions before applying selected values.
[Configuration guide](CONFIGURATION.md) · [Troubleshooting](TROUBLESHOOTING.md).

<a id="status"></a>
The game page shows the last recorded session; **Installation details** reports the owned files. [Logs and diagnostics](TROUBLESHOOTING.md#logs).

Default FP16 shaders can change generated pixels. `BC250_XEFG_EXACT=1` disables those forms; the remaining F4Q
paths matched the reported tests but are not proven equivalent for every input. Scaling also changes the generated
image. See [output differences](ARCHITECTURE.md#fp16-forms-approximate-output-by-default).

## Known limitations

- Validation is limited to one BC-250 under Proton. Flatpak launcher operation and other GPUs are unqualified.
- Only the first eligible XeFG context is accelerated. Runtime mismatches can fall back or end the game.
- Perceptual equivalence, higher-factor image quality and end-to-end latency are not established. Pacing cannot
  remove every game or CPU stall.

<a id="extras"></a>
<a id="troubleshooting"></a>
<a id="credits-and-licences"></a>

## Documents

- [Installation and recovery](INSTALLATION.md) · [Configuration](CONFIGURATION.md) · [Compatibility](COMPATIBILITY.md) · [Troubleshooting](TROUBLESHOOTING.md)
- [Measurements](MEASUREMENTS.md) · [Architecture](ARCHITECTURE.md) · [Building](BUILDING.md) · [Changelog](CHANGELOG.md)
- [Optional extras](INSTALLATION.md#uninstall-and-extras) · [Privacy](PRIVACY.md) · [Notices and licences](NOTICE.md) · [Security](SECURITY.md) · [Contributing](CONTRIBUTING.md)

FreeFG is independent of Intel, AMD, NVIDIA, OptiScaler and HelixSR. Intel's runtime is downloaded unmodified, but
FreeFG changes part of its GPU work; see [notices and terms](NOTICE.md).
