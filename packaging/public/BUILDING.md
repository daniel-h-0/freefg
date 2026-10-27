# Building FreeFG from source

The public tree builds the XeFG proxy, Vulkan pacing layer, shader profile and installer. The bundled OptiScaler DLL
has its own pinned source and build route.

## Outputs

| Output | Built by | Reference sha256 |
| --- | --- | --- |
| `libxess_fg.dll` (the proxy) | `release/build_proxy.py` | `f78d4840ac6984a5e078e7422982da2abe287fbd05ac33458c13e8682dd96a26` |
| `libxefg_wave.so` (the pacing layer) | `release/build_layer.py` | `5de86d968c8adbfb42cf3d56bd020a0ba82e92ca31e9dcf4e319cbc479963687` |

The proxy and layer scripts build twice and require identical outputs. They also compare against
`release/inputs.lock.json`; `--no-reference-check` skips that final comparison, not the other checks. A different hash
is a different build and needs testing before distribution.

## Toolchain

Reference build, x86-64 Linux:

| Tool | Pinned version | Purpose |
| --- | --- | --- |
| Python | 3.14.7; build scripts require 3.11.4+ | Build scripts and archive extraction |
| clang / lld | 22.1.8 | Windows proxy DLL |
| Wine | 11.16 | Headers/import libraries; CPU-only loader tests |
| GCC | 16.2.1 | Pacing layer and sanitizer tests |
| glibc / binutils | 2.44 / 2.47 | Pacing layer |
| Vulkan-Headers | 1.4.357 | Pacing layer |
| DXC | v1.9.2607 for shader reproduction; v1.9.2609 for static scans | [DXC details](#dxc) |
| git / bsdtar | Available on the host | Source records / installer tests |

Output and cache locations default to `build/` and `build/cache`. `XEMFG_BUILD` and `XEMFG_CACHE` override them;
`python3 release/config.py --help` lists the shared options.

### The pinned toolchain

`release/toolchain.py` verifies Arch package hashes from `release/ci/ci.lock.json` and extracts tools and headers into
an isolated directory without root. It uses `XEMFG_PACKAGES`, pacman's cache or the Arch Linux Archive.

```sh
python3 release/toolchain.py prepare
export XEMFG_TOOLCHAIN=pinned
```

`XEMFG_TOOLCHAIN=pinned` also prepares the toolchain on first use if needed. Builds then require the pinned compiler
versions and header digests. Without that variable they use host tools and warn on mismatches. Host Python, the Wine
used to run tests, and some compiler support libraries remain host-provided; the pinned CI container is the reference
environment.

## Downloaded inputs

`release/fetch.py` retrieves the lock's `fetch` groups from pinned GitHub commits, verifies SHA-256 and caches them.
It does not execute downloaded files. The build tools accept `--offline` to use cached inputs only.

| Group | Repository | Commit | Files | Used for |
| --- | --- | --- | --- | --- |
| `intel-xess` | `intel/xess` | `de0fb9c1c510661c571164e1418ceca8101dab69` | `inc/xess_fg/*.h`, `inc/xell/*.h`, `LICENSE.txt`, `third-party-programs.txt` | API types for the proxy; licence texts for the package |
| `intel-xess-runtime` | `intel/xess` | `de0fb9c1c510661c571164e1418ceca8101dab69` | `bin/libxess_fg.dll` | the proxy's export table, and the size and hash the proxy checks before loading the runtime; never copied into an output |
| `optiscaler-license` | `optiscaler/OptiScaler` | `92337ebfbf07d533eabe3731fd8de1bb19437aea` | `LICENSE` | the package's `licenses/OptiScaler.txt` |
| `fsr4-notices` | `daniel-h-0/bc250-fsr4-fork` | `b2ab949477b4d2745babae146393db5537d87fcb` | `dll/notices/*` | the package's `licenses/fsr4/` |
| `minhook` | `TsudaKageyu/minhook` | `c3fcafdc10146beb5919319d0683e44e3c30d537` | sources, `LICENSE.txt` | nothing in FreeFG; fetched because `fetch.py` without arguments fetches every group |

Intel's XeFG headers carry Intel's proprietary notice: fetch them at build time; do not commit or ship them.
Installer downloads use the separate `packaging/dependencies.json` pins ([PRIVACY.md](PRIVACY.md)).

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
export XEMFG_OPTISCALER=/path/to/folder  # contains the pinned OptiScaler.dll
python3 release/assemble.py --variant intel-free-mfg --no-source-companion
python3 release/check_intel_free.py check build/package-intel-free-mfg/<name>
```

Take `opti/OptiScaler.dll` from the release archive; assembly verifies its hash. For a CI-style package without that
DLL, use `release/ci/assemble_ci.py --variant intel-free-mfg`. It requires a clean checkout and matching reference
outputs. Neither route establishes GPU/game qualification.

### What each step checks

| Step | Checks and record |
| --- | --- |
| `build_layer.py` | Pacer, wave-layer and concurrent-present tests under ASan/UBSan and TSan; two matching builds; `build/layer/build.json`. |
| `build_proxy.py` | Pinned inputs, profile manifest, two matching DLLs, 57 Intel exports (8 wrapped/49 forwarded) plus 4 own exports, and imports limited to `kernel32.dll`/`ucrtbase.dll`; `build/addon-intel-free-mfg/build.json`. |
| `check_proxy_wine.py` | Forwarding to the pinned runtime; refusal of missing/altered runtimes; caller preservation with stand-in hooks; coexistence bookkeeping. Private Wine prefix, no GPU/display. |
| `assemble.py` | Installer tests, build freshness, allowed package contents, manifest hashes and static material scan. `--archive` also requires a passed qualification receipt and completed public documents. |
| `check_intel_free.py check` | Known Intel files/shaders, unrecognised embedded DXIL, shader model 6.4 and known warp-weight constants. Pinned OptiScaler shaders are recognised separately. Synthetic detector controls are in `release/ci/check_controls.py`. |

### DXC

The static material check needs DXC to inspect constant arrays. CI uses v1.9.2609. `check --skip-constant-scan` omits
that check and records the omission; assembly does not allow it. Rebuilding the shader profile byte for byte requires
v1.9.2607.

### Installer tests and an offline install

```sh
python3 release/ci/installer_tests.py --fail-on-skip
python3 release/smoke_install.py --variant intel-free-mfg --deps /path/to/prepared/payload
```

The smoke test installs into a throwaway game folder and Restores it exactly. The dependency directory can be the
installer's `~/.cache/bc250-xefg-testers/payload` after preparation.

## The shader profile

The shipped profile has **83 shaders and 10 tables/markers**. `release/profile/` supplies 33 base shaders;
`release/profile-mfg/` replaces 12 and adds 50 shaders plus the scaling capability marker. Additions comprise seven
F(4×4) alternatives, seven FP16 alternatives, five comparison kernels, 25 bounded convolution forms and six scaling
filters. HLSL is under `src/kernels/`, `src/frame_resample.hlsl` and `src/frame_upscale_filters.hlsl`; compile recipes
are in the two `origin.json` files. The EASU filter uses the pinned MIT headers under `vendor/fsr1/`.

Extract Microsoft's Linux DXC v1.9.2607 archive, `linux_dxc_2026_07_29.x86_x64.tar.gz`, SHA-256
`55665c87824051ed4774ff3280a79ccbbb7d39243b9736ca5e98222134112d54`, then run:

```sh
XEMFG_DXC=/path/to/linux_dxc_2026_07_29.x86_x64 python3 release/build_profile.py check
```

Expected: 33 byte-identical base shaders and 62 in `variant_profiles`. `--no-rebuild` checks stored files, not compiler
reproducibility. [Profile provenance and composition](../../release/profile/ORIGIN.md).

## CI

`.github/workflows/ci.yml` runs on main pushes, pull requests and manual dispatch. It uses an Arch image pinned by
digest, the 2026-09-03 package snapshot, and packages pinned by file hash. It runs release/document checks, installer
and sanitizer tests, proxy loader tests, package/material checks and strict public export. Reference-output mismatches
fail the pinned job. Artifacts contain reports and build records, not binaries.

CI skips the DXC v1.9.2607 shader rebuild and the private-material detector self-test; synthetic controls cover the
static detectors instead. `.github/workflows/pins.yml` checks download pins weekly and runs an informational build
with current Arch packages, where output-hash differences are warnings.

A container running as a different user from a bind-mounted checkout's owner may need the workflow's safe-directory
setting before git can read the commit:

```sh
git config --system --add safe.directory <path-in-the-container>
```

## What this tree does not build

- **OptiScaler:** DLL SHA-256 `b3602882c7e194af523e50861a222d63c0c56b013cff4bfb5b187ca4f6666656`, built from
  `03db4f8692878e65748769ebe583c053cae96360`. The [fork release](https://github.com/daniel-h-0/OptiScaler/releases/tag/bc250-03db4f8)
  supplies the DLL and matching source. Its `FORK.md` and `tools/bc250-build.py` describe the separate build.
  OptiScaler is the only component CI may omit from its test package.
- **Source companion without its inputs:** normal assembly needs a fork checkout named by `XEMFG_OPTISCALER_SOURCE`.
  Use `--no-source-companion` only for a local build that does not distribute the complete source companion.
- **GPU measurements:** the public tree reproduces binaries and CPU checks. The SDK scene and game benchmark harnesses
  are separate research tooling; [MEASUREMENTS.md](MEASUREMENTS.md) reports their results and limits.

## Reproducibility

Build records and manifests omit absolute host paths. The pinned proxy/layer and shader builds are checked byte for
byte. A package records its source commit, payload hashes and qualification receipt; use those to identify what was
built, rather than treating a matching version label as proof of identical contents.
