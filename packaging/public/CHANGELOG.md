# Changelog

Changes in each release of FreeFG. The private test builds made before 0.9.0 are not covered.

## 1.0.1 – 2026-10-20

The installer and the documents change. The proxy, pacing layer, shader profile and OptiScaler are byte-identical to
1.0.0's.

### Added

- An override of the anti-cheat refusal per game, at the risk of an account ban: Setup's **Override anti-cheat
  refusal...** or `install.py --accept-anticheat-risk` ([COMPATIBILITY.md](COMPATIBILITY.md#anti-cheat)). **Install
  anyway** and `--accept` still never lift it. Status and Check show the override until Restore.

### Changed

- Check lists anti-cheat as a refusal of its own kind (`[anticheat, risk, refused]`, before: `hard`) and names the
  override.

### Documents

- README and COMPATIBILITY name the 758 games with an OptiScaler wiki entry beside the 19 verified recipes.
- The figures carry less text; their captions give the conditions.
- MEASUREMENTS adds the two measurement series under Checked, with a figure. README recommends
  `XeFGModel=default` with MFG Unlocker for speed.

### Checked

- Without a GPU: the installer tests, an offline install and Restore, and CI.
- The payload is byte-identical to 1.0.0's, so 1.0.0's GPU [checks](MEASUREMENTS.md#checks-of-100) apply to it.
- Two measurement series with 1.0.0's files on one BC-250, Cyberpunk 2077 headless:
  - [1.0.0 against 0.9.0 at 2×](MEASUREMENTS.md#100-against-090-at-2-same-day), the same day: no measurable difference
    in an existing OptiScaler setup (−0.12%, SE 0.11); a fresh setup, which loads OptiPatcher, −0.45% (SE 0.25).
  - [3× and 4× with MFG Unlocker](MEASUREMENTS.md#3-and-4-with-mfg-unlocker), against MFG Unlocker alone with
    `XeFGModel=default`: +34% and +43% game frame rate (pacing off, 1–2 runs per arm). Also HDR10, Dynamic MFG, and no
    start-up exit in 18 starts at 3×.

## 1.0.0 – 2026-10-20

First public release. The proxy `libxess_fg.dll` is a new build with the multi-frame code compiled in. The figures in
[MEASUREMENTS.md](MEASUREMENTS.md) were measured with 0.9.0 and not repeated with this build.

### Added

- 3× and 4× with MFG Unlocker by dashdogy (<https://github.com/dashdogy/MFG-Unlocker>), a separate OptiScaler plugin
  that lifts Intel's limit of one generated frame per real frame on GPUs other than Intel's. FreeFG neither lifts
  that limit nor ships MFG Unlocker. With it, FreeFG's shaders run on the work that is still Intel's at every frame
  count, including five kernels of the multi-frame network (33 shaders in the package, 28 in 0.9.0). Without it,
  FreeFG generates 2×. Steps: [3× and 4× with MFG Unlocker](README.md#3-and-4-with-mfg-unlocker).
- Coexistence with a module that hooks Intel's runtime. The proxy passes each call on with the caller that module
  expects and accelerates only OptiScaler's own frame generation. Where it meets work it has not verified, it steps
  aside for that session (`FAST_ASIDE` in its log) instead of ending the game ([ARCHITECTURE.md](ARCHITECTURE.md)).
- Upscaler choice in Setup: FSR 4 (default) or HelixSR, a separate project by lonewolf0622. When HelixSR is chosen, the
  installer downloads its complete official release, pinned by hash; FreeFG ships none of it
  ([NOTICE.md](NOTICE.md#helixsr)).
- A compatibility verdict for every game, decided offline before anything is written (Setup's **Check**,
  `install.py check`): verified on BC-250, community-reported, automatic (guided by the OptiScaler wiki, or from
  detection), or not supported with the reason and the way forward. It comes from a read-only scan of the game and its
  launcher entry ([PRIVACY.md](PRIVACY.md) lists what is read). For a game without a recipe, Automatic takes the
  executable, route, input and DirectX 12 switch from the scan.
- Refusals before any download, some of them soft (accepted per game with **Install anyway**). Check also names what in
  the game folder Install would refuse. The list, with codes and ways forward:
  [COMPATIBILITY.md](COMPATIBILITY.md#refusals).
- OptiScaler wiki data at revision `9812e2d` (17 October 2026), with every condition a page states checked against your
  setup. An input the wiki reports broken is not chosen automatically. Six wiki fixes, reviewed by an agent and awaiting
  a maintainer's confirmation, are applied only where the game is identified by its launcher ID or by its executable and
  title (today FINAL FANTASY VII REBIRTH and Soulstice). Other wiki advice is shown with its condition.
- Community recipes from other BC-250 owners, with a report form and a review checklist
  ([CONTRIBUTING.md](CONTRIBUTING.md#game-recipes)). Their game settings are applied and restored key by key, as a
  verified recipe's are.
- Figures in README.md and MEASUREMENTS.md (Cyberpunk 2077 frame rate, GPU time per generated frame,
  VRR pacing, what Setup changes), each drawn from a data file in the repository.

### Changed

- OptiScaler is rebased on upstream master of 19 October 2026 (`c2e44a8b`), fork tag `bc250-f971ed1`
  ([NOTICE.md](NOTICE.md)). The start-up deadlock fix keeps upstream's Streamline plugin locks and takes them after the
  Windows loader lock, instead of reverting the upstream change.
- The proxy also counts the frames the runtime reports presented. The pacing layer therefore holds presents while XeFG
  generates at any frame count, also with Intel's shaders (`BC250_XEFG_DISABLE=1`) and on other GPUs, which 0.9.0 did
  not pace. `BC250_XEFG_STATUS_POLL=0` turns the proxy's own per-frame status read off.
- OptiScaler's built-in game fixes are read from the shipped build (`f971ed14`). The installer never writes a key one of
  them sets, and adds only fixes newer than that build: for 1 game (5 in 0.9.0).
- A fresh OptiScaler setup loads OptiPatcher (`LoadAsiPlugins=true`), which unlocks the upscaler inputs of about 200
  games on GPUs other than NVIDIA's; 0.9.0 placed it without loading it. Not yet checked in a game.
- On the OptiFG route, a game without a verified recipe whose only upscaler is DLSS, and which ships no
  `nvngx_dlss.dll`, gets NVIDIA's DLSS helper. Not yet checked in a game.
- Install reports "Launch option added" only when it added one.

### Known limitations

The full list is in [README.md](README.md#known-limitations). New or specific to 1.0.0:

- Setup writes 2× only; 3× and 4× are set in OptiScaler's menu and need MFG Unlocker.
- With MFG Unlocker loaded, a game's own XeSS frame generation runs MFG Unlocker's and Intel's shaders at every frame
  count; FreeFG accelerates only OptiScaler's frame generation there.
- Beside another module, only the checks of the network's make-up step aside; the other checks still end the game.
- With MFG Unlocker and `XeFGModel=default`, one of two 3× starts in Echo Point Nova ended during start-up with no error
  in any log; the next start worked. The cause is not known.
- No automatic setup outside the 19 verified recipes has been checked in play. Check and Install label those verdicts as
  automatic; the promoted wiki fixes await a maintainer's confirmation.
- BC-250 only (other GPUs untested), Linux and Proton only, no generated-frame scaling.

### Checked

A proof-of-life qualification. Its results, conditions and what it did not check are in
[MEASUREMENTS.md](MEASUREMENTS.md#checks-of-100).

- Without a GPU: reproducible build hashes, the installer tests, an offline install and Restore, the Wine loader check
  (callers kept beside a stand-in hooking module, only OptiScaler's contexts accelerated) and the static check.
- On one BC-250, one short start per question: synthetic scenes at 2× (bit-identical to 0.9.0); Echo Point Nova at 2×,
  at 3× and 4× with MFG Unlocker v1.6.0, and with HelixSR 2.0.0; one Cyberpunk 2077 benchmark run (102.08 FPS); Restore
  in both games; CONTROL Resonant with this OptiScaler build, 32 of 32 starts.

## 0.9.0 – 2026-10-19

The first release: a private pre-release for review. The figures in [MEASUREMENTS.md](MEASUREMENTS.md) were measured
with this build.

### Added

- XeSS frame generation at 2× accelerated on the AMD BC-250. A `libxess_fg.dll` proxy forwards to Intel's unmodified
  XeFG runtime 1.3.1.78 and runs part of its GPU work with this project's own shaders (13 pipeline replacements and 15
  Winograd-domain kernels), which read the network's coefficients at run time. Generated images were bit-identical
  wherever compared. Cyberpunk 2077, 1440p, FSR 4 Performance, headless: 103.3 FPS against 85.3 with Intel's shaders
  (+21%, measured on two days).
- Frame pacing for VRR under gamescope: a Vulkan layer holds each frame until its turn while XeFG generates. It presents
  from a compute queue where the driver has one, otherwise from the game's queue, and wakes stock gamescope so that it
  shows a held frame at once.
- FSR 4 upscaling through OptiScaler, with a BC-250 build of AMD's FSR 4 (RC11, INT8).
- An installer with a desktop front end (Setup): Add games, Install, Restore, Status and Check system. It writes Steam,
  Heroic and Lutris launch settings, applies per-game recipes for 19 games and lists OptiScaler wiki advice for about
  750 more. Restore puts everything back and keeps what the user or a game update changed.
- Pinned downloads, each checked by SHA-256 and downloaded once: Intel's runtime from Intel's repository, the FSR 4 DLL,
  OptiScaler's nightly support files and, only where a DLSS input needs it, NVIDIA's DLSS helper.
- Optional extras: realtime priority for gamescope; Steam's screensaver off while a game runs.
- A reproducible build of the proxy and the layer, byte for byte on the pinned toolchain, with CI and a static check
  that the package contains no Intel file and none of Intel's shaders or weight tables.

### Known limitations

- 2× only, no generated-frame scaling, BC-250 only (other GPUs untested), Linux and Proton only.
- With Intel's shaders (`BC250_XEFG_DISABLE=1` or another GPU), presents are not paced.

### Checked

Results and conditions: [MEASUREMENTS.md](MEASUREMENTS.md).

- Without a GPU: reproducible build hashes, the installer tests, an offline install and Restore, the Wine loader check.
- Synthetic scene on a BC-250: generated images identical in five 2× configurations. Six headless Cyberpunk 2077
  benchmark runs.
- Live install and Restore on a BC-250 in Echo Point Nova (Steam, OptiFG; started to the main menu) and Cyberpunk 2077
  (Heroic entry, native XeSS FG; benchmark at 2.001 presents per game frame). Restore returned both game folders and
  launcher entries as they were. These runs used the installer before its messages were reworded for 0.9.0; its install
  and Restore steps are the same.
- LG G5 TV at 1440p and 120 Hz with VRR, Cyberpunk 2077's benchmark: 2.000 presents per game frame and the same pacing
  as an earlier private build, at a 0.9% (SDR) and 1.3% (HDR10) lower frame rate.
- Not checked: gameplay (only benchmarks and menus were run).
