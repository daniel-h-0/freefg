# FreeFG

FreeFG makes Intel XeSS Frame Generation (XeFG) faster on the AMD BC-250, in DirectX 12 games under Proton on Linux.

- Intel's runtime (downloaded unmodified by the user) generates frames. A proxy `libxess_fg.dll` runs part of its GPU work with
  this project's own shaders, which are faster on the BC-250. **By default the generated frames now technically differ slightly from
  Intel's**: seven U-Net shaders run FP16 forms ([what changes](ARCHITECTURE.md#fp16-forms-the-default-slightly-different)). Differences are assessed to be on the range of
  extraordinarily minor to imperceptible - more precision and information on measurement methods/tooling forthcoming!
  With `BC250_XEFG_EXACT=1` (or `Exact=1` in `BC250-XeFG/settings.ini`) every shader runs its exact form, and the
  pixels were identical to Intel's where compared. Seven of those, the F4Q kernels, are identical in every test but not
  proven for every input ([turn them off](ARCHITECTURE.md#f4q-identical-in-every-test-not-proven)).
- A Vulkan layer paces the output for VRR displays, leading to profoundly better frame pacing than vanilla Xe(M)FG. Upscaling runs through OptiScaler, with a BC-250 build of AMD FSR 4
  or HelixSR.
- On GPUs other than Intel's, the runtime generates 2× (Intel's documented limit); **FreeFG itself does not raise that limit.**
  With MFG Unlocker, a separate tool that **does raise that limit**, FreeFG's shaders also run at 3× and 4× and retain their speedups. This project is intentionally designed to work alongside MFG Unlocker,
  but has no affiliation with that project or *official* support.
- This project does not modify Intel's DLL, replace the graphics driver, or run on Windows.

How it works: [ARCHITECTURE.md](ARCHITECTURE.md).

![Cyberpunk 2077 frames shown per second at 2× on an AMD BC-250 (2560×1440, FSR 4 Performance, headless): SDR, XeFG with Intel's shaders 85.30 and FreeFG 1.1.0 104.34 (+22.3%); HDR10, 83.98 and 102.45 (+22.0%).](../../docs/assets/cyberpunk-2x-fps.svg)

Frames per second, generated frames included. Headless, all arms in one block, 4 runs per arm in SDR and in
HDR10, [warm shader caches](MEASUREMENTS.md#shader-caches), 1.1.0's launch settings. FreeFG 1.0.x in the same
block: 102.93 and 101.24.
Details and TV figures: [MEASUREMENTS.md](MEASUREMENTS.md#frame-rate-cyberpunk-2077).

FreeFG is an independent project. It is not affiliated with, endorsed by, sponsored by or supported by Intel, AMD,
NVIDIA, ASRock, Valve or the OptiScaler project. Intel, XeSS and Xe are trademarks of Intel Corporation. AMD, FidelityFX
and FSR are trademarks of Advanced Micro Devices, Inc. NVIDIA and DLSS are trademarks of NVIDIA Corporation. Steam is a
trademark of Valve Corporation. Other names are trademarks of their owners. All are used only to identify what FreeFG
works with.

## Requirements

| Item | Needed |
| --- | --- |
| Hardware | AMD BC-250 (ASRock board, Cyan Skillfish APU, PCI ID `1002:13fe`); [other GPUs](TROUBLESHOOTING.md#other-gpus) |
| System | a Linux distribution with Steam; GE-Proton 11-6 or newer (others untested); a larger GTT helps at 1440p and 4K |
| Graphics driver | Mesa RADV, any current version. The BC-250's compute queue (off in stock Mesa) is optional and needs a kernel with the matching BC-250 fixes. |
| Compositor | gamescope 3.16.28 or newer, as in Steam Game Mode; realtime priority helps ([Extras](#extras)) |
| Setup | Python 3.11 or newer, Zenity (desktop Setup), `bsdtar` (libarchive); network access for the first installation ([PRIVACY.md](PRIVACY.md)) |
| Games | 64-bit DirectX 12 under Proton, from Steam, Heroic or Lutris; an ASCII-only folder path; no anti-cheat (an [override](COMPATIBILITY.md#anti-cheat) per game risks a ban) |

Setup's **Check system** reports each item and warns about a compute-queue Mesa on a kernel without the fixes. Tested
configuration: [MEASUREMENTS.md](MEASUREMENTS.md#test-system). The Steam Deck is untested.

## Install

### Setup

1. Extract the release archive and run `Start-freefg.sh` in Desktop Mode to open Setup.
2. **Add games**: each game's rendering `.exe` (for Unreal Engine games often in `Binaries/Win64`, not the root folder's
   launcher).
3. **Install**: choose the frame-generation input and the [upscaler](#upscaler-fsr-4-or-helixsr). **Automatic per game**
   (recommended) takes the recipe's input, else native XeSS FG where the game ships it, else OptiFG, and shows each
   game's verdict and any steps for you. Install games that need different explicit inputs separately.
4. In the game, select the upscaler that runs FSR 4 (it may be called DLSS, FSR or XeSS) and set frame generation:

| Input | In the game |
| --- | --- |
| DLSS FG | DLSS frame generation on (Streamline 2 or newer). |
| FSR 3.1 FG, FSR 3.0 FG | FSR frame generation on. The HUD is interpolated with the scene, so fast HUD elements can smear slightly. |
| OptiFG | The usual upscaler, the game's frame generation off. OptiFG derives its inputs from upscaling and can affect HUDs. |
| Native XeSS FG | XeSS frame generation on; its runtime DLL must be beside the `.exe`. |

The first start, also with a new frame-generation mode, can pause while shaders compile.

### Command line

```sh
python3 install.py check GAME.exe       # compatibility verdict; changes nothing
python3 install.py preview GAME.exe     # downloads, then shows what would change
python3 install.py install GAME.exe     # Automatic input, FSR 4
python3 install.py configure GAME.exe --upscaler helixsr   # or fsr4
python3 install.py status GAME.exe
python3 install.py restore GAME.exe
python3 install.py helixsr              # download HelixSR
python3 install.py doctor               # Check system
```

`install` also takes `--fg-input` (`dlssg`, `upscaler`, `fsrfg`, `fsrfg30`), `--route native` (the game's own XeSS FG),
`--upscaler helixsr` and `--dlss-helper no` or `yes` ([NOTICE.md](NOTICE.md#nvidias-terms)). A game's existing
OptiScaler must be the 10.0.0-pre1 nightly of 4 or 29 September 2026 (restore or update any other first); a custom DLL
path in `OptiScaler.ini`, symlinked game files or another proxy DLL need manual integration.

## Upscaler: FSR 4 or HelixSR

FSR 4 (the BC-250 build, RC12) is the default. [HelixSR](https://github.com/lonewolf0622/HelixSR) by lonewolf0622
runs NVIDIA's DLSS upscaling network without an NVIDIA GPU; FreeFG ships none of it
([NOTICE.md](NOTICE.md#helixsr)). Frame generation stays XeFG. To use it:

1. Choose **HelixSR (by lonewolf0622)** in Setup (in Install, or **Upscaler** for installed games). Setup offers to
   download its official 2.0.0 release if it is not on your computer ([PRIVACY.md](PRIVACY.md#helixsr-optional)).
2. Build it once in a terminal with its own setup:
   `cd ~/.cache/bc250-xefg-testers/helixsr/HelixSR-2.0.0 && ./helixsr-setup.sh --no-fg` (upscaler only). At its first
   game question press **Ctrl+C**, or answer **n** for each game; it changes no game before its last question. Enter
   would install HelixSR its own way, replacing FreeFG's OptiScaler with HelixSR Scaler.
3. Choose HelixSR in Setup again. In the game, choose the upscaler as for FSR 4.

For games FreeFG installed, use Restore, not HelixSR's uninstaller.

## 3× and 4× with MFG Unlocker

[MFG Unlocker](https://github.com/dashdogy/MFG-Unlocker) by dashdogy is a separate OptiScaler plugin that lifts Intel's
limit on GPUs other than Intel's, up to 6×. FreeFG does not ship it, link it into its own code or change it; support
for it comes from its authors ([NOTICE.md](NOTICE.md#mfg-unlocker-not-shipped)). With it, FreeFG's shaders run on the
work that is still Intel's ([how](ARCHITECTURE.md#another-mod-on-intels-runtime),
[checks](MEASUREMENTS.md#checks-of-100)), under two conditions:

- **OptiScaler's frame generation**: an OptiScaler input (OptiFG, DLSS FG, FSR 3.1 FG or FSR 3.0 FG), not native XeSS
  FG. Beside MFG Unlocker, FreeFG does not accelerate a game's own XeSS frame generation, which then runs Intel's or
  MFG Unlocker's shaders at every frame count ([details](ARCHITECTURE.md#optiscalers-contexts-only)).
- **`XeFGModel=default`** under `[XeFG]` in `OptiScaler.ini`: then FreeFG's shaders run the whole network. Without
  it, MFG Unlocker runs its own model at every frame count, 2× included (table below). Setup writes `default` where the
  INI has no value and keeps a value you set, also across Restore and a new Install. Only MFG Unlocker reads the key;
  without it the key does nothing.

1. Install FreeFG for the game with an OptiScaler input (in Setup, choose it instead of **Automatic per game** where
   that picks native XeSS FG; on the command line, `--fg-input upscaler` or another input), check 2×, and close the
   game.
2. Download `MFGUnlocker-v1.6.0.zip` from its Releases page and check it against its `SHA256SUMS.txt`.
3. Rename `MFGUnlocker.dll` to `MFGUnlocker.asi` and put it in the `OptiScaler/plugins/` folder beside the `.exe`. Do
   not give it a DLL name such as `dxgi.dll`; those are OptiScaler's.
4. In `OptiScaler.ini`, check `XeFGModel` (above) and `LoadAsiPlugins=true` under `[Plugins]`. Setup sets
   `LoadAsiPlugins` only in OptiScaler setups it creates; in a game's existing setup, set it yourself.
5. In the game, set the frame count in OptiScaler's menu (**Insert**, **Frame Generation**), which saves it. OptiScaler's
   frame limit counts output frames: at 4×, 117 FPS is about 29 real frames per second.
6. To return to 2×, remove `MFGUnlocker.asi` and set 2×. Leave `LoadAsiPlugins` on: it also loads OptiPatcher, which
   some games need for their upscaler inputs.

| `[XeFG] XeFGModel` | Network | FreeFG's shaders run on |
| --- | --- | --- |
| `default` | Intel's 2× model at every frame count. MFG Unlocker's authors found that it places the outer generated frames at the wrong times at 6×, which smears them; 3× and 4× are unchecked. | the whole network |
| not set (MFG Unlocker's default) | MFG Unlocker's own model, whose programs replace some of Intel's | 7 of their 13 programs (Cyberpunk 2077) |

In Cyberpunk 2077 with 1.0.0 at 1440p, the game ran 20% (3×) and 25% (4×) faster with `default` than on MFG
Unlocker's own model. At 4K with 1.1.0, OptiScaler's frame generation at 2× showed 53.25 frames per second without MFG
Unlocker and 42.61 with it on its own model ([4K](MEASUREMENTS.md#4k)). With `default`, the picture at 3× and 4× is
unchecked (table above).

![Cyberpunk 2077 frames shown per second with MFG Unlocker and XeFGModel=default on an AMD BC-250 (2560×1440 SDR, FSR 4 Performance, headless): at 3×, MFG Unlocker alone 93.50 and FreeFG 1.1.0 127.91 (+36.8%); at 4× (2 runs per arm), 97.65 and 143.52 (+47.0%).](../../docs/assets/mfg-3x4x-fps.svg)

FreeFG against MFG Unlocker alone, both with `XeFGModel=default`. Frames shown per second, generated frames
included, as in the 2× figure; the game itself renders 31 and 43 FPS at 3×. Headless at 240 Hz, so nothing was capped;
a 120 Hz display shows at most 120. Pacing off, [warm shader caches](MEASUREMENTS.md#shader-caches), 1.1.0's launch
settings; runs per arm: n = 4 at 3×, n = 2 at 4× ([details](MEASUREMENTS.md#3-and-4-with-mfg-unlocker)).

- Before Restore, delete `OptiScaler/plugins/MFGUnlocker.asi` and the `RTXMFG-*` files beside the `.exe` (keep a copy of
  `RTXMFG-Universal.json` for its settings). Otherwise Restore leaves them and their folder, and says so.
- Install sets 2× each time. After a reinstall, put `MFGUnlocker.asi` back if you removed it and set the frame count
  again; Setup writes `XeFGModel` as above.
- To check that FreeFG runs beside MFG Unlocker, use Setup's **Status**
  ([frame generation adds little](TROUBLESHOOTING.md#frame-generation-adds-little)).

## Game compatibility

Before it writes anything, Setup gives every game a verdict, with the way forward for a refused one
([COMPATIBILITY.md](COMPATIBILITY.md)):

- 19 games have a verified recipe from the BC-250.
- 758 games have an entry from the OptiScaler wiki. Its inputs, launch options and compatibility-list verdict guide the
  automatic setup; other advice is shown with its condition.
- Any other 64-bit DirectX 12 game with an upscaler or frame-generation input gets an automatic setup from detection.

## In the game

- Frame generation on or off: the game's settings, or OptiScaler's menu (**Insert**, **Frame Generation**, **Active**).
- On OptiScaler's frame generation, the game's own FPS counter counts only the frames the game renders; an overlay such
  as MangoHud or Steam's performance overlay shows frames shown.
- XeFG does not interpolate in exclusive fullscreen. The installer keeps OptiScaler inputs borderless; with native XeSS
  FG, choose borderless or windowed.
- If the real frame rate times the frame count exceeds the refresh rate, the game's frame rate drops to match, adding
  latency without smoothness.
- Generated frames make motion smoother, not the game more responsive; pacing holds each frame a few milliseconds.
- In Game Mode, set Steam's screensaver timeout to **Never** or install the [extra](#extras); the screensaver runs
  behind games and shows as bursts of VRR flicker ([details](TROUBLESHOOTING.md#problems)).

## What Setup changes

Setup downloads the pinned files in [PRIVACY.md](PRIVACY.md#what-the-installer-downloads) from their publishers, checked
by SHA-256, into `~/.cache/bc250-xefg-testers`. It saves each game file it replaces in the backup folder, then places
the files in the figure beside the game's rendering `.exe` and writes the launch settings
([variables](ARCHITECTURE.md#the-installer)) and a recipe's settings
([COMPATIBILITY.md](COMPATIBILITY.md#supported-games)); existing launch options and wrappers stay. An OptiScaler already
in the game keeps its file name. OptiScaler's support files come only with a fresh setup, `nvngx_dlss.dll` only for a
DLSS input without a game copy. Setup waits until the game, and for launcher settings the launcher, is closed.

![Files Setup places in a game folder, coloured by origin (package, pinned download, written by Setup, kept for Restore), and the five launcher variables it adds.](../../docs/assets/setup-file-layout.svg)

Recorded in a live install of 0.9.0 (Echo Point Nova, Steam, OptiFG input, 19 October 2026); 1.0.0 adds five shaders
and 1.1.0 seven. 1.1.1 adds two launcher variables, `VKD3D_DISABLE_EXTENSIONS` and `VKD3D_SHADER_CACHE_PATH`, and a
folder `vkd3d-cache` for the game's vkd3d-proton shader cache in the backup folder. 1.1.2 adds twelve shaders (the
shader profile holds 61 files; 1.1.1: 49) and the keys `F4Q2` and `Exact` in `BC250-XeFG/settings.ini`.

## Restore and uninstall

Restore puts back every file Setup replaced, removes what it added and its launch settings, and undoes recipe changes to
game settings key by key. It keeps launch options and settings you changed, and names any file that changed after
installation, such as a DLL a game update replaced; the original stays in the backup folder `.bc250-xefg-experimental`
(renamed `-restored-…`; it also holds FreeFG's logs). Restore before you change a game's input, hand its files to
another installer, or install another build.

To uninstall, restore every game, run each installed extra's `uninstall.sh`, and delete the extracted folder, the cache
`~/.cache/bc250-xefg-testers` (with any HelixSR downloaded there) and, once unneeded, the
`.bc250-xefg-experimental-restored-…` folders. HelixSR's own setup keeps its downloads in `~/.local/share/HelixSR`.

## Extras

Optional helpers in `extras/`, each with a README and `uninstall.sh`
([SECURITY.md](SECURITY.md#what-runs-on-your-computer)): `gamescope-cap-sys-nice` gives gamescope realtime priority
(`CAP_SYS_NICE`), which most distributions other than SteamOS leave out; without it, its composition and page flips
queue behind the game's GPU work (uneven VRR refresh). `steam-screensaver-in-game` sets Steam's screensaver timeout to
Never while a game runs, then restores yours.

## Status

1.1.3.1, released 25 October 2026. A global wave64 setting for one Winograd shader avoids a GPU fault isolated in
Cyberpunk 2077 2.5 with HelixSR. Shader code is unchanged; the proxy and profile must be updated together through
Restore, then Install. [Checks and scope](MEASUREMENTS.md#checks-of-1131). It includes 1.1.3's OptiScaler library-path
repairs and 3×/4× VRR pacing improvements, tested with CONTROL Resonant on a physical HDR/VRR TV
([pacing checks](MEASUREMENTS.md#checks-of-113)). The updated Cyberpunk testbed needs further compatibility work;
this hotfix alone does not qualify the bundled recipe for that game version.

Tested only on the AMD BC-250 under Proton. 1.1.2 changes the proxy and the shader profile: the FP16 forms of seven U-Net shaders (on by
default; the output differs slightly from Intel's), F4Q2, F4Q3 and three exact kernel changes; the installer adds the
`Exact` key and an `Output:` line to Status and Check, and installs FSR 4 RC12 instead of RC11. It was checked in the SDK
test program and in Cyberpunk 2077 benchmarks, headless, on GE-Proton 11-11 with RC12: by default its generated images
equal its test build's in 19 configurations, with the exact switch Intel's shaders' in 20; in the game the default shows
1.64% more frames per second than 1.1.1 at 2× in SDR and 1.50% in HDR10 ([checks](MEASUREMENTS.md#checks-of-112)).
Its installer ran live once, in Cyberpunk 2077 (Heroic route, benchmark, headless): Setup placed FSR 4 RC12, Status named
full acceleration and the FP16 forms, and Restore left the game and Heroic as before
([live install](MEASUREMENTS.md#live-install-and-restore)); an earlier 1.1.2 candidate's installer also ran in Echo Point
Nova (Steam). 1.1.1 changed only the installer:
wave sizes apply on every start, Setup writes `XeFGModel=default`, and Status and Check name a partial or skipped
acceleration beside MFG Unlocker. Its proxy, pacing layer, shader profile and OptiScaler are 1.1.0's. Its installer ran
live once on each route, in Echo Point Nova (Steam, to the main menu at 2× and 3×) and Cyberpunk 2077 (benchmark,
headless): it wrote its settings, the wave sizes applied, Status named each start's acceleration, and Restore left both
games and launchers as before ([live install](MEASUREMENTS.md#live-install-and-restore)). Its launch settings' frame
rate was measured headless with 1.1.0's files ([shader caches](MEASUREMENTS.md#shader-caches)). 1.1.0 changed the proxy
and the shader profile and was checked in the SDK test program (generated images identical to Intel's shaders' in 20
configurations, F4Q on and off) and in Cyberpunk 2077 benchmarks ([checks](MEASUREMENTS.md#checks-of-110)); earlier
releases' checks: [MEASUREMENTS.md](MEASUREMENTS.md#checks-of-100). Everything else is untested.

## Known limitations

- 2× on its own; 3× and 4× only with MFG Unlocker. No generated-frame scaling
  ([at 4K](TROUBLESHOOTING.md#frame-generation-adds-little)).
- This build has run in benchmarks, not in gameplay. Flatpak Steam and Heroic are not qualified.
- By default the generated frames differ slightly from Intel's (the FP16 forms; compared on synthetic SDK scenes and by
  eye, not in games). `BC250_XEFG_EXACT=1` in the launch options, or `Exact=1` under `[BC250]` in the game folder's
  `BC250-XeFG/settings.ini`, gives output identical to Intel's in every test; its frame rate in a game was not
  measured.
- F4Q, F4Q2 and F4Q3 were compared with the kernels they replace in games only in Cyberpunk 2077 (2× and 3×, SDR).
  `BC250_XEFG_F4Q=0` or `F4Q=0` turns all of them off (and the FP16 forms); `BC250_XEFG_F4Q2=0` or `F4Q2=0` turns off
  F4Q2 (its three layers then run their F(2×2) kernels, without their FP16 form).
- The first start after an installation takes longer, while vkd3d-proton fills the installation's new shader cache
  ([shader caches](MEASUREMENTS.md#shader-caches)). In a game folder whose path is too long for vkd3d-proton's cache
  file names, Setup leaves that cache as it was, and wave sizes from
  `waves.txt` apply only to pipelines the shader caches do not already hold compiled without them, as in 1.1.0
  ([details](ARCHITECTURE.md#wave-sizes-bc-250-only)).
- Frame pacing works only under gamescope.
- Only a game process's first XeFG context is accelerated.
- FreeFG closes the game when the runtime does something it does not recognise, for example after an update to
  Intel's runtime pin ([details](ARCHITECTURE.md#stepping-aside)).
- HelixSR has had one start with FreeFG; Restore, image and frame rate with it are not checked.

## Troubleshooting

[TROUBLESHOOTING.md](TROUBLESHOOTING.md): the logs, common problems, environment variables and other GPUs.

## Credits and licences

FreeFG's own code is under the MIT licence; every other component keeps its own ([NOTICE.md](NOTICE.md)). Intel's
XeFG runtime is used under Intel's licence, which applies to you as its user; while it runs, FreeFG changes how part
of its GPU work is carried out ([NOTICE.md](NOTICE.md#intels-terms),
[ARCHITECTURE.md](ARCHITECTURE.md#what-is-changed-at-run-time)). [OptiScaler](https://github.com/optiscaler/OptiScaler)
is by its contributors; FreeFG ships a modified GPL-3.0 build ([source](NOTICE.md#optiscaler-source)). HelixSR is by
lonewolf0622; MFG Unlocker, not shipped, is by dashdogy. NOTICE.md credits the FSR 4 build's origins and the OptiScaler
wiki. Security reports and rights holders' concerns: [SECURITY.md](SECURITY.md).

## Documents

[COMPATIBILITY.md](COMPATIBILITY.md) · [TROUBLESHOOTING.md](TROUBLESHOOTING.md) · [ARCHITECTURE.md](ARCHITECTURE.md) ·
[MEASUREMENTS.md](MEASUREMENTS.md) · [PRIVACY.md](PRIVACY.md) · [NOTICE.md](NOTICE.md) · [BUILDING.md](BUILDING.md) ·
[CHANGELOG.md](CHANGELOG.md) · [CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md)
