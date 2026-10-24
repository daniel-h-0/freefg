# Building FreeFG from source

## Outputs

| Output | Built by | Reference sha256 |
| --- | --- | --- |
| `libxess_fg.dll` (the proxy) | `release/build_proxy.py` | `b0b71d6575ad8c27072741545459364a880ccb6f0f369a23de58558f02505ec3` |
| `libxefg_wave.so` (the pacing layer) | `release/build_layer.py` | `d5f9800d0f52903f16b5a71af42599d89640bc41fc0bfc4dad66248f30ac3271` |

Each script builds its binary twice, requires both builds to be identical, and exits with status 1 when the result
differs from the reference hash in `release/inputs.lock.json` (`--no-reference-check` exits 0). On the pinned toolchain
([Toolchain](#toolchain)) the result equals the shipped file byte for byte. A different compiler, Wine or glibc version
normally changes the bytes; a binary with another hash is a new build that needs its own testing. The package's OptiScaler build is not built
here ([What this tree does not build](#what-this-tree-does-not-build)).

## Toolchain

Linux on x86-64 with:

| Tool | Version of the reference build | Used for |
| --- | --- | --- |
| Python | 3.11.4 or newer (reference: 3.14.7); `toolchain.py` extracts archives with tarfile's `data` filter | all build scripts |
| clang, lld | 22.1.8 | the proxy (`--target=x86_64-w64-windows-gnu`) |
| Wine | 11.16: headers (`/usr/include/wine`), x86-64 Windows import libraries (`/usr/lib/wine/x86_64-windows`), `wine` | compiling the proxy; `check_proxy_wine.py` |
| GCC | 16.2.1, with AddressSanitizer, UBSan and ThreadSanitizer | the pacing layer and its unit tests |
| glibc, binutils | 2.44, 2.47 | the pacing layer |
| vulkan-headers | 1.4.357 | the pacing layer |
| DirectX Shader Compiler (DXC) | Microsoft's release for Linux: v1.9.2607; v1.9.2609 for the static check alone | the shader profile; the static check ([DXC](#dxc)) |
| `bsdtar` (libarchive) | any | the installer's unit tests |
| git | any | `assemble.py` records the checked-out commit |

Locations are settings with environment variables, such as `XEMFG_BUILD` (outputs, default `build/`, which git ignores)
and `XEMFG_CACHE` (downloads, default `build/cache`); `python3 release/config.py --help` lists them all.

### The pinned toolchain

The compilers, Wine and headers of the table need not be installed. `release/toolchain.py` takes the Arch Linux package
files pinned by SHA-256 in `release/ci/ci.lock.json` (the versions above plus gcc's runtime libraries), from pacman's
package cache, a folder in `XEMFG_PACKAGES` or the Arch Linux Archive, and unpacks them into a folder of their own,
without root. With `XEMFG_TOOLCHAIN=pinned` the build scripts prepare and use that folder (`<cache>/toolchain-<id>`):
clang, lld, gcc, Wine's headers and import libraries and the C and Vulkan headers all come from it, and a compiler
version or header digest that differs from `release/inputs.lock.json` fails the build. Without the variable the builds
use the host's tools and only warn on a difference.

```sh
python3 release/toolchain.py prepare      # unpack and check the pinned packages (about 0.9 GB)
export XEMFG_TOOLCHAIN=pinned
```

From the host, a pinned build still uses the Python interpreter, the shared libraries the compilers load that no pinned
package holds (such as zlib and libxml2), and the Wine that runs `check_proxy_wine.py`; none of them reaches an output.

## Downloaded inputs

`release/fetch.py` downloads the groups under `fetch` in `release/inputs.lock.json` from
`https://raw.githubusercontent.com/<repository>/<commit>/<path>`, checks each file's SHA-256 and keeps it in
`XEMFG_CACHE`. It never runs what it downloads. The builds call it on demand; `--offline` restricts every tool to the
cache.

| Group | Repository | Commit | Files | Used for |
| --- | --- | --- | --- | --- |
| `intel-xess` | `intel/xess` | `de0fb9c1c510661c571164e1418ceca8101dab69` | `inc/xess_fg/*.h`, `inc/xell/*.h`, `LICENSE.txt`, `third-party-programs.txt` | API types for the proxy; licence texts for the package |
| `intel-xess-runtime` | `intel/xess` | `de0fb9c1c510661c571164e1418ceca8101dab69` | `bin/libxess_fg.dll` | the proxy's export table, and the size and hash the proxy checks before loading the runtime; never copied into an output |
| `optiscaler-license` | `optiscaler/OptiScaler` | `92337ebfbf07d533eabe3731fd8de1bb19437aea` | `LICENSE` | the package's `licenses/OptiScaler.txt` |
| `fsr4-notices` | `daniel-h-0/bc250-fsr4-fork` | `b2ab949477b4d2745babae146393db5537d87fcb` | `dll/notices/*` | the package's `licenses/fsr4/` |
| `minhook` | `TsudaKageyu/minhook` | `c3fcafdc10146beb5919319d0683e44e3c30d537` | sources, `LICENSE.txt` | nothing in FreeFG; fetched because `fetch.py` without arguments fetches every group |

Intel's XeFG headers carry Intel's proprietary notice. They are fetched at build time and must never be committed to
this tree or shipped. The installer's own downloads are pinned separately, in `packaging/dependencies.json`
([PRIVACY.md](PRIVACY.md)).

## Build and check

From a checkout of <https://github.com/daniel-h-0/freefg>:

```sh
python3 release/ci/toolchain.py dxc --dest build/dxc   # DXC v1.9.2609, downloaded and checked
export XEMFG_DXC=build/dxc
export XEMFG_TOOLCHAIN=pinned                          # optional: the pinned toolchain (prepared on first use)
python3 release/fetch.py
python3 release/build_layer.py                         # unit tests under sanitizers, then libxefg_wave.so twice
python3 release/build_proxy.py                         # libxess_fg.dll twice, then its ABI checks
python3 release/check_proxy_wine.py                    # the proxy under Wine's loader, CPU only
export XEMFG_OPTISCALER=/path/to/folder                # holds OptiScaler.dll from the release archive
python3 release/assemble.py --variant intel-free-mfg --no-source-companion
python3 release/check_intel_free.py check build/package-intel-free-mfg/<name>   # result "pass", exit status 0
```

`assemble.py` takes the OptiScaler DLL (`opti/OptiScaler.dll` in the release archive) from `XEMFG_OPTISCALER` and checks
it against its pinned SHA-256. `python3 release/ci/assemble_ci.py --variant intel-free-mfg` assembles the package
without it, as CI does; it also requires a clean checkout and outputs equal to the reference hashes.

### What each step checks

- `build_layer.py` builds and runs the layer's unit tests (pacer, wave layer, concurrent presents) under
  AddressSanitizer with UBSan and under ThreadSanitizer; any sanitizer report fails the build. It writes
  `build/layer/build.json`.
- `build_proxy.py` checks its inputs against the lock; assembles the shader profile into the build folder and builds its
  size-and-hash manifest into the DLL; generates the export definitions from Intel's DLL (57 exports at their ordinals,
  8 wrapped and 49 forwarded to `bc250_xefg_original`, plus the 4 exports of FreeFG's settings interface); and
  compiles `src/game/mfg_proxy.c` twice. It checks the built DLL: Intel's export table reproduced ordinal by ordinal,
  imports only from `kernel32.dll` and `ucrtbase.dll`, no reference to `version.dll` or an `XeSSMFG` loader. It writes
  `build/addon-intel-free-mfg/build.json`.
- `check_proxy_wine.py` runs a test program under Wine in a private prefix, with no GPU or display, in four layouts:
  - the pinned runtime: forwarded and wrapped calls reach Intel's code;
  - a runtime altered by one byte, and no runtime: the wrapped call refuses without loading anything;
  - a stand-in hooking eight of Intel's entries: each is reached once; six of them (the four lifecycle entries,
    `xefgSwapChainD3D12GetSwapChainPtr` and `xefgSwapChainTagFrameConstants`) with the caller they would see without the
    proxy, `xefgSwapChainGetLastPresentStatus` and `xefgSwapChainSetNumInterpolatedFrames` with the proxy as caller.
    Only a module whose version resource names OptiScaler is considered for acceleration.

  It also runs the unit test of the proxy's bookkeeping beside another module (`src/game/test_proxy_coexist.c`).
- `assemble.py` runs the installer's unit tests first. It refuses stale builds and files the package must not carry
  (Intel's runtime, the FSR 4 DLL), and with `--archive` documents that still carry the draft marker. It writes
  `build/package-intel-free-mfg/<name>/` with `manifest.json` (every file's SHA-256, the git commit, and which shipped
  files differ from that commit), then runs the static check and removes the package if the check fails.
- `check_intel_free.py check`, the static check, reads every file of the package. It fails on a file whose SHA-256 is
  that of an Intel file or of a shader program of Intel's runtime; on DXIL that is not one of the profile's own shaders,
  also inside other files (the pinned OptiScaler DLL's own shaders excepted); on DXIL of shader model 6.4; and on any
  copy of Intel's warp weight tables, as raw bytes or as a constant array in DXIL. It knows Intel's material only by
  hashes and checksums (`release/intel_material.json`); the tree holds no Intel bytes. `release/ci/check_controls.py`
  tests each detector on synthetic material.

### DXC

The static check reads DXIL constant arrays from DXC's disassembly, so `check_intel_free.py` and `assemble.py` fail
without `XEMFG_DXC`. `check_intel_free.py check --skip-constant-scan` leaves that scan out and records this in its
report; `assemble.py` has no such option. For this scan, v1.9.2609 (which `toolchain.py dxc` downloads and CI uses)
gives the same constant arrays as v1.9.2607 for every DXIL file of the profile. Rebuilding the profile byte for byte
needs v1.9.2607 ([The shader profile](#the-shader-profile)).

### Installer tests and an offline install

- `python3 release/ci/installer_tests.py` runs the installer's unit tests on their own.
- `python3 release/smoke_install.py --variant intel-free-mfg --deps <dir>` installs the assembled package into a
  throwaway game folder and restores it, offline. `<dir>` holds the installer's prepared downloads, for example
  `~/.cache/bc250-xefg-testers/payload` after one Setup run.

## The shader profile

The package's `payload/BC250-XeFG/shaders/` holds 52 shaders and 9 tables and markers, all of this project's own origin.
The tree holds them compiled in `release/profile/` (33 shaders, the tables and markers) and `release/profile-mfg/` (the
nine U-Net shaders and three refinement shaders the multi-frame build ships in a faster form, which replace their
`release/profile/` files in its profile, F4Q's seven shaders, F4Q2's three, F4Q3's two and the seven FP16 forms), and the HLSL they are compiled from in `src/kernels/`. Each file is pinned by SHA-256
in `release/inputs.lock.json` with origin `own` (`release/profile-mfg/` as the tree group `profile-intel-free-mfg`). The
builds read `release/profile/` unless `XEMFG_PROFILE` names another directory; `release/profile-mfg/` is always read
from the tree.

To rebuild every shader and compare the bytes, extract Microsoft's DXC release v1.9.2607 for Linux
(`linux_dxc_2026_07_29.x86_x64.tar.gz`, SHA-256 `55665c87824051ed4774ff3280a79ccbbb7d39243b9736ca5e98222134112d54`) and
run:

```sh
XEMFG_DXC=/path/to/linux_dxc_2026_07_29.x86_x64 python3 release/build_profile.py check   # "result": "pass", 33 byte-identical, and 16 in variant_profiles
```

Another DXC version compiles the same sources to different bytes. `release/profile/ORIGIN.md` describes each shader's
recipe (`release/profile/origin.json`, and `release/profile-mfg/origin.json` for that folder).

## CI

`.github/workflows/ci.yml` runs on every push to `main`, every pull request and on demand:

- Toolchain: an official Arch Linux container image pinned by digest, with pacman pointed at the Arch Linux Archive
  snapshot of 2026-09-03. The packages that reach an output are also pinned by file SHA-256 (`release/ci/ci.lock.json`).
- Steps: those of [Build and check](#build-and-check) (assembling with `assemble_ci.py`), plus the release tools' unit
  tests, `check_public_docs.py`, the profile checks without the rebuild, the static check's controls and a strict public
  export.
- Result: every output is compared with its reference hash; on this toolchain a difference fails the job. The job
  uploads build records and reports, not binaries.
- Not run: the byte-for-byte profile rebuild (it needs the 515 MB DXC v1.9.2607 release) and the maintainers'
  `check_intel_free.py self-test` (it needs private material; `check_controls.py` covers every detector instead).

`.github/workflows/pins.yml` runs weekly. It checks that every pinned download still serves its pinned bytes, and runs
the CI job on the current Arch packages, where hash differences are warnings.

`python3 release/ci/toolchain.py --help` explains the toolchain setup; the same steps run in a local container. If the
container user differs from the owner of a bind-mounted checkout (root, as in the CI job), git refuses the tree
("detected dubious ownership") and `assemble.py` cannot record the commit. Mark the mount as safe first, as the workflow
does:

```sh
git config --system --add safe.directory <path in the container>
```

## What this tree does not build

- The OptiScaler build (`opti/OptiScaler.dll`, GPL-3.0, sha256
  `5e570dff6299866c508b60634d0dcfc5a53975840888f2aa5e69ba31c3819da6`). The package ships this DLL. Its source is the
  OptiScaler fork at <https://github.com/daniel-h-0/OptiScaler>, tag `bc250-f971ed1` ([NOTICE.md](NOTICE.md)). The
  release tooling does not download the built DLL, so CI assembles the package without it; it is the only component CI
  may leave out.
- The source companion (`assemble.py` without `--no-source-companion`), which reads a git checkout of the OptiScaler
  fork (`XEMFG_OPTISCALER_SOURCE`).

## Reproducibility

- Build records (`build.json`) and the package manifest hold no absolute paths. The builds give the same bytes from a
  tree exported to another directory (`release/export_tree.py --public DIR`).
- The proxy build warns when the Wine headers or import libraries differ from those recorded in the lock (by count and
  digest), and the layer build when the system headers do. With `XEMFG_TOOLCHAIN` set, either difference, or another
  compiler version, is an error, and each `build.json` names the toolchain's id.
