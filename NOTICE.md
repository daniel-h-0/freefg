<!-- Copy of packaging/public/NOTICE.md for this folder of the repository, written by release/export_tree.py --public with its links adjusted; edit packaging/public/NOTICE.md instead. -->
# Notices and licences

FreeFG's own code is under the MIT licence. Every other component keeps its own licence; nothing here relicenses
anyone else's work. The release archive contains only the files listed under [Shipped](#shipped-in-the-release-archive).
The installer downloads the components listed under [Downloaded](#downloaded-by-the-installer-not-shipped) from their
publishers on your behalf; [PRIVACY.md](packaging/public/PRIVACY.md) gives each download's condition, URL and SHA-256.

## FreeFG's licence

MIT License. The text is in `LICENSE` in the source tree and in `licenses/freefg.txt` in the release. It covers the
files marked `SPDX-License-Identifier: MIT` and the other files this project wrote. It does not cover anyone else's
software, model data or documents.

## Trademarks and affiliation

FreeFG is not affiliated with, endorsed by, sponsored by or supported by Intel, AMD, NVIDIA, ASRock, Valve or the
OptiScaler project. Intel, XeSS and Xe are trademarks of Intel Corporation. AMD, FidelityFX and FSR are trademarks of
Advanced Micro Devices, Inc. NVIDIA and DLSS are trademarks of NVIDIA Corporation. Steam is a trademark of Valve
Corporation. Other names are trademarks of their owners. All are used only to identify what FreeFG works with.

## Rights holders

[SECURITY.md](packaging/public/SECURITY.md#concerns-from-rights-holders) describes how rights holders can raise a concern and when the
release is taken down.

## Shipped in the release archive

| Component | Files in the archive | Origin | Licence |
| --- | --- | --- | --- |
| FreeFG | every file not named in another row: the installer and Setup (the package's top-level `.py` files and `Start-freefg.sh`), `dependencies.json`, `extras/`, the proxy `payload/libxess_fg.dll`, the pacing layer `payload/BC250-XeFG/layer/`, the shader profile `payload/BC250-XeFG/shaders/`, `payload/BC250-XeFG/settings.ini`, `manifest.json`, `qualification/`, the documents | this project | MIT (`licenses/freefg.txt`) |
| Per-game recipes | `recipes/recipes.json` | this project and the sources in [Per-game recipes](#per-game-recipes) | MIT for this project's part |
| PyYAML 6.0.3 (pure Python), unmodified; reads and writes Lutris settings | `vendor/yaml/` | Kirill Simonov and the PyYAML contributors | MIT (`vendor/PyYAML-LICENSE.txt`, `licenses/PyYAML.txt`) |
| OptiScaler, modified build | `opti/OptiScaler.dll` | the [OptiScaler](https://github.com/optiscaler/OptiScaler) contributors, plus three commits by this project | GNU GPL version 3 (`licenses/OptiScaler.txt`); the code of other projects inside it: `licenses/OptiScaler-third-party/`. See [OptiScaler source](#optiscaler-source). |
| Licence texts of the downloaded components | `licenses/Intel-XeSS.txt`, `licenses/Intel-third-party-programs.txt`, `licenses/fsr4/` | as named | as named |

[Build inputs](#build-inputs-not-shipped) lists what the binaries are compiled against.

### Per-game recipes

`recipes/recipes.json` combines:

- this project's findings on the BC-250;
- community reports, reviewed by the maintainers;
- facts from the [OptiScaler wiki](https://github.com/optiscaler/OptiScaler/wiki), revision `9812e2d` (17 October 2026):
  titles, tested versions, inputs, settings and their stated conditions, launch options, proxy names, the compatibility
  list's verdict, and links to the pages. No page text is copied. Setup labels these lines "OptiScaler wiki (community
  reports)" and links the page. Credit belongs to the wiki's contributors and to the game reporters named on its pages;
- the list of OptiScaler's built-in game fixes, from the shipped build `f971ed14` and upstream `737a21d5`.

### The shader profile

`payload/BC250-XeFG/shaders/` holds 40 shaders, compiled with Microsoft's DirectX Shader Compiler from this project's
HLSL source, and 9 other files: this project's tables (`waves.txt` and `dispatch-scale.txt` name shaders by hash) and
switches. The shaders contain no weights and none of Intel's code or constant tables. They read the network's
coefficients at run time from the buffers Intel's runtime uploads ([ARCHITECTURE.md](packaging/public/ARCHITECTURE.md)).

The release build runs a static check over the whole package (`release/check_intel_free.py`). It fails on:

- a file whose SHA-256 is that of an Intel file or of one of the shader programs of Intel's runtime;
- a DXIL shader that is not one of the profile's own;
- a DXIL shader of shader model 6.4;
- a copy of Intel's warp weight tables.

The release passes the check with no allowance. OptiScaler's embedded shaders are recognised as OptiScaler's and still
get every other check.

## Downloaded by the installer, not shipped

| Component | Placed in the game folder as | Publisher and origin | Licence | Notes |
| --- | --- | --- | --- | --- |
| Intel XeSS Frame Generation runtime 1.3.1.78 and XeLL 1.3.2.10 | `bc250_xefg_original.dll`, `libxell.dll` | Intel Corporation, [intel/xess](https://github.com/intel/xess) commit `de0fb9c1`, or the same bytes from the fallback sources in [PRIVACY.md](packaging/public/PRIVACY.md) | Intel Simplified Software License, October 2022 (`licenses/Intel-XeSS.txt`); third-party notices in `licenses/Intel-third-party-programs.txt` | Unmodified and Intel-signed. See [Intel's terms](#intels-terms). |
| FSR 4 upscaler DLL, BC-250 build RC12 (INT8) | `OptiScaler/amd_fidelityfx_upscaler_dx12.dll` | built by the [bc250-fsr4-fork](https://github.com/daniel-h-0/bc250-fsr4-fork) project from AMD FidelityFX SDK v2.3.0 (commit `60f4ea81`), release `v4.0.0-rc12` | AMD's FidelityFX SDK notice lists `amd_fidelityfx_upscaler_dx12.dll` under its MIT terms (`licenses/fsr4/AMD-SDK-LICENSE.md`). The fork's new tooling is MIT (`licenses/fsr4/LICENSE.new-code`). The shader assembly was validated with Microsoft's DXC (`licenses/fsr4/LICENSE-LLVM.txt`, `LICENSE-MS.txt`). | Provenance in `licenses/fsr4/PROVENANCE.md` and `V4-THIRD-PARTY.md`. Credit for the original BC-250 FSR 4 work belongs to [dmorazasanchez/bc250-fsr4](https://github.com/dmorazasanchez/bc250-fsr4) and its contributors. |
| OptiScaler 10.0.0-pre1 nightly of 2026-10-25, support files | `OptiScaler.ini`, `OptiScaler/…` (FidelityFX, XeSS and DirectX 12 Agility SDK DLLs, `dlssg_to_fsr3_amd_is_better.dll`, a fetcher script), `OptiScaler/Licenses/` | the OptiScaler project, [OptiScaler-nightly](https://github.com/optiscaler/OptiScaler-nightly) | each file under its publisher's terms, as OptiScaler distributes it; the licences it ships are installed in `OptiScaler/Licenses/` | The nightly's own `OptiScaler.dll` is replaced by the modified build above. |
| OptiPatcher 0.41 | `OptiScaler/plugins/OptiPatcher.asi` | the OptiScaler project, [OptiPatcher](https://github.com/optiscaler/OptiPatcher) | its project's terms | Unmodified. |
| NVIDIA DLSS Super Resolution 310.7.0 | `nvngx_dlss.dll`, `OptiScaler/Licenses/NVIDIA-DLSS-LICENSE.txt` | NVIDIA Corporation, [NVIDIA/DLSS](https://github.com/NVIDIA/DLSS) commit `a291cc7d` | NVIDIA RTX SDKs License (placed beside it) | Unmodified. See [NVIDIA's terms](#nvidias-terms). |
| HelixSR 2.0.0 (optional upscaler) | `OptiScaler/amd_fidelityfx_upscaler_dx12.dll` (the DLL HelixSR's own setup built on your computer) and `OptiScaler/helixsr.ini` (written by FreeFG) | lonewolf0622, [lonewolf0622/HelixSR](https://github.com/lonewolf0622/HelixSR) release `v2.0.0`: the complete official archive, unpacked unchanged into the download cache | HelixSR Freeware License (`LICENSE` in that archive) | See [HelixSR](#helixsr). |

## OptiScaler source

The bundled `opti/OptiScaler.dll` is a modified build of OptiScaler, licensed under the GNU GPL version 3. Its complete
corresponding source is included in the source companion and identified by tag `bc250-be42012`, commit
`be42012aff2dbe26e5565d076e50f227e428cad1`. The fork repository is <https://github.com/daniel-h-0/OptiScaler>.
The tag adds the updated FORK.md to the build commit.

The source is upstream master of 19 October 2026 (`c2e44a8bc911010d7ed3e4fa63843185fbb55d03`) with these changes:

- A fixed lock order for the Streamline plugin locks of upstream `f6db41d` ("Try to prevent race conditions when hooking
  sl plugins", 26 September 2026): the Windows loader lock first, then the plugin's lock, and no plugin lock held across
  a library load. Upstream's order since that commit can deadlock with the loader lock at start-up in some Streamline
  games; CONTROL Resonant hung on about half of its starts with an earlier upstream build.
- Automatic saving of menu changes.
- Build-portability fixes for the Linux cross-build.
- Independent XeSS, XeFG and XeLL library-path configuration, with a save/reload regression check.

Where to get it:

- The fork's source tree lists its submodules with their public repositories and commits.
- This release's source archive (named in `SOURCE.md`) carries the same source with its build script.
- The fork's release at that tag offers the source as one archive together with its submodules, apart from Intel's XeSS
  SDK, which comes from its own repository.

OptiScaler contains code of other projects, compiled or linked into the DLL. Their licence texts are in
`licenses/OptiScaler-third-party/`; its `README.md` lists each component with its licence and copyright holders.
FreeType asks for this credit: Portions of this software are copyright © 2024 The FreeType Project (www.freetype.org).
All rights reserved.

This build is not an official OptiScaler or OptiScaler Client release. Its version string ends in `(BC250 private)`,
fixed text of this build; its source is the public source above.

## Intel's terms

Intel licenses the XeFG and XeLL runtime "in binary form only … without modification", on conditions that include this
one: "No reverse engineering, decompilation, or disassembly of the Software is permitted, nor any modification or
alteration of the Software or its operation at any time, including during execution." Your right to use the runtime ends
if you breach the licence.

- FreeFG does not ship Intel's runtime. The installer downloads it, unmodified, from Intel's public repository (or
  takes the identical copy from OptiScaler's nightly archive), and you use it under Intel's licence.
- While the runtime runs, FreeFG changes how part of its GPU work is carried out.
  [ARCHITECTURE.md](packaging/public/ARCHITECTURE.md#what-is-changed-at-run-time) lists the changes.
- Intel has not given this project permission to do this. This project cannot tell you whether that change is compatible
  with Intel's licence. Decide for yourself whether to use FreeFG.
- `BC250_XEFG_DISABLE=1` runs Intel's own shaders.

Intel's name is used here only to identify its software, not to endorse or promote FreeFG.

## NVIDIA's terms

NVIDIA's licence says that the DLSS SDK is "licensed for you to develop applications only for their use in systems with
NVIDIA GPUs". The BC-250 has an AMD GPU. On it, OptiScaler handles a game's DLSS calls itself and needs `nvngx_dlss.dll`
only to be present for its DLSS inputs; NVIDIA's DLSS does not run.

When the installer places the file:

- Only in a fresh OptiScaler setup whose input is DLSS, and only when OptiScaler's own search finds no copy of the
  game's. That search covers the game executable's folder and the folders below it, plus the engine folder of Win64,
  WinGDK and Win64MasterMasterSteamPGO layouts.
- It never replaces a game's own copy. A copy outside that search stays where the game put it.
- `install.py --dlss-helper no` never places the file. `--dlss-helper yes` places it on any input.
- If you do not want it, choose an input other than DLSS.

Without that file, or a copy of the game's that OptiScaler finds, OptiScaler's default (`Spoofing.Dxgi=auto`) turns its
GPU spoofing off, as upstream OptiScaler does in a game without DLSS. The game then sees the AMD GPU, which can change
the upscaler and Reflex options it offers. `--dlss-helper yes` keeps the spoofing on. Its effect in games without DLSS
and without a recipe has not been measured.

## HelixSR

[HelixSR](https://github.com/lonewolf0622/HelixSR) is a separate project by lonewolf0622, not part of FreeFG. Its
source is not published. It runs NVIDIA's DLSS Model E upscaling network as Direct3D 12 compute shaders.

Its licence, the HelixSR Freeware License:

- allows free use;
- allows redistribution only of the complete, unmodified official release, free of charge;
- forbids modification and reverse engineering;
- says that the network files HelixSR's setup builds from NVIDIA's DLSS DLL remain NVIDIA's and must not be shared.

How FreeFG handles it:

- It ships none of HelixSR.
- When you choose HelixSR, the installer downloads the complete official release from HelixSR's own GitHub releases
  page, pinned by version and SHA-256, and unpacks it unchanged.
- You run HelixSR's own setup. It asks you before it downloads NVIDIA's DLSS DLL, and it builds the network on your
  computer.
- The installer copies the DLL that setup built into the games you choose, on your computer only. Before it does, it
  checks that the DLL is the official file of a HelixSR release it knows, with only the locally built network appended.
  Restore removes the copies.
- It never changes HelixSR's files, never downloads NVIDIA's files for HelixSR, never builds the network, and never
  ships or uploads it.
- The only HelixSR setting it writes is the documented `[DlssFrameGeneration] Enabled = false` in `helixsr.ini`.
  HelixSR's licence does not count a change through `helixsr.ini` as a modification.

NVIDIA's licence speaks of systems with NVIDIA GPUs ([NVIDIA's terms](#nvidias-terms)), and HelixSR's setup downloads
NVIDIA's DLSS DLL under that licence. HelixSR runs NVIDIA's network on other GPUs. This project cannot tell you whether
that is compatible with NVIDIA's licence; HelixSR's own documentation describes its position. Decide for yourself
whether to use HelixSR. FSR 4 remains the default.

## MFG Unlocker (not shipped)

[MFG Unlocker](https://github.com/dashdogy/MFG-Unlocker) by dashdogy is a separate tool, not part of FreeFG. The
README links to it for 3× and 4× ([3× and 4× with MFG Unlocker](README.md#3-and-4-with-mfg-unlocker)).

- FreeFG does not ship, download, mirror or install it. Its installer neither places nor removes it.
- MFG Unlocker's own code is under the MIT licence. Its NOTICE says that its DLL also contains programs derived from
  Intel's XeSS SDK, which stay under Intel's licence.
- While the runtime runs, it lifts Intel's limit of one generated frame per real frame on GPUs other than Intel's. That
  change is MFG Unlocker's, made by your choice to add it, not FreeFG's. Whether to use it, and whether that is
  compatible with [Intel's terms](#intels-terms), is your decision.
- FreeFG does not read, hook or patch MFG Unlocker, and contains none of its code. It detects that another module
  hooks Intel's runtime by comparing the runtime's entry points in memory with Intel's file on disk. It then runs its
  own shaders only where the runtime still runs Intel's
  ([ARCHITECTURE.md](packaging/public/ARCHITECTURE.md#another-mod-on-intels-runtime)).
- Setup writes `XeFGModel=default` under `[XeFG]` in `OptiScaler.ini` where it is unset. Only MFG Unlocker reads that
  key; with it, FreeFG's shaders run the whole network beside MFG Unlocker. Status and Check look for its plugin file
  by name and read FreeFG's own logs.

## Build inputs (not shipped)

The release binaries are built from this project's source with these inputs. None of them is in the archive.
[BUILDING.md](packaging/public/BUILDING.md) has the versions and hashes.

- Intel's public XeFG and XeLL headers (intel/xess commit `de0fb9c1`), fetched at build time and never stored in the
  source tree. The XeFG headers carry Intel's proprietary notice; the XeLL headers are MIT. The proxy uses them for the
  API's types and constants.
- Intel's runtime DLL (the same pinned file), read at build time to check the proxy's export table against Intel's,
  ordinal by ordinal. It is not copied into any output.
- Wine 11.16 headers and x86-64 import libraries (LGPL-2.1-or-later), for the proxy, which is compiled with clang/lld,
  linked with `-nostdlib`, and imports only `kernel32.dll` and `ucrtbase.dll`. `release/generated/com_thunks.*` are
  forwarding stubs that this project generates from the method lists in Wine's `d3d12.h`.
- glibc, GCC and the Khronos Vulkan headers, for the pacing layer.
- Microsoft's DirectX Shader Compiler, for the shader profile.
