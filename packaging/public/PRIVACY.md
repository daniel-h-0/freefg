# Privacy

FreeFG has no telemetry, account, update check or crash uploader. The installer uses the network only to download
the pinned files listed here. In the game, FreeFG writes local logs, shares one memory page between its two parts and
connects to the game's X display. The two optional extras use local interfaces, described below.

## Downloads

Every download comes from a public GitHub location and is checked by SHA-256 and, where pinned, by size. Files inside
an archive are extracted by name and checked one by one. HelixSR's archive is checked as a whole and unpacked as
[Security](SECURITY.md#the-installer) describes. Preview downloads what the proposed installation needs. Apart from
HelixSR's build (below), the installer runs nothing it downloads; the installed DLLs run later, in the game.

Downloads are cached under `$XDG_CACHE_HOME/bc250-xefg-testers` (normally `~/.cache/bc250-xefg-testers`) and checked
again before each use. The table mirrors `dependencies.json`; the documentation check fails when they differ.

| What | When | URL | SHA-256 | Size (bytes) |
| --- | --- | --- | --- | --- |
| OptiScaler 10.0.0-pre1 nightly of 2026-11-11 (OptiScaler's support files; also a source of Intel's runtime below) | a fresh setup (a game without OptiScaler); otherwise only as a fallback source of Intel's runtime, if both downloads from Intel's repository fail | https://github.com/optiscaler/OptiScaler-nightly/releases/download/nightly-20261111/OptiScaler_v10.0.0-pre1_20261111.7z | `c7cff235da733e2b778962cb1532dd18380c621d113375f513b5d65832f4611e` | 72,450,177 |
| OptiPatcher 0.41 (OptiScaler plug-in) | fresh setup | https://github.com/optiscaler/OptiPatcher/releases/download/v0.41/OptiPatcher_v0.41.asi | `fb12735bfcc0d47f534f2206d57ec34129dc3d22b6405a1c2ef86745ab48b2eb` | 95,232 |
| Intel XeFG runtime 1.3.1.78 (`libxess_fg.dll`), unmodified | every installation, unless the same bytes come from the OptiScaler archive | https://raw.githubusercontent.com/intel/xess/de0fb9c1c510661c571164e1418ceca8101dab69/bin/libxess_fg.dll | `ec5e0c65e075570c6ede72618bb666d0be0c2e10b2ea9762c0fe8cb8e375ab27` | 22,957,432 |
| Intel XeLL runtime 1.3.2.10 (`libxell.dll`), unmodified | as above | https://raw.githubusercontent.com/intel/xess/de0fb9c1c510661c571164e1418ceca8101dab69/bin/libxell.dll | `d2030dcd694fda8f2ec7e044b13e6db8f0b56d4ba9113a5efad334e3f3ded8c7` | 415,368 |
| Intel's licence for that runtime | as above | https://raw.githubusercontent.com/intel/xess/de0fb9c1c510661c571164e1418ceca8101dab69/LICENSE.txt | `784be42c39a4a4d03cf85d88e15e59d75828fca773ce45b8dbfffbd7eaf208df` | 4,194 |
| Fallback: the same Intel runtime file at the commit of Intel's `v3.0.2` tag | only if the download from commit `de0fb9c1` fails | https://raw.githubusercontent.com/intel/xess/8fe81bdbbaf00b3c1b733fd0d830c333dc84e6f0/bin/libxess_fg.dll | `ec5e0c65e075570c6ede72618bb666d0be0c2e10b2ea9762c0fe8cb8e375ab27` | 22,957,432 |
| Fallback: the same XeLL file at that commit | as above | https://raw.githubusercontent.com/intel/xess/8fe81bdbbaf00b3c1b733fd0d830c333dc84e6f0/bin/libxell.dll | `d2030dcd694fda8f2ec7e044b13e6db8f0b56d4ba9113a5efad334e3f3ded8c7` | 415,368 |
| Fallback: the same licence at that commit | as above | https://raw.githubusercontent.com/intel/xess/8fe81bdbbaf00b3c1b733fd0d830c333dc84e6f0/LICENSE.txt | `784be42c39a4a4d03cf85d88e15e59d75828fca773ce45b8dbfffbd7eaf208df` | 4,194 |
| Last fallback: Intel's XeSS SDK 3.0.2 release archive (only the three Intel files above are extracted) | only if every other source of Intel's files fails | https://github.com/intel/xess/releases/download/v3.0.2/XeSS_SDK_3.0.2.zip | `88b8a373f30e33f3558a77a93e634f11b8132fc3047ea1a8edeead32b8471990` | 76,839,749 |
| FSR 4 upscaler DLL, BC-250 build RC12 (INT8), with its notices | every installation | https://github.com/daniel-h-0/bc250-fsr4-fork/releases/download/v4.0.0-rc12/bc250-fsr4-dll-4.0.0-rc12.zip | `646778a0d06c42bf3cdcc99f9396680f5cc4a33658b90c0889fd15751bfb800d` | 50,186,200 |
| NVIDIA DLSS Super Resolution DLL 310.7.0 (`nvngx_dlss.dll`), unmodified | a fresh setup on a DLSS input, only when OptiScaler's own search finds no copy of the game's; `--dlss-helper yes` places it on any input ([NOTICE.md](NOTICE.md#nvidias-terms)) | https://raw.githubusercontent.com/NVIDIA/DLSS/a291cc7d2cc642a51566f3dfd5376f635cd1b284/lib/Windows_x86_64/rel/nvngx_dlss.dll | `be6e434a94ca32499515eb62ca0e6c274526055d568d0426e4c652dcdfb6ee6e` | 58,977,904 |
| NVIDIA's licence for that DLL | with the DLL | https://raw.githubusercontent.com/NVIDIA/DLSS/a291cc7d2cc642a51566f3dfd5376f635cd1b284/LICENSE.txt | `21b5daec892b12bea692e66bc8fe45cf5902ccaf3a7b831e78050d8859881c37` | 27,176 |
| HelixSR 2.0.0, its complete official release archive (a separate project by lonewolf0622, under its own licence) | only if the legacy `install.py helixsr` command requests 2.0.0 and it is not cached | https://github.com/lonewolf0622/HelixSR/releases/download/v2.0.0/HelixSR-2.0.0.zip | `0d60686eddbb0abd680b27d12a088344b212464ebf0a2dc18d10387e1c817f52` | 136,997,025 |

The fallback sources hold the same pinned Intel files. With an empty cache, a fresh setup downloads about 123 MB and
a game that already has a supported OptiScaler about 74 MB, plus 59 MB if the DLSS helper is needed. The legacy
2.0.0 command downloads a 137 MB archive, unpacks it beneath `helixsr/` in the cache and removes the ZIP.
HelixSR 3.3.0 is a separate download, described below.

### Request data

GitHub and its download hosts receive the requesting IP address, the time and the requested file. Requests carry the
fixed User-Agent `freefg-installer/1`. No game list, system report, credential or device or user identifier is sent.
GitHub's privacy terms govern those requests.

## HelixSR (optional)

[HelixSR 3.3.0](https://github.com/lonewolf0622/HelixSR), by lonewolf0622, is a separate project. FreeFG downloads
the files below by pinned hash when you install or switch to an HLX upscaler that is not prepared yet, or prepare
one ahead (Setup's **Upscalers…**, `install.py hlx`). Setup lists them before it starts. With AMD FSR 4 none of them
is downloaded.

| File | When | Source | SHA-256 | Bytes |
| --- | --- | --- | --- | --- |
| HelixSR 3.3.0, its complete official release archive | the first use of any HLX upscaler, when it is not cached | https://github.com/lonewolf0622/HelixSR/releases/download/v3.3.0/HelixSR-3.3.0.zip | `7d6c0a4adeb5237004fc6fbe211d39705d62d49f23c51cc8f4ea987281d0a56b` | 279,492,763 |
| Microsoft's DirectX Shader Compiler 1.9.2607 | a build of HLX DLSS, when it is not cached | https://github.com/microsoft/DirectXShaderCompiler/releases/download/v1.9.2607/dxc_2026_07_29.zip | `a1dfb116ba3eeae6a1582291b53a8e7bf65ad760676bd3194685c8f7367cd241` | 41,625,275 |
| NVIDIA's DLSS 310.7.0 DLL, the pinned file listed above | a build of HLX DLSS, when no local copy is given or cached (`--no-download-dlss` refuses the download) | as above | as above | 58,977,904 |

If HelixSR's author replaces a release's archive in place, FreeFG refuses the changed file until a FreeFG release
pins it.

Prepare Helix runs the archive's own build script, unchanged, with `--no-fg`. Bubblewrap mounts the host read-only,
makes only the preparation folder writable and gives the build no network. The build uses the Wine and Python with
numpy already on the computer. It installs no system package and does not run HelixSR's game installer. HLX FSR 4
and HLX FSR 4 Full come built in the archive and need no build, model input or build tool.

The prepared files are kept per archive under `~/.cache/bc250-xefg-testers/hlx/` (or the cache root `XDG_CACHE_HOME`
names), together with the path of a prepared folder you selected. FreeFG copies the checked DLLs and model data into
each game's OptiScaler custom folder. Built model data stays on your computer: it is not uploaded and no FreeFG
release contains it. Each upscaler's log stays beside its DLL. Records of the earlier HelixSR 2.0.0 keep what Restore
needs for its files and log. [Notices](NOTICE.md#helixsr).

## Local files

| Location | Use |
| --- | --- |
| Selected game folder | Back up replaced files, install runtime/configuration, record changes, and normally create an installation-specific vkd3d cache. Restore reverts owned files and removes that cache. An update also saves the files it replaces there for Rollback. |
| Launcher records | Find and edit only the selected game's launch entry, after the launcher closes. Steam discovery reads every local account's configuration. |
| Game's Proton settings | Apply recipe keys and retain originals for Restore. Later user edits are preserved. |
| Download cache | Store verified payloads, extracted HelixSR and its remembered location. |
| Library index | Store local executable paths, installation IDs and package names at `$XDG_DATA_HOME/freefg/library.json` (default `~/.local/share/freefg/library.json`). `FREEFG_LIBRARY` may select an absolute alternative. It is optional and rebuildable; Restore removes its entry. |

What each action reads:

| Action | Reads | Writes |
| --- | --- | --- |
| Finding games | Steam library lists, app manifests, `appinfo.vdf`, Proton selections, launch options and each local account's `localconfig.vdf` and `shortcuts.vdf`; Heroic's library and configuration caches; Lutris game configuration. Native and Flatpak locations (Flatpak launchers are untested) | nothing |
| **Update All Games…**, `plan --all` | the environment of every Steam, Heroic and Lutris launch entry, and the optional index | Plan writes nothing. An update writes FreeFG's own launcher fields when its plan includes a migration |
| Check | headers, imports and function-name strings of the game's executables and DLLs; file names; launcher metadata; GE-Proton's fix for the game; game settings and logs that show the graphics API; FreeFG's logs of a recorded installation | nothing. It runs no game file and contacts no service |
| **System Check** | PCI IDs, kernel and Proton versions, Vulkan queues, GPU memory and clocks, gamescope's capabilities; it also tries Steam's local DevTools port | nothing |

Install, Update and Register refresh the index entry of their game. The index is never uploaded.

`check --report` prepares a text for you to send; it uploads nothing. The report has versions, the game's store ID,
configuration, the verdict and a log summary. Known home, user and library paths are replaced, also in their Wine
forms, and the executable is named without its folder. Read it before you share it: raw logs are not redacted.

## In the game

`BC250-MFG.log` and `BC250-XeFG-fast.log` sit beside the executable. They can contain executable paths, GPU IDs, timing
and shader hashes. HelixSR adds its own log. Status and Check read these locally; nothing uploads them.

The pacing layer writes to standard error, shares one page with the proxy under `/dev/shm/bc250-xefg-pace-…` (the
signal that frames are being generated) and connects to the game's X display to wake the compositor.
[Local interfaces and permissions](SECURITY.md#the-pacing-layer).

## Extras

- `steam-screensaver-in-game` uses Steam's unauthenticated `127.0.0.1:8080` DevTools endpoint. It reads game-running
  state, changes AC/battery screensaver timeouts and stores previous values in
  `$XDG_STATE_HOME/bc250-steam-screensaver-in-game.json` (normally under `~/.local/state`).
- `gamescope-cap-sys-nice` records the previous capability in `/var/lib/bc250-xemfg-gamescope-cap/previous` and may
  install a pacman hook. It requires sudo.

## Building from source

A build from source fetches pinned API headers, the inputs that identify Intel's runtime and its exports, licence
texts and toolchains, with the User-Agent `freefg-release-fetch`. [Building](BUILDING.md) lists the sources and
checks. Installing and playing make none of these requests.
