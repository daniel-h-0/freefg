# Third-party code in OptiScaler.dll

`opti/OptiScaler.dll` is a modified build of OptiScaler, licensed under the GNU GPL version 3
(`licenses/OptiScaler.txt`). The OptiScaler source it is built from contains code of other projects, which is compiled
or linked into the DLL. This folder holds their licence texts, unchanged.

The list below comes from the build of the DLL itself (fork commit `a7932870`, 18 October 2026): every source file its
compiler read and every library its linker used. It was checked again for the shipped build (fork commit `f971ed14`,
19 October 2026), which compiles the same third-party code. The repository, commit and SHA-256 of each text are in
`packaging/licenses/OptiScaler-third-party/PROVENANCE.json` in the source.

**FreeType credit:** Portions of this software are copyright © 2024 The FreeType Project (www.freetype.org). All
rights reserved.

| Component | Where in the OptiScaler source | Licence | Text in this folder | Copyright |
| --- | --- | --- | --- | --- |
| FreeType 2.13.3 | `external/freetype` (headers and the static library `freetype.lib`, which includes the BDF and PCF drivers and the gzip module) | FreeType License (FTL) | `FreeType-FTL.txt`, `FreeType-LICENSE.txt`, `FreeType-BDF-README.txt`, `FreeType-PCF-README.txt` | © 1996-2024 David Turner, Robert Wilhelm and Werner Lemberg; BDF driver © 2000 Computing Research Labs, New Mexico State University, © 2001-2002, 2011 Francesco Zappa Nardelli; PCF driver © 2000 Francesco Zappa Nardelli |
| zlib 1.3 (inside FreeType's gzip module) | `external/freetype/freetype.lib` | zlib licence (no notice needed in binary form) | — | © 1995-2023 Jean-loup Gailly and Mark Adler |
| Microsoft Detours 4.0.1 | `OptiScaler/include/detours`, `OptiScaler/library/detours/detours.lib` | MIT | `Detours.txt` | © Microsoft Corporation |
| Dear ImGui 1.92.0 (docking) | `OptiScaler/include/imgui`, with its Win32, DirectX 11/12, Vulkan and UWP backends and the FreeType font builder | MIT | `Dear-ImGui.txt` | © 2014-2025 Omar Cornut |
| stb_rect_pack 1.01, stb_textedit 1.14 (part of Dear ImGui) | `OptiScaler/include/imgui/imstb_rectpack.h`, `imstb_textedit.h` | public domain, or MIT (stated at the end of each file) | — | Sean Barrett |
| ImGuiNotify 0.0.3 | `OptiScaler/include/imgui/ImGuiNotify.hpp` | MIT | `ImGuiNotify.txt` | © 2021 Patrick, © 2024 TyomaVader |
| spdlog 1.15.1 | `external/spdlog` | MIT | `spdlog.txt` | © 2016 Gabi Melman |
| JSON for Modern C++ 3.12.0 | `external/nlohmann/json.hpp` | MIT | `nlohmann-json.txt` | © 2013-2025 Niels Lohmann |
| SimpleIni | `external/simpleini` | MIT | `simpleini.txt` | © 2006-2024 Brodie Thiesfield |
| magic_enum 0.9.7 | `external/magic_enum` | MIT | `magic_enum.txt` | © 2019-2024 Daniil Goncharov |
| unordered_dense 4.5.0 | `external/unordered_dense` | MIT | `unordered_dense.txt` | © 2022 Martin Leitner-Ankerl |
| flag-set-cpp | `OptiScaler/include/flag-set-cpp` | MIT | `flag-set-cpp.txt` | © 2019 Arnaud Kapp (Xaqq), Barry Revzin, Mart Sõmermaa |
| SHA-1 (`sha1.hpp`) | `OptiScaler/include/sha1` | public domain | — | — |
| AMD FidelityFX Super Resolution 2.2 | `OptiScaler/include/fsr2`, `OptiScaler/library/fsr2` (static libraries) | MIT | `AMD-FidelityFX-FSR2.2.txt` | © 2022-2023 Advanced Micro Devices, Inc. |
| AMD FidelityFX Super Resolution 2.1.2 | `OptiScaler/include/fsr2_212`, `OptiScaler/library/fsr2_212` (static libraries) | MIT | `AMD-FidelityFX-FSR2.1.txt` | © 2022 Advanced Micro Devices, Inc. |
| AMD FidelityFX SDK 1.0 (FSR 3) | `OptiScaler/include/fsr3`, `OptiScaler/include/d3dx/d3dx12.h` | MIT | `AMD-FidelityFX-SDK-1.0.txt` | © 2023 Advanced Micro Devices, Inc. |
| AMD FidelityFX SDK 1.1 (FSR 3.1) and the FidelityFX API | `OptiScaler/include/fsr31`, `OptiScaler/library/fsr31` (static libraries), `external/FidelityFX-SDK` | MIT | `AMD-FidelityFX-SDK-1.1.txt` | © 2024 Advanced Micro Devices, Inc. |
| AMD FidelityFX Super Resolution 1 | `OptiScaler/shaders/output_scaling/fsr1` (compiled into shaders) | MIT | `AMD-FidelityFX-FSR1.txt` | © 2021 Advanced Micro Devices, Inc. |
| AMD Anti-Lag 2 SDK | `external/AntiLag2-SDK` | MIT | `AMD-Anti-Lag-2-SDK.txt` | © 2024 Advanced Micro Devices, Inc. |
| AMD device_info | `OptiScaler/include/device_info` | MIT | `AMD-device_info.txt` | © Advanced Micro Devices, Inc. |
| Microsoft DirectX Graphics Samples | the bicubic upscaling shaders in `OptiScaler/shaders/output_scaling` (MiniEngine), `OptiScaler/include/d3dx/d3dx12.h` | MIT | `Microsoft-DirectX-Graphics-Samples.txt` | © Microsoft |
| NVIDIA Streamline 2.11.1 | `external/streamline` (headers), `OptiScaler/include/sl.param` | MIT | `NVIDIA-Streamline-2.txt` | © 2022-2025 NVIDIA Corporation |
| NVIDIA Streamline 1 (headers) | `external/streamline1` | MIT | `NVIDIA-Streamline-1.txt` | © 2022 NVIDIA Corporation |
| NVIDIA NVAPI R595 (headers) | `external/nvapi` | MIT | `NVIDIA-NVAPI.txt` | © 2019-2026 NVIDIA Corporation & affiliates |
| Vulkan-Headers 1.4.310 | `external/vulkan`; `OptiScaler/library/vulkan/vulkan-1.lib` (import library of the Vulkan loader) | Apache-2.0 (the C++ headers are Apache-2.0 or MIT; Apache-2.0 is used here) | `Khronos-Vulkan-Headers.txt`, `Apache-2.0.txt` | © 2014-2025 The Khronos Group Inc. |
| LatencyFleX (header) | `external/latencyflex/latencyflex.h` | Apache-2.0 | `Apache-2.0.txt` | © 2021 Tatsuyuki Ishi |
| Intel XeSS, XeLL and XeSS Frame Generation SDK headers | `external/xess/inc` | Intel Simplified Software License | `licenses/Intel-XeSS.txt` (the same text as in that submodule) | © 2021-2024 Intel Corporation |
| NVIDIA NGX (DLSS SDK) headers | `external/nvngx_dlss_sdk` | NVIDIA's DLSS SDK licence (NVIDIA RTX SDKs License, https://github.com/NVIDIA/DLSS) | `NVIDIA-DLSS-SDK.txt` (the text of DLSS SDK 310.7.0; the headers come from an earlier SDK release) | © 2018-2023 NVIDIA Corporation & affiliates |

**Prebuilt libraries.** Some of the code above reaches the DLL as static libraries that the OptiScaler source carries
as binaries, as upstream OptiScaler does: `detours.lib` (Microsoft Detours 4.0.1, source at
https://github.com/microsoft/Detours), `freetype.lib` (FreeType 2.13.3 with zlib 1.3, source at
https://github.com/freetype/freetype, tag `VER-2-13-3`), the FSR 2.2 and FSR 2.1.2 libraries in `OptiScaler/library/fsr2`
and `fsr2_212` (source at https://github.com/GPUOpen-Effects/FidelityFX-FSR2), the FSR 3.1 libraries in
`OptiScaler/library/fsr31` (source at https://github.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK, release 1.1) and
`vulkan-1.lib`, the import library of the Vulkan loader (https://github.com/KhronosGroup/Vulkan-Loader). The OptiScaler
source does not record which exact commit each binary was built from; the versions are the ones the headers beside
them name.

In the OptiScaler source but not compiled into this DLL: fmt (spdlog uses `std::format` here), stb_truetype (FreeType
builds the fonts), `external/FidelityFX-SDK-v2`, `external/directx_agility_sdk`, `OptiScaler/library/d3dx/d3dx11.lib` and
the import libraries in `external/xess/lib`.

From the build toolchain, not from the OptiScaler source: the Microsoft C/C++ runtime and the Windows SDK import
libraries (the DLL uses the shared runtime) and the parts of Microsoft's C++ standard library that are compiled in
(Apache-2.0 with the LLVM exception, which needs no notice in object code).
