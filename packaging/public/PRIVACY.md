# Privacy

FreeFG collects nothing and sends nothing. It has no telemetry, no update check, no crash reporting and no account.
Only the installer uses the network, and only to download the pinned files listed below. The parts that run in the game
(the proxy DLL, the shader profile and the pacing layer) make no network connections.

## What the installer downloads

- Every file comes from its publisher's public release location on GitHub.
- The installer checks each download's size and SHA-256 against the values below, which are pinned in
  `dependencies.json` in the release, and refuses a mismatch.
- Files inside an archive are extracted by their exact names and checked by their own SHA-256.
- Downloads are kept in `$XDG_CACHE_HOME/bc250-xefg-testers` (normally `~/.cache/bc250-xefg-testers`), so each is
  downloaded once. You can delete that folder at any time.
- The installer never runs anything it downloads. The DLLs run later, inside your game, like any other game DLL.
- A preview (`install.py preview`) downloads the same files, because its checks need them.

| What | When | URL | SHA-256 | Size (bytes) |
| --- | --- | --- | --- | --- |
| OptiScaler 10.0.0-pre1 nightly of 2026-09-29 (OptiScaler's support files; also a source of Intel's runtime below) | a fresh setup (a game without OptiScaler); otherwise only as a fallback source of Intel's runtime, if both downloads from Intel's repository fail | https://github.com/optiscaler/OptiScaler-nightly/releases/download/nightly-20260929/OptiScaler_v10.0.0-pre1_20260929.7z | `29d5715d55b88a27452ea99f92fdca083138698d8435fd3d7a98ff65812b88e3` | 56,901,752 |
| OptiPatcher 0.41 (OptiScaler plug-in) | fresh setup | https://github.com/optiscaler/OptiPatcher/releases/download/v0.41/OptiPatcher_v0.41.asi | `fb12735bfcc0d47f534f2206d57ec34129dc3d22b6405a1c2ef86745ab48b2eb` | 95,232 |
| Intel XeFG runtime 1.3.1.78 (`libxess_fg.dll`), unmodified | every installation, unless the same bytes come from the OptiScaler archive | https://raw.githubusercontent.com/intel/xess/de0fb9c1c510661c571164e1418ceca8101dab69/bin/libxess_fg.dll | `ec5e0c65e075570c6ede72618bb666d0be0c2e10b2ea9762c0fe8cb8e375ab27` | 22,957,432 |
| Intel XeLL runtime 1.3.2.10 (`libxell.dll`), unmodified | as above | https://raw.githubusercontent.com/intel/xess/de0fb9c1c510661c571164e1418ceca8101dab69/bin/libxell.dll | `d2030dcd694fda8f2ec7e044b13e6db8f0b56d4ba9113a5efad334e3f3ded8c7` | 415,368 |
| Intel's licence for that runtime | as above | https://raw.githubusercontent.com/intel/xess/de0fb9c1c510661c571164e1418ceca8101dab69/LICENSE.txt | `784be42c39a4a4d03cf85d88e15e59d75828fca773ce45b8dbfffbd7eaf208df` | 4,194 |
| Fallback: the same Intel runtime file at the commit of Intel's `v3.0.2` tag | only if the download from commit `de0fb9c1` fails | https://raw.githubusercontent.com/intel/xess/8fe81bdbbaf00b3c1b733fd0d830c333dc84e6f0/bin/libxess_fg.dll | `ec5e0c65e075570c6ede72618bb666d0be0c2e10b2ea9762c0fe8cb8e375ab27` | 22,957,432 |
| Fallback: the same XeLL file at that commit | as above | https://raw.githubusercontent.com/intel/xess/8fe81bdbbaf00b3c1b733fd0d830c333dc84e6f0/bin/libxell.dll | `d2030dcd694fda8f2ec7e044b13e6db8f0b56d4ba9113a5efad334e3f3ded8c7` | 415,368 |
| Fallback: the same licence at that commit | as above | https://raw.githubusercontent.com/intel/xess/8fe81bdbbaf00b3c1b733fd0d830c333dc84e6f0/LICENSE.txt | `784be42c39a4a4d03cf85d88e15e59d75828fca773ce45b8dbfffbd7eaf208df` | 4,194 |
| Last fallback: Intel's XeSS SDK 3.0.2 release archive (only the three Intel files above are extracted) | only if every other source of Intel's files fails | https://github.com/intel/xess/releases/download/v3.0.2/XeSS_SDK_3.0.2.zip | `88b8a373f30e33f3558a77a93e634f11b8132fc3047ea1a8edeead32b8471990` | 76,839,749 |
| FSR 4 upscaler DLL, BC-250 build RC11 (INT8), with its notices | every installation | https://github.com/daniel-h-0/bc250-fsr4-fork/releases/download/v4.0.0-rc11/bc250-fsr4-dll-4.0.0-rc11.zip | `95ef0c6ea887e0506a3a92f7e4648e7ab7e1100e99f5eff2f70dd33b8dff2a72` | 50,865,005 |
| NVIDIA DLSS Super Resolution DLL 310.7.0 (`nvngx_dlss.dll`), unmodified | a fresh setup on a DLSS input, only when OptiScaler's own search finds no copy of the game's; `--dlss-helper yes` places it on any input ([NOTICE.md](NOTICE.md#nvidias-terms)) | https://raw.githubusercontent.com/NVIDIA/DLSS/a291cc7d2cc642a51566f3dfd5376f635cd1b284/lib/Windows_x86_64/rel/nvngx_dlss.dll | `be6e434a94ca32499515eb62ca0e6c274526055d568d0426e4c652dcdfb6ee6e` | 58,977,904 |
| NVIDIA's licence for that DLL | with the DLL | https://raw.githubusercontent.com/NVIDIA/DLSS/a291cc7d2cc642a51566f3dfd5376f635cd1b284/LICENSE.txt | `21b5daec892b12bea692e66bc8fe45cf5902ccaf3a7b831e78050d8859881c37` | 27,176 |
| HelixSR 2.0.0, its complete official release archive (a separate project by lonewolf0622, under its own licence) | only when you choose HelixSR (Setup, or `install.py helixsr`) and it is not on your computer yet | https://github.com/lonewolf0622/HelixSR/releases/download/v2.0.0/HelixSR-2.0.0.zip | `0d60686eddbb0abd680b27d12a088344b212464ebf0a2dc18d10387e1c817f52` | 136,997,025 |

The fallback rows hold the same bytes as the rows above them and are checked against the same SHA-256.

Download totals:

| Case | Size |
| --- | --- |
| A game without OptiScaler (fresh setup) | about 110 MB |
| A game that already has the supported OptiScaler | about 74 MB |
| Where the DLSS helper is placed | 59 MB more |
| HelixSR, when you choose it | 137 MB; unpacked unchanged into `helixsr/` in the same cache, after which the archive is deleted |

### What a download reveals

Like any HTTPS download, each request tells GitHub (github.com and its download hosts, raw.githubusercontent.com) your
IP address, the time and the file requested. The request carries a fixed User-Agent string that names the installer
(`freefg-installer/1`). It sends no information about your system or games, and no identifier. GitHub's own
privacy statement applies to those requests.

## HelixSR (optional)

[HelixSR](https://github.com/lonewolf0622/HelixSR) is a separate project by lonewolf0622. FreeFG downloads only its
release archive (the table above), and only when you choose it. FreeFG never runs HelixSR's setup and never downloads
anything of NVIDIA's for it.

You run HelixSR's setup yourself, once: `./helixsr-setup.sh --no-fg` in the unpacked folder (Setup shows the command).
What it downloads is under HelixSR's control; read its README. With `--no-fg` it downloads:

- NVIDIA's DLSS DLL 310.7.0, from NVIDIA's DLSS repository on GitHub. It asks you first, builds the network from the DLL
  on your computer, and deletes the DLL. The network it builds is NVIDIA's: keep it on your computer.
- Python with numpy, when your system has none. It offers to install them with your distribution's package manager (with
  `sudo`), or downloads a portable Python from GitHub (astral-sh/python-build-standalone) and numpy from PyPI.
- Microsoft's DirectX Shader Compiler, from Microsoft's GitHub releases. It runs the compiler through Proton or Wine.

Without `--no-fg` it also downloads NVIDIA's DLSS frame-generation DLLs and NVIDIA's NGX core. FreeFG does not need
them (frame generation stays XeFG).

Files HelixSR keeps:

- Its setup's downloads: `~/.local/share/HelixSR`.
- The network it builds: the unpacked HelixSR folder.
- In a game, `OptiScaler/helixsr.log` next to its DLL. It records your GPU and what HelixSR does. Restore moves it into
  the game's backup folder. Check it before you share it.

## What the installer reads and writes on your computer

The installer writes only:

- the game folder you select: it saves the files it will replace in a backup folder there (`.bc250-xefg-experimental`),
  places its files, makes a folder in the backup folder for the game's vkd3d-proton shader cache (`vkd3d-cache`, which
  the game fills), and on Restore puts the originals back and deletes that cache;
- launcher configuration: only the selected game's entries, and only after the launcher has been closed;
- the game's own settings file in its Proton prefix, where a recipe turns the game's frame generation on. Restore
  reverts those keys;
- its download cache ([above](#what-the-installer-downloads)).

Launcher configuration it reads, for native and Flatpak installs, to find the game and write its launch settings:

- Steam: its library list, app manifests, and each local account's `localconfig.vdf` and `shortcuts.vdf` (every local
  account's configuration is read to find the game's entry);
- Heroic: its game configuration and library caches;
- Lutris: its game configuration.

The compatibility check (before every install, and Setup's **Check**) only reads, and makes no network request:

- the game's executable and DLL headers and import tables, and a search of the executable and its engine DLLs for the
  names of upscaler and graphics functions (nothing from the game folder is run);
- the game folder's file names;
- Steam's app manifests, its `appinfo.vdf` launch entries, `config.vdf` (which Proton the game uses) and the game's
  launch options; Heroic's library records;
- the game's own log or `GameUserSettings.ini` in its Proton prefix (which graphics API it used);
- the installed GE-Proton's per-game fix for the game;
- after a run, the logs in the game folder, only where an installation of FreeFG is recorded (another tool's logs are
  not read).

Its report (`--report`) is text for you to paste into an issue yourself. It contains the package name, the game's name,
store and ID, the GPU, kernel, gamescope and Proton lines of **Check system**, the verdict and what the check detected,
a summary of the last run's logs and, for a game installed despite its anti-cheat, the date of that override. It
replaces your home folder, user name and the game's library folder (also as the game sees them under Wine, `Z:\...`),
and names the executable only by its file name.

**Check system** reads the GPU's PCI IDs, the kernel version, the Vulkan driver's queue layout, memory sizes and clocks,
gamescope's version and capabilities, and the installed Proton builds. It tests whether Steam's local DevTools port
(127.0.0.1:8080) is listening. It changes nothing.

## What runs in the game

- Logs in the game folder: `BC250-MFG.log` and `BC250-XeFG-fast.log` (with HelixSR, also its `OptiScaler/helixsr.log`,
  see [above](#helixsr-optional)). They hold the game executable's path (which can include your user name), your GPU's
  PCI IDs, timings and shader hashes. Only Setup's **Status** and the compatibility check read them, on your computer.
  Check them before you share them.
- The pacing layer writes status lines to the game's standard error. It talks to the proxy in the same process through a
  small shared-memory page (`/dev/shm/bc250-xefg-pace-…`), and connects to the game's local X display to wake gamescope
  ([SECURITY.md](SECURITY.md#the-pacing-layer)).

## Extras

- `steam-screensaver-in-game` talks only to Steam's DevTools endpoint on 127.0.0.1:8080, on your own computer. It reads
  whether a game is running and sets Steam's two screensaver timeouts.
- `gamescope-cap-sys-nice` records gamescope's previous capability in `/var/lib/bc250-xemfg-gamescope-cap/previous`, so
  that it can restore it.

## Building from source

The release build downloads its pinned public inputs (Intel's public headers and licence texts, Intel's runtime DLL for
the export-table check, OptiScaler's licence, the FSR 4 notices) from raw.githubusercontent.com, with the User-Agent
`freefg-release-fetch`. [BUILDING.md](BUILDING.md) lists the sources.
