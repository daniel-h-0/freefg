# Privacy

FreeFG has no telemetry, account, automatic update check or crash uploader. Its installer makes external requests
for pinned downloads. Runtime components use local logs, shared memory and the game's X display; optional helpers
also use local interfaces described below.

## What the installer downloads

Downloads come from public GitHub locations and are verified by size and SHA-256. Pinned dependency members are
extracted by name and checked individually. The optional HelixSR download is instead verified as a complete archive
and safely extracted as described in [SECURITY.md](SECURITY.md#the-installer). Preview downloads the dependencies it
needs for the proposed installation. The installer does not execute downloaded setup scripts; installed DLLs run later
in the game.

Files are cached under `$XDG_CACHE_HOME/bc250-xefg-testers` (normally `~/.cache/bc250-xefg-testers`). Reused files are
verified before use. The table mirrors `dependencies.json`; automated checks detect URL/hash/size drift.

| What | When | URL | SHA-256 | Size (bytes) |
| --- | --- | --- | --- | --- |
| OptiScaler 10.0.0-pre1 nightly of 2026-10-25 (OptiScaler's support files; also a source of Intel's runtime below) | a fresh setup (a game without OptiScaler); otherwise only as a fallback source of Intel's runtime, if both downloads from Intel's repository fail | https://github.com/optiscaler/OptiScaler-nightly/releases/download/nightly-20261025/OptiScaler_v10.0.0-pre1_20261025.7z | `6bb2e9cd6ac0204c76c974df1c202afb1fc7a765844a9ccf608103557aa595fe` | 57,146,678 |
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
| HelixSR 2.0.0, its complete official release archive (a separate project by lonewolf0622, under its own licence) | only when you choose HelixSR (Setup, or `install.py helixsr`) and it is not on your computer yet | https://github.com/lonewolf0622/HelixSR/releases/download/v2.0.0/HelixSR-2.0.0.zip | `0d60686eddbb0abd680b27d12a088344b212464ebf0a2dc18d10387e1c817f52` | 136,997,025 |

Fallback sources provide identical pinned Intel files. Cold-cache totals are about 107 MB for a fresh setup or
74 MB with supported OptiScaler already installed, plus 59 MB if the DLSS helper is needed. HelixSR adds a 137 MB
archive, unpacked beneath `helixsr/` in the cache; its downloaded ZIP is then removed.

### What a download reveals

GitHub and its download hosts receive the requesting IP address, time and requested file. Requests use the fixed
legacy User-Agent `freefg-installer/1`; no game list, system report, account credential or unique device/user
identifier is sent. GitHub's privacy terms govern those requests.

## HelixSR (optional)

[HelixSR 3.1.0](https://github.com/lonewolf0622/HelixSR), by lonewolf0622, is a separate project. On request,
FreeFG downloads its complete official archive and Microsoft's shader compilers by pinned hash. The NVIDIA DLSS
and AMD driver model inputs are local files selected by the user; this preparation route does not download them.

Prepare HLX runs the archive's unchanged build-only Python entry point with `--no-fg`. Bubblewrap mounts the host
read-only, makes only the preparation directory writable and disables networking for the build. It uses existing
Wine and Python/numpy; it does not install system packages or run Helix's game installer.

The archive-specific preparation cache is under `~/.cache/bc250-xefg-testers/hlx/` unless `XDG_CACHE_HOME` selects
another cache root. A remembered prepared-folder path is local to that archive identity. FreeFG copies the checked
model-bearing DLLs into each selected game's custom-provider folder. These files remain on the user's computer;
no built model data is uploaded or included in a FreeFG release. Provider logs remain beside the installed DLLs.
Legacy HelixSR 2.0.0 records retain their original-file and log recovery information. [Notices](NOTICE.md#helixsr).

## What the installer reads and writes on your computer

| Location | Use |
| --- | --- |
| Selected game folder | Back up replaced files, install runtime/configuration, record changes, and normally create an installation-specific vkd3d cache. Restore reverts owned files and removes that cache. An update also saves the files it replaces there for Rollback. |
| Launcher records | Find and edit only the selected game's launch entry, after the launcher closes. Steam discovery reads every local account's configuration. |
| Game's Proton settings | Apply recipe keys and retain originals for Restore. Later user edits are preserved. |
| Download cache | Store verified payloads, extracted HelixSR and its remembered location. |
| Library index | Store local executable paths, installation IDs and package names at `$XDG_DATA_HOME/freefg/library.json` (default `~/.local/share/freefg/library.json`). `FREEFG_LIBRARY` may select an absolute alternative. It is optional and rebuildable; Restore removes its entry. |

Discovery reads Steam library lists, app manifests, `appinfo.vdf`, Proton selections, launch options and local account
`localconfig.vdf`/`shortcuts.vdf`; Heroic library/configuration caches; and Lutris game configuration. Native and Flatpak
locations are recognised, though Flatpak launcher operation is not qualified. Update All Games and `plan --all` read every
Steam, Heroic and Lutris launch entry's environment and the optional index to find installations; they write no launcher record. Install, Update and Register refresh index entries. No index is uploaded.

Check reads executable/DLL headers, imports and relevant function-name strings; filenames; launcher metadata;
GE-Proton's per-game fix; game settings/logs indicating the graphics API; and FreeFG logs for recorded
installations. It does not run game files, modify the game or contact external services.

**System Check** reads PCI IDs, kernel/Proton versions, Vulkan queues, GPU memory/clocks and gamescope capabilities.
It also tests Steam's local DevTools port. It does not change system configuration.

`check --report` prepares text for you to submit; it does not upload it. The report includes versions, game/store ID,
configuration, verdict and a log summary. It replaces known home/user/library paths, including Wine forms, and shows
the executable basename. Review it before sharing; raw logs are not redacted automatically.

## What runs in the game

`BC250-MFG.log` and `BC250-XeFG-fast.log` sit beside the executable. They can contain executable paths, GPU IDs, timing
and shader hashes. HelixSR adds its own log. Status and Check read these locally; nothing uploads them.

The pacing layer writes to standard error, shares a generation-signal page with the proxy under
`/dev/shm/bc250-xefg-pace-…`, and connects to the game's X display for compositor wake-ups.
[Local interfaces and permissions](SECURITY.md#the-pacing-layer).

## Extras

- `steam-screensaver-in-game` uses Steam's unauthenticated `127.0.0.1:8080` DevTools endpoint. It reads game-running
  state, changes AC/battery screensaver timeouts and stores previous values in
  `$XDG_STATE_HOME/bc250-steam-screensaver-in-game.json` (normally under `~/.local/state`).
- `gamescope-cap-sys-nice` records the previous capability in `/var/lib/bc250-xemfg-gamescope-cap/previous` and may
  install a pacman hook. It requires sudo.

## Building from source

Build tools fetch pinned API headers, runtime identity/export inputs, licence texts and toolchains. The release fetcher
uses User-Agent `freefg-release-fetch`. [BUILDING.md](BUILDING.md) lists sources and checks; these build-time
requests are separate from installation and gameplay.
