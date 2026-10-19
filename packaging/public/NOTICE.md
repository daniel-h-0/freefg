# Notices and licences

FreeFG's own code is under the MIT licence. Every other component keeps its own licence. Nothing here relicenses
anyone else's work. The release archive contains only the items under [Shipped](#shipped-in-the-release-archive). The
installer downloads the items under [Downloaded](#downloaded-by-the-installer-not-shipped) from their publishers on your
behalf, the first time they are needed, and checks each one by SHA-256 ([PRIVACY.md](PRIVACY.md) lists them all).

FreeFG is not affiliated with, endorsed by or sponsored by Intel, AMD, NVIDIA, ASRock, Valve or the OptiScaler
project. Intel, XeSS and Xe are trademarks of Intel Corporation. AMD, FidelityFX and FSR are trademarks of Advanced
Micro Devices, Inc. NVIDIA and DLSS are trademarks of NVIDIA Corporation. Other names are trademarks of their owners
and are used only to identify what FreeFG works with.

Rights holders with a concern about FreeFG can open an issue at <https://github.com/daniel-h-0/freefg/issues>
or raise it privately through the repository's **Security** tab (**Report a vulnerability**), and GitHub's own DMCA
process is open to them too. The project answers promptly and takes the release down on a credible request
([Rights holders](README.md#rights-holders)).

## Shipped in the release archive

| Component | Files in the archive | Origin | Licence | Notes |
| --- | --- | --- | --- | --- |
| FreeFG | installer and Setup (`install.py`, `setup.py`, `launcher_config.py`, `steam_config.py`, `recipes.py`, `dependencies.py`, `doctor.py`, `Start-freefg.sh`), `extras/`, the proxy `payload/libxess_fg.dll`, the pacing layer `payload/BC250-XeFG/layer/` (`libxefg_wave.so`, `layer.json`), the shader profile `payload/BC250-XeFG/shaders/`, `payload/BC250-XeFG/settings.ini`, `manifest.json`, `qualification/`, the documents | this project | MIT (`licenses/freefg.txt`) | See [Build inputs](#build-inputs-not-shipped) for what the binaries are compiled against. |
| Per-game recipes | `recipes/recipes.json` | this project's BC-250 findings, plus facts from the [OptiScaler wiki](https://github.com/optiscaler/OptiScaler/wiki) (revision `67f573d5`, 25 September 2026) and the list of OptiScaler's built-in game fixes (upstream `92337ebf`) | MIT for this project's part | From the wiki: titles, tested versions, inputs, settings, launch options and links to the pages, as facts; no page text is copied. Credit to the wiki's contributors and the game reporters named on its pages. |
| PyYAML 6.0.3 (pure Python) | `vendor/yaml/` | Kirill Simonov and the PyYAML contributors | MIT (`vendor/PyYAML-LICENSE.txt`, `licenses/PyYAML.txt`) | Unmodified; used to read and write Lutris settings. |
| OptiScaler, modified build | `opti/OptiScaler.dll` | the [OptiScaler](https://github.com/optiscaler/OptiScaler) contributors, plus four commits by this project | GNU GPL version 3 (`licenses/OptiScaler.txt`) | See [OptiScaler source](#optiscaler-source). |
| Licence texts | `licenses/` | as named | as named | Includes Intel's licence (`Intel-XeSS.txt`, `Intel-third-party-programs.txt`) and the FSR 4 notices (`fsr4/`), for the downloaded components below. |

### The shader profile

The 28 shaders in `payload/BC250-XeFG/shaders/` are compiled with Microsoft's DirectX Shader Compiler from this
project's HLSL source. They contain no weights, and none of Intel's code or constant tables: they read the network's
coefficients at run time from the buffers Intel's runtime uploads (see [ARCHITECTURE.md](ARCHITECTURE.md)). The release
build runs a static check over the whole package (`release/check_intel_free.py`). It fails on any file whose SHA-256 is
that of an Intel file or of one of the shader programs of Intel's runtime, any DXIL that is not one of the profile's own
shaders, any DXIL of shader model 6.4, and any copy of Intel's warp weight tables. The release passes it without any
allowance; OptiScaler's own embedded shaders are recognised as OptiScaler's and still get every other check. The other
9 files are
this project's tables (`waves.txt` and `dispatch-scale.txt` name shaders by hash) and switches.

## Downloaded by the installer, not shipped

| Component | Placed in the game folder as | Publisher and source | Licence | Notes |
| --- | --- | --- | --- | --- |
| Intel XeSS Frame Generation runtime 1.3.1.78 and XeLL 1.3.2.10 | `bc250_xefg_original.dll`, `libxell.dll` | Intel Corporation, [intel/xess](https://github.com/intel/xess) at commit `de0fb9c1`; if that download fails, the same bytes from the `v3.0.2` tag's commit, OptiScaler's nightly archive or the XeSS SDK 3.0.2 release archive ([PRIVACY.md](PRIVACY.md)) | Intel Simplified Software License, October 2022 (`licenses/Intel-XeSS.txt`); third-party notices in `licenses/Intel-third-party-programs.txt` | Unmodified and Intel-signed. See [Intel's terms](#intels-terms). |
| FSR 4 upscaler DLL, BC-250 build RC11 (INT8) | `OptiScaler/amd_fidelityfx_upscaler_dx12.dll` | built by the [bc250-fsr4-fork](https://github.com/daniel-h-0/bc250-fsr4-fork) project from AMD FidelityFX SDK v2.3.0 (commit `60f4ea81`), release `v4.0.0-rc11` | AMD's FidelityFX SDK notice lists `amd_fidelityfx_upscaler_dx12.dll` under its MIT terms (`licenses/fsr4/AMD-SDK-LICENSE.md`); the fork's new tooling is MIT (`licenses/fsr4/LICENSE.new-code`); the shader assembly was validated with Microsoft's DXC (`licenses/fsr4/LICENSE-LLVM.txt`, `LICENSE-MS.txt`) | Provenance in `licenses/fsr4/PROVENANCE.md` and `V4-THIRD-PARTY.md`. Credit for the original BC-250 FSR 4 work belongs to [dmorazasanchez/bc250-fsr4](https://github.com/dmorazasanchez/bc250-fsr4) and its contributors. |
| OptiScaler 10.0.0-pre1 nightly of 2026-09-29, support files (fresh setup only) | `OptiScaler.ini`, `OptiScaler/…` (FidelityFX, XeSS and DirectX 12 Agility SDK DLLs, `dlssg_to_fsr3_amd_is_better.dll`, a fetcher script), `OptiScaler/Licenses/` | the OptiScaler project, [OptiScaler-nightly](https://github.com/optiscaler/OptiScaler-nightly) | each file under its publisher's terms, as distributed by OptiScaler; the licences it ships are installed in `OptiScaler/Licenses/` | The nightly's own `OptiScaler.dll` is replaced by the modified build above. |
| OptiPatcher 0.41 (fresh setup only) | `OptiScaler/plugins/OptiPatcher.asi` | the OptiScaler project, [OptiPatcher](https://github.com/optiscaler/OptiPatcher) | its project's terms | Unmodified. |
| NVIDIA DLSS Super Resolution 310.7.0 (fresh setup on a DLSS input, only when OptiScaler finds no copy of the game's own) | `nvngx_dlss.dll`, `OptiScaler/Licenses/NVIDIA-DLSS-LICENSE.txt` | NVIDIA Corporation, [NVIDIA/DLSS](https://github.com/NVIDIA/DLSS) at commit `a291cc7d` | NVIDIA RTX SDKs License (placed beside it) | Unmodified. See [NVIDIA's terms](#nvidias-terms). |

## Build inputs (not shipped)

The release binaries are built from this project's source with these inputs, none of which is in the archive:

- **Intel's public XeFG and XeLL headers** (intel/xess at commit `de0fb9c1`), fetched at build time and never stored in
  the source tree. The XeFG headers carry Intel's proprietary notice. The XeLL headers are MIT. The proxy uses them for
  the API's types and constants.
- **Intel's runtime DLL** (the same pinned file), read at build time to check the proxy's export table against
  Intel's, ordinal by ordinal. It is not copied into any output.
- **Wine's headers and x86-64 import libraries** (Wine 11.16, LGPL-2.1-or-later), compiled with clang/lld. The proxy is
  linked with `-nostdlib` and imports only `kernel32.dll` and `ucrtbase.dll`. `release/generated/com_thunks.*` are
  forwarding stubs generated by this project from the method lists in Wine's `d3d12.h`.
- **glibc, GCC and the Khronos Vulkan headers** for the pacing layer.
- **Microsoft's DirectX Shader Compiler** for the shader profile.

[BUILDING.md](BUILDING.md) has the versions and hashes.

## OptiScaler source

The bundled `opti/OptiScaler.dll` is a modified build of OptiScaler, licensed under the GNU GPL version 3. Its complete
corresponding source is available at **<https://github.com/daniel-h-0/OptiScaler>**, tag **`bc250-a793287`**, commit
`a7932870f9988b86692aabf9e8908e2adc61e1f0` (the tag is that commit plus its FORK.md and build script). It is upstream
nightly-20260929 (`92337ebfbf07d533eabe3731fd8de1bb19437aea`) with four commits:

- a revert of upstream `f6db41d` ("Try to prevent race conditions when hooking sl plugins"), whose Streamline plugin
  locks can deadlock with the Windows loader lock at start-up (CONTROL Resonant hung on about half of its starts);
- build-portability and resource-initialisation fixes;
- automatic saving of menu changes;
- a menu section for generated-frame scaling, which this build does not use.

Its submodules are listed in that source tree with their public repositories and commits. This release's source
archive (named in `SOURCE.md`) carries the same source with its build script. The release of the fork at that tag
offers it as one archive together with its submodules, apart from Intel's XeSS SDK, which comes from its own
repository.

OptiScaler contains code of other projects, compiled or linked into the DLL. Their licence texts are in
`licenses/OptiScaler-third-party/`, whose `README.md` lists each component with its licence and copyright holders.
FreeType asks for this credit: Portions of this software are copyright © 2024 The FreeType Project
(www.freetype.org). All rights reserved.

This build is not an official OptiScaler or OptiScaler Client release.

## Intel's terms

Intel licenses the XeFG and XeLL runtime "in binary form only … without modification", on conditions that include
this one: "No reverse engineering, decompilation, or disassembly of the Software is permitted, nor any modification or
alteration of the Software or its operation at any time, including during execution." Your right to use the runtime
ends if you breach the licence. FreeFG does not ship Intel's runtime. The installer downloads it, unmodified, from
Intel's public repository (or takes the identical copy from OptiScaler's nightly archive) for you, and you use it under
Intel's licence. While it runs, FreeFG changes how part of
its GPU work is carried out: [ARCHITECTURE.md](ARCHITECTURE.md) lists exactly what. Intel has not given this project
permission to do this, and this project cannot tell you whether that change is compatible with Intel's licence. Decide
for yourself whether to use FreeFG. `BC250_XEFG_DISABLE=1` runs Intel's own shaders. Intel's name is used here only
to identify its software, not to endorse or promote FreeFG.

## NVIDIA's terms

NVIDIA's licence says that the DLSS SDK is licensed for applications used on systems with NVIDIA GPUs. The BC-250 has
an AMD GPU. On it, OptiScaler handles a game's DLSS calls itself and needs `nvngx_dlss.dll` only to be present for
its DLSS inputs; NVIDIA's DLSS does not run. The installer places the file only in a fresh OptiScaler setup whose
input is DLSS, and only when OptiScaler's own search (the game executable's folder and the folders below it, plus the
engine folder of Win64, WinGDK and Win64MasterMasterSteamPGO layouts) finds no copy of the game's. It never replaces a
game's own copy: one outside that search stays where the game put it. `install.py --dlss-helper no` never places the
file; `--dlss-helper yes` places it on any input. If you do not want it, choose an input other than DLSS.

Without that file, or a copy of the game's that it finds, OptiScaler's default (`Spoofing.Dxgi=auto`) turns its GPU
spoofing off, so the game sees the AMD GPU, as upstream OptiScaler does in a game without DLSS; that can change which
upscaler and Reflex options the game offers. `--dlss-helper yes` keeps the spoofing on. Its effect in games without
DLSS and without a recipe has not been measured.

## FreeFG's licence

MIT License. The licence text is in `LICENSE` in the source tree and in `licenses/freefg.txt` in the release. It
covers the files marked `SPDX-License-Identifier: MIT` and the other files this project wrote. It does not cover
anyone else's software, model data or documents.
