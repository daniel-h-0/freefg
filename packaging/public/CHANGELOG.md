# Changelog

All notable changes to FreeFG are recorded here. Earlier private test builds are a separate series and are not
covered by this file.

## 0.9.0 – 2026-10-19

First release: a private pre-release for review, ahead of the first public release.

### Added

- **Accelerated XeSS frame generation at 2× on the AMD BC-250.** A `libxess_fg.dll` proxy that forwards to Intel's
  unmodified XeFG runtime 1.3.1.78. It carries out part of the runtime's GPU work with this project's own shaders (13
  pipeline replacements and 15 Winograd-domain kernels), which read the network's coefficients at run time. Cyberpunk
  2077, 1440p, FSR 4 Performance, headless: 103.3 FPS against 85.3 with Intel's shaders (+21%, cross-day; see
  MEASUREMENTS.md). Generated images bit-identical where compared.
- **Even frame pacing for VRR under gamescope.** A Vulkan layer holds each frame until its turn while XeFG generates.
  It presents from a compute queue where the driver has one, otherwise from the game's queue, and nudges stock gamescope
  to show held frames at once.
- **FSR 4 upscaling** through OptiScaler, with a BC-250 build of AMD's FSR 4 (RC11, INT8).
- **Installer with a desktop front end:** Add games, Install, Restore, Status and Check system. It writes Steam, Heroic
  and Lutris launch settings, applies per-game recipes for 19 games, and lists OptiScaler wiki advice for about 750
  more. Restore puts everything back and keeps what the user or a game update changed.
- **Pinned downloads:** Intel's runtime from Intel's repository, the FSR 4 DLL, OptiScaler's nightly support files and,
  only where a DLSS input needs it, NVIDIA's DLSS helper. Each is checked by SHA-256 and downloaded once.
- **Optional extras:** gamescope realtime priority, and Steam's screensaver kept off while a game runs.
- **Reproducible build** of the proxy and the layer, byte for byte on the pinned toolchain, with CI and a static check
  that the package contains no Intel file and none of Intel's shaders or weight tables.

### Known limitations

- 2× only, no generated-frame scaling, BC-250 only (other GPUs untested), Linux and Proton only.
- With Intel's shaders (`BC250_XEFG_DISABLE=1` or another GPU), presents are not paced.

### Checked

- Builds reproduce the reference hashes. The installer tests pass. An offline install and Restore pass. The proxy loads
  under Wine. SDK image identity was checked in five 2× configurations. Six headless Cyberpunk 2077 benchmark runs
  completed.
- Live install and Restore on a BC-250 in Echo Point Nova (Steam, OptiFG; started to the main menu) and Cyberpunk 2077
  (its Heroic entry, native XeSS FG; the benchmark, started with the launch settings the installer wrote, at 2.001
  presents per game frame), with the installer as it was before its messages were reworded for this release (the same
  install and Restore). Restore returned both game folders and their launcher entries as they were.
- On an LG G5 TV at 1440p 120 Hz with VRR, Cyberpunk 2077's benchmark: 2.000 presents per game frame and the same
  frame pacing as an earlier private build, at a 0.9% (SDR) and 1.3% (HDR10) lower frame rate. Benchmarks and menus
  only; no gameplay yet.
