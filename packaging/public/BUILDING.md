# Building FreeFG from source

The release build reproduces the shipped binaries **byte for byte** on the pinned toolchain. Each binary is built
twice per run, and both builds must match. The result is compared with the reference hashes in
`release/inputs.lock.json`:

| Output | Built by | sha256 |
| --- | --- | --- |
| `libxess_fg.dll` (the proxy) | `release/build_proxy.py` | `3bb43859ccff3a98786dd3c931e430523dbd05676f8d721515973ea73f935410` |
| `libxefg_wave.so` (the pacing layer) | `release/build_layer.py` | `d5f9800d0f52903f16b5a71af42599d89640bc41fc0bfc4dad66248f30ac3271` |

A different compiler, Wine or glibc version normally changes the bytes. The build then warns, and the result is a new
build that needs its own testing.

## Toolchain

Linux on x86-64 with:

| Tool | Version of the reference build | Used for |
| --- | --- | --- |
| Python | 3.11 or newer (reference: 3.14.7) | all build scripts |
| clang and lld | 22.1.8 | the proxy (`--target=x86_64-w64-windows-gnu`) |
| Wine | 11.16: its headers (`/usr/include/wine`) and x86-64 Windows import libraries (`/usr/lib/wine/x86_64-windows`) | compiling the proxy; the loader check |
| GCC | 16.2.1, with AddressSanitizer, UBSan and ThreadSanitizer | the pacing layer and its unit tests |
| glibc, binutils | 2.44, 2.47 | the pacing layer |
| vulkan-headers | 1.4.357 | the pacing layer |
| DirectX Shader Compiler | Microsoft's v1.9.2607 release for Linux to rebuild the shader profile byte for byte (`release/build_profile.py`); for the static package check alone, v1.9.2609 or newer also works | the shader profile; the static package check (`check_intel_free.py` disassembles DXIL with it) |
| `bsdtar` (libarchive) | any | the installer's offline test |

`python3 release/config.py --help` lists every location setting and its environment variable (`XEMFG_BUILD`,
`XEMFG_CACHE`, `XEMFG_CLANG`, `XEMFG_GCC`, `XEMFG_WINE_INCLUDE`, `XEMFG_WINE_LIB`, `XEMFG_DXC`, `XEMFG_PROFILE`, …).

**Exact reproduction:** the CI workflow (`.github/workflows/ci.yml`, helpers in `release/ci/`) builds in an official
Arch Linux container image pinned by digest. It points pacman at the Arch Linux Archive snapshot of 2026-09-03 and checks
every output-relevant package by file SHA-256 (`release/ci/ci.lock.json`). On that toolchain a hash that differs from
the lock fails the job. `python3 release/ci/toolchain.py --help` explains the setup; you can run the same steps in a
local container.
In a container that runs as another user than the one owning a bind-mounted tree (root over your own checkout, as in
the CI job), git refuses the tree ("detected dubious ownership") and `release/assemble.py` cannot read the commit it
records; mark the mount as safe first (`git config --system --add safe.directory <path in the container>`), as the
workflow does.

## Inputs that are downloaded

`release/fetch.py` downloads the pinned public inputs listed under `fetch` in `release/inputs.lock.json`, file by file
at the locked commit. It checks each file's SHA-256 and keeps them in `XEMFG_CACHE` (default `build/cache`). The
builds call it on demand. It never executes anything it downloads.

| Group | Source | Commit | What | Used for |
| --- | --- | --- | --- | --- |
| `intel-xess` | `https://raw.githubusercontent.com/intel/xess/{commit}/{path}` | `de0fb9c1c510661c571164e1418ceca8101dab69` | `inc/xess_fg/*.h`, `inc/xell/*.h`, `LICENSE.txt`, `third-party-programs.txt` | API types for the proxy; licence texts for the package |
| `intel-xess-runtime` | same repository and commit | `de0fb9c1c510661c571164e1418ceca8101dab69` | `bin/libxess_fg.dll` | the proxy's export table, size and hash are checked against it; it is never copied into an output |
| `optiscaler-license` | `https://raw.githubusercontent.com/optiscaler/OptiScaler/{commit}/{path}` | `92337ebfbf07d533eabe3731fd8de1bb19437aea` | `LICENSE` | the package's `licenses/OptiScaler.txt` |
| `fsr4-notices` | `https://raw.githubusercontent.com/daniel-h-0/bc250-fsr4-fork/{commit}/{path}` | `f37421e7befb11a3a50f6f385332a8d1e02e7190` | `dll/notices/*` | the package's `licenses/fsr4/` |
| `minhook` | `https://raw.githubusercontent.com/TsudaKageyu/minhook/{commit}/{path}` | `c3fcafdc10146beb5919319d0683e44e3c30d537` | sources and `LICENSE.txt` | not compiled into FreeFG; fetched because `fetch.py` without arguments fetches every group |

Intel's XeFG headers carry Intel's proprietary notice. They are fetched at build time and must never be committed to
this tree or shipped. The installer's own downloads (Intel's runtime, FSR 4, OptiScaler's support files, the DLSS
helper) are pinned separately in `packaging/dependencies.json` ([PRIVACY.md](PRIVACY.md)).

## Build

From a checkout of <https://github.com/daniel-h-0/freefg>:

```sh
python3 release/ci/toolchain.py dxc --dest build/dxc          # Microsoft's DXC v1.9.2607 (below), downloaded and checked
export XEMFG_DXC=build/dxc                   # the static check's constant scan in assemble.py and check_intel_free.py
python3 release/fetch.py                     # pinned public inputs (also fetched on demand)
python3 release/build_layer.py               # unit tests under ASan/UBSan and TSan, then libxefg_wave.so twice
python3 release/build_proxy.py               # libxess_fg.dll twice, plus its ABI checks
python3 release/check_proxy_wine.py          # the proxy under Wine's real loader, CPU only (needs wine)
python3 release/assemble.py --variant intel-free-2x --no-source-companion
python3 release/check_intel_free.py check build/package-intel-free-2x/<package name>   # result "pass", exit 0
```

`assemble.py` and `check_intel_free.py` need DXC (`XEMFG_DXC`, the extracted release of [The shader
profile](#the-shader-profile), the one CI uses): the static check disassembles every DXIL container to scan its constant
arrays for Intel's warp weight tables, and without DXC it fails. `check_intel_free.py check --skip-constant-scan` runs
without it but leaves that scan out (its report records it); `assemble.py` has no such switch.

Outputs go to `build/` (`XEMFG_BUILD`), which git ignores. What each step checks:

- **`build_layer.py`** builds and runs the layer's unit tests (pacer, wave layer, concurrent presents) under
  AddressSanitizer/UBSan and ThreadSanitizer. Any sanitizer report fails the build. Then it builds the layer twice and
  writes `build/layer/build.json`, with no absolute paths.
- **`build_proxy.py`** checks its inputs against the lock and prepares the shader profile. It generates the export
  definitions from Intel's DLL: 57 exports at their ordinals, 5 wrapped and 52 forwarded to `bc250_xefg_original`. It
  compiles `src/game/mfg_proxy.c` twice and requires identical output. Then it checks the result: Intel's export table
  reproduced ordinal by ordinal, imports only from `kernel32.dll` and `ucrtbase.dll`, and no reference to any other
  loader. It writes `build/addon-intel-free-2x/build.json`.
- **`check_proxy_wine.py`** runs a small test program under Wine in a private prefix, with no GPU and no display, in
  three layouts. With the pinned runtime, a forwarded call reaches Intel's DLL and a wrapped one reaches Intel's code.
  With a runtime altered by one byte, and with no runtime, the wrapped call refuses without loading anything.
- **`assemble.py`** runs the installer's unit tests first. It refuses stale builds, files the package must not carry
  (Intel's runtime, the FSR 4 DLL) and, when archiving, documents that still carry the draft marker. It writes
  `build/package-intel-free-2x/<name>/` with `manifest.json` (every file's SHA-256, the git commit, and which shipped
  files differ from it), then runs the static check and removes the package if that check fails.
- **`check_intel_free.py check`** reads every file of the package. It fails on a file whose SHA-256 is that of an Intel
  file or of one of the shader programs of Intel's runtime, on any DXIL that is not one of the profile's own shaders (also
  inside other files), on DXIL of shader model 6.4, and on any copy of Intel's warp weight tables. Intel's material is
  known to the check only by hashes and checksums (`release/intel_material.json`). No Intel bytes are in the tree.
  `release/ci/check_controls.py` proves each detector on synthetic material.

**Installer tests and an offline install:** `python3 release/ci/installer_tests.py` runs the installer's unit tests on
their own. `python3 release/smoke_install.py --variant intel-free-2x --deps <dir>` installs the assembled package into
a throwaway game folder and restores it, offline. `<dir>` holds the installer's prepared downloads, for example
`~/.cache/bc250-xefg-testers/payload` after one Setup run.

## The shader profile

The 28 shaders and 9 tables of `payload/BC250-XeFG/shaders/` are this project's own. The tree holds the compiled
profile in `release/profile/` (33 shaders and 9 tables and markers: the 2× package leaves out five multi-frame
shaders) and the HLSL it is compiled from in `src/kernels/`. Each file is pinned by SHA-256 in
`release/inputs.lock.json`, with origin `own`. The builds read `release/profile/` unless `XEMFG_PROFILE` names another
directory.

To rebuild every shader from its HLSL and compare the bytes, extract Microsoft's DirectX Shader Compiler release
v1.9.2607 for Linux (`linux_dxc_2026_07_29.x86_x64.tar.gz`, SHA-256
`55665c87824051ed4774ff3280a79ccbbb7d39243b9736ca5e98222134112d54`) and run:

```sh
XEMFG_DXC=/path/to/linux_dxc_2026_07_29.x86_x64 python3 release/build_profile.py check   # "result": "pass", 33 byte-identical
```

`release/profile/ORIGIN.md` describes each shader's recipe (`release/profile/origin.json`). Another DXC version
compiles the same sources to different bytes.

## What a public build cannot produce yet

- **The OptiScaler build** (`opti/OptiScaler.dll`, GPL-3.0, sha256 `244eca5c0927dff802d7f2a506afe9e7776bcdc489bdc3acdf56e9c92f7b437d`).
  The package ships this DLL. Its source is the OptiScaler fork at <https://github.com/daniel-h-0/OptiScaler>, tag
  `bc250-a793287` (see [NOTICE.md](NOTICE.md)). The release tooling does not download the built DLL, so CI assembles
  the package without it. That is the only component it may leave out.
- **The source companion** (`assemble.py` without `--no-source-companion`) reads a git checkout of the OptiScaler fork
  (`XEMFG_OPTISCALER_SOURCE`).

## Reproducibility notes

- Build records (`build.json`) and the package manifest hold no absolute paths. The builds have been checked to give
  the same bytes from a tree exported to another directory (`release/export_tree.py --public DIR`).
- The proxy build warns when the Wine headers or import libraries differ from the ones recorded in the lock (by
  count and digest). The layer build does the same for the system headers.
- `--offline` makes every tool use only the download cache.
