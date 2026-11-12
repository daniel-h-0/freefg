# Building

The public tree builds the XeFG proxy, the Vulkan pacing layer, the shader profile and the installer. The bundled
OptiScaler DLL has its own pinned source and build route ([Outside this tree](#outside-this-tree)).

## Outputs

| Output | Built by | Reference sha256 |
| --- | --- | --- |
| `libxess_fg.dll` (the proxy) | `release/build_proxy.py` | `6489938d63e7059d1b669681881cc11e93072bec921844868926386131b03ca8` |
| `libxefg_wave.so` (the pacing layer) | `release/build_layer.py` | `1f691dfd018f7d3d062704b9639e5ed7bfbcfe1e71d92c2299e08153b9f666b6` |

Each script builds twice and requires identical outputs. It then compares the result with `release/inputs.lock.json`.
`--no-reference-check` skips only that final comparison. A different hash is a different build and needs testing before
distribution.

## Toolchain

Reference build, x86-64 Linux:

| Tool | Pinned version | Purpose |
| --- | --- | --- |
| Python | 3.14.7 | Build scripts and archive extraction. The scripts require 3.11.4+. Before 3.14, `toolchain.py` also needs the `zstd` program. |
| clang / lld | 22.1.8 | Windows proxy DLL |
| Wine | 11.16 | Headers and import libraries; CPU-only loader tests |
| GCC | 16.2.1 | Pacing layer and sanitizer tests |
| glibc / binutils | 2.44 / 2.47 | Pacing layer |
| Vulkan-Headers | 1.4.357 | Pacing layer |
| DXC | v1.9.2607 for shader reproduction; v1.9.2609 for static scans | [DXC details](#dxc) |
| git / bsdtar | Available on the host | Source records / installer tests |

Output and cache locations default to `build/` and `build/cache`. `XEMFG_BUILD` and `XEMFG_CACHE` override them.
`python3 release/config.py --help` lists the shared options.

### Pinned toolchain

`release/toolchain.py` verifies Arch package hashes from `release/ci/ci.lock.json` and extracts tools and headers into
an isolated directory without root. It takes the packages from `XEMFG_PACKAGES`, pacman's cache or the Arch Linux
Archive.

```sh
python3 release/toolchain.py prepare
export XEMFG_TOOLCHAIN=pinned
```

`XEMFG_TOOLCHAIN=pinned` also prepares the toolchain on first use. Builds then require the pinned compiler versions and
header digests. Without that variable they use host tools and warn on mismatches. Host Python, the Wine that runs the
tests and some compiler support libraries remain host-provided. The pinned CI container is the reference environment.

## Downloaded inputs

`release/fetch.py` retrieves the lock's `fetch` groups from pinned GitHub commits, verifies SHA-256 and caches them. It
does not execute downloaded files. With `--offline`, the build tools use cached inputs only.

| Group | Repository | Commit | Files | Used for |
| --- | --- | --- | --- | --- |
| `intel-xess` | `intel/xess` | `de0fb9c1c510661c571164e1418ceca8101dab69` | `inc/xess_fg/*.h`, `inc/xell/*.h`, `LICENSE.txt`, `third-party-programs.txt` | API types for the proxy; licence texts for the package |
| `intel-xess-runtime` | `intel/xess` | `de0fb9c1c510661c571164e1418ceca8101dab69` | `bin/libxess_fg.dll` | The proxy's export table, and the size and hash that the proxy checks before loading the runtime. Never copied into an output. |
| `optiscaler-license` | `optiscaler/OptiScaler` | `92337ebfbf07d533eabe3731fd8de1bb19437aea` | `LICENSE` | The package's `licenses/OptiScaler.txt` |
| `optiscaler-fork` | `daniel-h-0/OptiScaler`, release `bc250-4d0c0b9` | `13e9ddabf3804db37de617ce1d667c1ac9a8910e` (tag) | `OptiScaler.dll`, `OptiScaler.ini` | The package's `opti/`. The fork has its [own build](#outside-this-tree). |
| `fsr4-notices` | `daniel-h-0/bc250-fsr4-fork` | `b2ab949477b4d2745babae146393db5537d87fcb` | `dll/notices/*` | The package's `licenses/fsr4/` |
| `minhook` | `TsudaKageyu/minhook` | `c3fcafdc10146beb5919319d0683e44e3c30d537` | sources, `LICENSE.txt` | Nothing in FreeFG. Fetched because `fetch.py` without arguments fetches every group. |

Intel's XeFG headers carry Intel's proprietary notice. Fetch them at build time. Do not commit or ship them. Installer
downloads use the separate `packaging/dependencies.json` pins ([PRIVACY.md](PRIVACY.md)).

## Build and check

From a checkout of <https://github.com/daniel-h-0/freefg>:

```sh
python3 release/toolchain.py prepare
python3 release/ci/toolchain.py dxc --dest build/dxc
export XEMFG_DXC=build/dxc
export XEMFG_TOOLCHAIN=pinned
python3 release/fetch.py
python3 release/build_layer.py
python3 release/build_proxy.py
python3 release/check_proxy_wine.py
python3 release/assemble.py --variant intel-free-mfg --no-source-companion
python3 release/check_intel_free.py check build/package-intel-free-mfg/<name>
```

`fetch.py` also downloads the OptiScaler fork's release files, which assembly verifies by hash.
`release/ci/assemble_ci.py --variant intel-free-mfg` assembles the CI package. It requires a clean checkout and matching
reference outputs. Neither route establishes GPU or game qualification.

### Step checks

| Step | Checks and record |
| --- | --- |
| `build_layer.py` | Pacer, wave-layer and concurrent-present tests under ASan/UBSan and TSan. Two matching builds. No glibc symbol version newer than 2.34, the manifest's `present_pacing.glibc`, which System Check compares with the host's. Record: `build/layer/build.json`. |
| `build_proxy.py` | Pinned inputs and profile manifest. Two matching DLLs. Intel's 57 exports in the split that [ARCHITECTURE.md](ARCHITECTURE.md#exports) lists, plus 4 own exports. Imports limited to `kernel32.dll` and `ucrtbase.dll`. Record: `build/addon-intel-free-mfg/build.json`. |
| `check_proxy_wine.py` | Own and forwarded entries reach the pinned runtime, also from a subfolder and beside a game's own copy of it. Missing and altered runtimes and a second copy loaded elsewhere are refused. Callers are preserved with stand-in hooks. Coexistence bookkeeping. Copied-history invalidation and abandoned or submitted recordings. Runs in a private Wine prefix without GPU or display. |
| `assemble.py` | Installer tests, build freshness, allowed package contents, manifest hashes and static material scan. `--archive` also requires a passed qualification receipt and completed public documents. |
| `check_intel_free.py check` | Known Intel files and shaders, unrecognised embedded DXIL, shader model 6.4 and known warp-weight constants. Pinned OptiScaler shaders are recognised separately. Synthetic detector controls are in `release/ci/check_controls.py`. |

### DXC

The static material check needs DXC to inspect constant arrays. CI uses v1.9.2609. `check --skip-constant-scan` omits
that check and records the omission. Assembly does not allow the omission. Rebuilding the shader profile byte for byte
requires v1.9.2607.

### Installer tests

```sh
python3 release/ci/installer_tests.py --fail-on-skip
python3 release/smoke_install.py --variant intel-free-mfg --deps /path/to/prepared/payload
```

The second command is a smoke test without downloads. It installs into a throwaway game folder and restores it exactly.
The dependency directory can be the installer's `~/.cache/bc250-xefg-testers/payload` after preparation.

## The shader profile

The shipped profile has **83 shaders and 10 tables/markers** ([composition](ARCHITECTURE.md#the-shader-profile)).
`release/profile/` supplies 33 base shaders. `release/profile-mfg/` replaces 12 and adds 50 shaders plus the scaling
capability marker.

The HLSL is under `src/kernels/`, `src/frame_resample.hlsl` and `src/frame_upscale_filters.hlsl`. The compile recipes
are in the two `origin.json` files. The EASU filter uses the pinned MIT headers under `vendor/fsr1/`.

To rebuild, extract Microsoft's Linux DXC v1.9.2607 archive, `linux_dxc_2026_07_29.x86_x64.tar.gz`, SHA-256
`55665c87824051ed4774ff3280a79ccbbb7d39243b9736ca5e98222134112d54`, then run:

```sh
XEMFG_DXC=/path/to/linux_dxc_2026_07_29.x86_x64 python3 release/build_profile.py check
```

Expected: 33 byte-identical base shaders and 62 in `variant_profiles`. `--no-rebuild` checks the stored files and does
not test compiler reproducibility.
[Profile provenance and composition](https://github.com/daniel-h-0/freefg/blob/main/release/profile/ORIGIN.md).

## CI

`.github/workflows/ci.yml` runs on pushes to main, pull requests and manual dispatch. It uses an Arch image pinned by
digest, the 2026-09-03 package snapshot and packages pinned by file hash. It runs:

- release and document checks
- installer and sanitizer tests
- proxy loader tests
- package and material checks
- a strict public export

A reference-output mismatch fails the pinned job. Artifacts contain reports and build records and no binaries.

CI skips the DXC v1.9.2607 shader rebuild and the private-material detector self-test. Synthetic controls cover the
static detectors instead. `.github/workflows/pins.yml` checks download pins weekly. It also runs an informational build
with current Arch packages, where output-hash differences are warnings.

A container that runs as a different user from a bind-mounted checkout's owner may need the workflow's safe-directory
setting before git can read the commit:

```sh
git config --system --add safe.directory <path-in-the-container>
```

## Outside this tree

### OptiScaler fork

| Item | Value |
| --- | --- |
| DLL SHA-256 | `22052eb2b4f9b936f9c6ee2bfa161a3dc9cdb6799f801c1999595fc765d579c3` |
| Source commit | `4d0c0b9798e07332a0a8a86a7dfa5b0388732957` |
| Upstream base | `7479cb294cd66d4d02c2a452f6f6294ade6a11ff` |
| Release tag commit | `13e9ddabf3804db37de617ce1d667c1ac9a8910e`. It adds only the `FORK.md` record of that build. |

`release/fetch.py` downloads this DLL and its matching `OptiScaler.ini` from the
[fork release](https://github.com/daniel-h-0/OptiScaler/releases/tag/bc250-4d0c0b9), which also has the recursive source
archive. The fork's `FORK.md` and `tools/bc250-build.py` describe the separate build. The source companion and the
locked recursive source archive identify the complete corresponding source.

### Source companion

Normal assembly builds the source companion from the fork's git checkout, named by `XEMFG_OPTISCALER_SOURCE` or
`--optiscaler-source`. Use `--no-source-companion` only for a local build that does not distribute the complete source
companion.

### GPU measurements

The public tree reproduces binaries and CPU checks. The SDK scene and game benchmark harnesses are separate research
tooling. [MEASUREMENTS.md](MEASUREMENTS.md) reports their results and limits.

## Reproducibility

Build records and manifests omit absolute host paths. The pinned proxy, layer and shader builds are checked byte for
byte. A package records its source commit, payload hashes and qualification receipt. Use those to identify a build. A
matching version label does not prove identical contents.
