# Changelog

All notable changes to FreeFG are recorded here. Earlier private test builds are a separate series and are not
covered by this file.

## 1.0.0 – 2026-10-19

First public release. The proxy DLL is a new build (the multi-frame code is compiled in), so 0.9.0's measurements do
not carry over to it by themselves; see README.md, Status.

### Added

- **3× and 4× with FreeFG's own shaders, through MFG Unlocker.** Intel's runtime generates at most one frame per real
  frame on GPUs other than Intel's, and FreeFG still does not lift that limit. MFG Unlocker by dashdogy
  (<https://github.com/dashdogy/MFG-Unlocker>), a separate tool that the player adds as an OptiScaler plugin, does.
  FreeFG does not ship it. With it, FreeFG runs its own shaders on the work that is still Intel's at the frame
  count the runtime runs, including the multi-frame network's five extra kernels (33 own shaders in the package, 28
  before). Without it, FreeFG generates 2× as before.
- **Coexistence with a module that hooks Intel's runtime.** FreeFG notices the hook by comparing Intel's entry points
  in memory with Intel's file, passes each call on with the caller that module expects, accelerates only OptiScaler's
  own frame generation beside it, and steps aside for that session (`FAST_ASIDE` in its log) instead of ending the game
  when it meets work it has not verified.
- **Upscaler choice: FSR 4 or HelixSR.** FSR 4 stays the default. HelixSR, a separate project by lonewolf0622, can be
  chosen in Setup; the installer downloads its complete official release by pinned hash and ships none of it.
- **Figures** in README.md, ARCHITECTURE.md and MEASUREMENTS.md (Cyberpunk 2077 frame rate, GPU time per generated
  frame, VRR pacing, what Setup changes), each drawn from a data file in the repository.
- **A compatibility verdict for every game** (Setup's **Check**, `install.py check`): verified on BC-250,
  community-reported, automatic guided by the OptiScaler wiki, automatic from detection, or not supported with the
  reason and the way forward, decided offline before anything is written. A read-only scanner reads the game's
  executable and DLL tables, its files, the launcher's records and GE-Proton's fix for the game; Automatic now uses it
  to pick the executable's route, input and DirectX 12 switch for games without a recipe.
- **Refusals before any download**: anti-cheat, native Linux builds, 32-bit games, games without DirectX 12 or without
  an upscaler input (soft when you chose the input yourself), launcher stubs, a second installation on one launcher
  entry, GE-Proton's own upscaler DLLs, and what in the game folder Install would refuse (an earlier installation,
  another mod, an OptiScaler setup it does not take over), which Check now names with the plan; soft, with **Install
  anyway**: a GE-Proton fix that leaves DirectX 12 (adds `PROTONFIXES_DISABLE=1`, which turns off all of GE-Proton's
  fixes for that game), the wiki's "not working" (matched by launcher ID or executable and title), and a Unity game
  whose only DLSS evidence is the DLL Unity bundles. Setup lists every game's soft refusal and accepts each for that
  game only.
- **The OptiScaler wiki, evaluated**: refreshed to revision `9812e2d` (17 October 2026); every condition a page states
  is kept and checked against your setup; inputs the wiki reports broken leave the automatic choice; six wiki fixes,
  reviewed by an agent for the maintainers and awaiting a maintainer's confirmation, are applied only where the game is
  identified by its launcher ID or by its executable with its title (today only FINAL FANTASY VII REBIRTH and
  Soulstice can be); the rest is shown with its condition.
- **Community recipes** from other BC-250 owners, with a report and review checklist (CONTRIBUTING.md); their game
  settings are applied and reverted key by key like a verified recipe's.

### Changed

- **OptiScaler rebased** on upstream master of 19 October 2026 (`c2e44a8b`), tag `bc250-f971ed1` of the fork. The
  deadlock fix now keeps upstream's Streamline plugin locks and takes them after the Windows loader lock, instead of
  reverting the upstream change.
- **Pacing signal:** the proxy also counts the frames the runtime reports presented, so the pacing layer holds presents
  while XeFG generates at any frame count, also with Intel's shaders (`BC250_XEFG_DISABLE=1`) and on other GPUs.
  `BC250_XEFG_STATUS_POLL=0` turns its own per-frame status read off.
- OptiScaler's built-in fixes are taken from the shipped OptiScaler build (`f971ed14`): setting a key one of them sets is
  left to it, and only fixes newer than that build are written (5 games before, 1 now).
- A fresh OptiScaler setup now loads OptiPatcher (`LoadAsiPlugins=true`), which unlocks the upscalers of about 200 games
  on GPUs other than NVIDIA's; 0.9.0 placed it without loading it (not yet checked in a game).
- Install says "Launch option added" only when one was.
- A game whose DLSS is its only upscaler, and that ships no `nvngx_dlss.dll`, gets NVIDIA's DLSS helper (not yet checked
  in a game).

### Known limitations

- BC-250 only (other GPUs untested), Linux and Proton only, no generated-frame scaling.
- Setup offers 2× only; 3× and 4× are set in OptiScaler's menu and need MFG Unlocker.
- Beside MFG Unlocker, a game's own XeSS frame generation (native route) runs MFG Unlocker's and Intel's shaders at every
  frame count; FreeFG accelerates only OptiScaler's frame generation there.
- Beside another module, only the checks of the network's make-up step aside; FreeFG's other checks still end the
  game.
- With MFG Unlocker and `XeFGModel=default`, one of two 3× starts in Echo Point Nova ended during start-up with no error
  in any log; the next start worked. The cause is not known yet.
- Outside the 19 verified recipes, no automatic setup has been checked in play yet: Check and Install label those
  verdicts as automatic, and the promoted wiki fixes still await a maintainer's confirmation.

### Checked

- Builds reproduce the reference hashes. The installer tests pass. An offline install and Restore pass. The proxy loads
  under Wine, and with a stand-in module hooking Intel's entries it keeps the callers and accelerates only
  OptiScaler's contexts. The static check finds no Intel file and none of Intel's shaders or weight tables.
- A GPU proof-of-life on one BC-250, one short start per question (README.md, Status, has the details):
  - synthetic scenes at 2×: images bit-identical to 0.9.0's in SDR 1440p, HDR10 with pixel motion vectors at 1440p and
    SDR 4K;
  - Echo Point Nova (OptiScaler's frame generation): 2× accelerated at 2 frames per present; with MFG Unlocker v1.6.0
    and `XeFGModel=default`, 3× and 4× on FreeFG's shaders at 3 and 4 frames per present; with MFG Unlocker's own
    model, 3× accelerated at 3 frames per present; with HelixSR 2.0.0 as the upscaler, 2× accelerated, and back to
    FSR 4 cleanly;
  - Cyberpunk 2077 (the game's own XeSS frame generation), headless benchmark: 102.08 FPS at 2.0 presents per game
    frame, accelerated (one run);
  - Restore exact in both games; CONTROL Resonant with this OptiScaler build: 32 of 32 starts.
- Not checked: same-day speed comparisons, 3× and 4× on a VRR display and their picture, changing the frame count
  while a game runs (and Dynamic MFG), HDR10 at 3× and 4×, a game's own XeSS frame generation beside MFG Unlocker,
  games without a recipe, Flatpak Steam or Heroic.

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
