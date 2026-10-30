# Notices and licences

FreeFG's code is MIT-licensed. Third-party components retain their own terms. This page distinguishes files
[shipped in the archive](#shipped-in-the-release-archive) from [installer downloads](#downloaded-by-the-installer-not-shipped).
[PRIVACY.md](PRIVACY.md) lists download URLs, conditions and hashes.

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

[SECURITY.md](SECURITY.md#concerns-from-rights-holders) describes how rights holders can raise a concern and when the
release is taken down.

## Shipped in the release archive

| Component | Files in the archive | Origin | Licence |
| --- | --- | --- | --- |
| FreeFG | every file not named in another row: the installer and Setup (the package's top-level `.py` files and `Start-freefg.sh`), `dependencies.json`, `extras/`, the proxy `payload/libxess_fg.dll`, the pacing layer `payload/BC250-XeFG/layer/`, the shader profile `payload/BC250-XeFG/shaders/`, `payload/BC250-XeFG/settings.ini`, `manifest.json`, `qualification/`, the documents | this project | MIT (`licenses/freefg.txt`) |
| Per-game recipes | `recipes/recipes.json` | this project and the sources in [Per-game recipes](#per-game-recipes) | MIT for this project's part |
| PyYAML 6.0.3 (pure Python), unmodified; reads and writes Lutris settings | `vendor/yaml/` | Kirill Simonov and the PyYAML contributors | MIT (`vendor/PyYAML-LICENSE.txt`, `licenses/PyYAML.txt`) |
| FidelityFX Super Resolution 1 EASU | compiled into `payload/BC250-XeFG/shaders/freefg-up-fsr1.dxil`; CPU constant setup in the proxy | AMD, [FidelityFX-FSR](https://github.com/GPUOpen-Effects/FidelityFX-FSR) commit `a21ffb8f6c13233ba336352bdff293894c706575`; source headers and provenance under `vendor/fsr1/` | MIT (`licenses/AMD-FSR1.txt`) |
| OptiScaler, modified build | `opti/OptiScaler.dll`, `opti/OptiScaler.ini` | the [OptiScaler](https://github.com/optiscaler/OptiScaler) contributors and this project | GNU GPL version 3 (`licenses/OptiScaler.txt`); the code of other projects inside it: `licenses/OptiScaler-third-party/`. See [OptiScaler source](#optiscaler-source). |
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
- the list of OptiScaler's built-in game fixes, from the shipped fork `03db4f86` and upstream `08e13adf`.

### The shader profile

`payload/BC250-XeFG/shaders/` contains **83 shaders and 10 tables/markers**. The shaders are compiled from the supplied
HLSL, including AMD's EASU implementation, and contain no model weights; coefficients are read from runtime buffers. Tables identify pipelines
by hash. [Mechanism](ARCHITECTURE.md#the-shader-profile) · [Build recipes](BUILDING.md#the-shader-profile).

The release passes `release/check_intel_free.py` with no allowance. That check rejects known Intel files and shader
bytecode, unrecognised embedded DXIL, shader model 6.4 and known Intel warp-weight tables. Pinned OptiScaler shaders
are recognised separately and undergo the remaining checks. This is a content check, not a licence determination.

## Downloaded by the installer, not shipped

| Component | Placed in the game folder as | Publisher and origin | Licence | Notes |
| --- | --- | --- | --- | --- |
| Intel XeSS Frame Generation runtime 1.3.1.78 and XeLL 1.3.2.10 | `bc250_xefg_original.dll`, `libxell.dll` | Intel Corporation, [intel/xess](https://github.com/intel/xess) commit `de0fb9c1`, or the same bytes from the fallback sources in [PRIVACY.md](PRIVACY.md) | Intel Simplified Software License, October 2022 (`licenses/Intel-XeSS.txt`); third-party notices in `licenses/Intel-third-party-programs.txt` | Unmodified and Intel-signed. See [Intel's terms](#intels-terms). |
| FSR 4 upscaler DLL, BC-250 build RC12 (INT8) | `OptiScaler/amd_fidelityfx_upscaler_dx12.dll` | built by the [bc250-fsr4-fork](https://github.com/daniel-h-0/bc250-fsr4-fork) project from AMD FidelityFX SDK v2.3.0 (commit `60f4ea81`), release `v4.0.0-rc12` | AMD's FidelityFX SDK notice lists `amd_fidelityfx_upscaler_dx12.dll` under its MIT terms (`licenses/fsr4/AMD-SDK-LICENSE.md`). The fork's new tooling is MIT (`licenses/fsr4/LICENSE.new-code`). The shader assembly was validated with Microsoft's DXC (`licenses/fsr4/LICENSE-LLVM.txt`, `LICENSE-MS.txt`). | Provenance in `licenses/fsr4/PROVENANCE.md` and `V4-THIRD-PARTY.md`. Credit for the original BC-250 FSR 4 work belongs to [dmorazasanchez/bc250-fsr4](https://github.com/dmorazasanchez/bc250-fsr4) and its contributors. |
| OptiScaler 10.0.0-pre1 nightly of 2026-10-25, support files | `OptiScaler.ini`, `OptiScaler/…` (FidelityFX, XeSS and DirectX 12 Agility SDK DLLs, `dlssg_to_fsr3_amd_is_better.dll`, a fetcher script), `OptiScaler/Licenses/` | the OptiScaler project, [OptiScaler-nightly](https://github.com/optiscaler/OptiScaler-nightly) | each file under its publisher's terms, as OptiScaler distributes it; the licences it ships are installed in `OptiScaler/Licenses/` | The nightly's own `OptiScaler.dll` is replaced by the modified build above. |
| OptiPatcher 0.41 | `OptiScaler/plugins/OptiPatcher.asi` | the OptiScaler project, [OptiPatcher](https://github.com/optiscaler/OptiPatcher) | its project's terms | Unmodified. |
| NVIDIA DLSS Super Resolution 310.7.0 | `nvngx_dlss.dll`, `OptiScaler/Licenses/NVIDIA-DLSS-LICENSE.txt` | NVIDIA Corporation, [NVIDIA/DLSS](https://github.com/NVIDIA/DLSS) commit `a291cc7d` | NVIDIA RTX SDKs License (placed beside it) | Unmodified. See [NVIDIA's terms](#nvidias-terms). |
| HelixSR 3.1.0 (optional HLX DLSS / HLX FSR 4 upscalers) | checked, locally built DLLs under `OptiScaler/custom/hlx-dlss/` or `OptiScaler/custom/hlx-fsr4/`, and `helixsr.ini` written by FreeFG | lonewolf0622, [lonewolf0622/HelixSR](https://github.com/lonewolf0622/HelixSR) release `v3.1.0`: the complete official archive, unpacked unchanged into the download cache | HelixSR Freeware License (`LICENSE` in that archive) | See [HelixSR](#helixsr). |

## OptiScaler source

The bundled GPL-3.0 DLL is built from commit `03db4f8692878e65748769ebe583c053cae96360`, based on upstream
`08e13adf55b3fd71a67071eac2e95973ac598df3` (25 October 2026). Its SHA-256 is
`b3602882c7e194af523e50861a222d63c0c56b013cff4bfb5b187ca4f6666656`.

The [fork release `bc250-03db4f8`](https://github.com/daniel-h-0/OptiScaler/releases/tag/bc250-03db4f8) provides the DLL
and matching source archive. The tag includes build documentation at `d191284a`; `SOURCE.md` in the FreeFG archive
identifies its source companion and build route. Available submodules are bundled; Intel's XeSS SDK is a separately
fetched, pinned input.

The fork retains loader-first Streamline locking, automatic menu saving, Linux cross-build support, independent
XeSS/XeFG/XeLL paths and adaptive 3×/4× game-frame starts. It is not an official OptiScaler release.

Third-party licence texts and the component index are in `licenses/OptiScaler-third-party/`.
Required FreeType credit: Portions of this software are copyright © 2024 The FreeType Project (www.freetype.org).
All rights reserved.

## Intel's terms

Intel licenses the XeFG and XeLL runtime "in binary form only … without modification", on conditions that include this
one: "No reverse engineering, decompilation, or disassembly of the Software is permitted, nor any modification or
alteration of the Software or its operation at any time, including during execution." Your right to use the runtime ends
if you breach the licence.

- FreeFG does not ship Intel's runtime. The installer downloads it, unmodified, from Intel's public repository (or
  takes the identical copy from OptiScaler's nightly archive), and you use it under Intel's licence.
- While the runtime runs, FreeFG changes how part of its GPU work is carried out.
  [ARCHITECTURE.md](ARCHITECTURE.md#what-is-changed-at-run-time) lists the changes.
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

[HelixSR 3.1.0](https://github.com/lonewolf0622/HelixSR), by lonewolf0622, is a separate project distributed under the
HelixSR Freeware License. Its upscaler source is not published. It runs DLSS-derived or FSR 4-derived upscaling through locally prepared compute shaders.

Its licence permits free use and redistribution of the complete, unmodified official release without charge. It
prohibits modification and reverse engineering. Network files built from NVIDIA's DLSS DLL remain NVIDIA's and must
not be shared. The licence permits configuration through `helixsr.ini`.

FreeFG ships no HelixSR files or locally built model data. On request it downloads and verifies the complete official
archive and shader compilers. Prepare HLX runs its unchanged build-only Python entry point in an isolated writable
staging directory with networking disabled, using the user's local model inputs. It does not run Helix's game
installer or fetch NVIDIA/AMD model files. FreeFG verifies complete prepared hashes, copies the selected provider
into the user's games and disables Helix's own frame generation. Restore removes the owned copies.

HelixSR obtains NVIDIA's DLL under [NVIDIA's terms](#nvidias-terms), which refer to NVIDIA-GPU systems. This project
has no permission from NVIDIA to extend those terms. Consult the licences and HelixSR's documentation when deciding
whether to use it. FSR 4 is the default upscaler.

## MFG Unlocker (not shipped)

[MFG Unlocker](https://github.com/dashdogy/MFG-Unlocker), by dashdogy, is an optional, separate tool that lifts Intel's
non-Intel frame-count limit. FreeFG does not ship, download, install or remove it.

MFG Unlocker's code is MIT-licensed. Its NOTICE identifies included programs derived from Intel's XeSS SDK, which
retain Intel's terms. Its in-memory changes to Intel's runtime are also relevant to [Intel's licence](#intels-terms).

FreeFG contains no MFG Unlocker code and does not read, hook or patch that module. It detects hooks on Intel's
runtime and substitutes its own shaders where Intel's programs remain. Setup writes `XeFGModel=default` when unset;
only MFG Unlocker reads that setting. [Setup and limitations](README.md#3-and-4-with-mfg-unlocker).

## Build inputs (not shipped)

The release binaries are built from this project's source with these inputs. None of them is in the archive.
[BUILDING.md](BUILDING.md) has the versions and hashes.

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
