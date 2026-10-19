<!-- Copy of packaging/public/README.md for this folder of the repository, written by release/export_tree.py --public with its links adjusted; edit packaging/public/README.md instead. -->
# FreeFG

**Faster XeSS frame generation for the AMD BC-250 on Linux.** FreeFG works with Intel XeSS Frame Generation (XeFG)
in DirectX 12 games running under Proton. Intel's own runtime, downloaded unmodified, still generates the frames: one
generated frame for every real frame (2×). FreeFG runs part of the runtime's GPU work with this project's own
shaders, which are faster on the BC-250 and give the same pixels, and it paces the output evenly for VRR displays. It
also sets up upscaling with a BC-250 build of AMD FSR 4, through OptiScaler.

FreeFG is an independent project. It is not affiliated with, endorsed by or supported by Intel, AMD, NVIDIA, ASRock,
Valve or the OptiScaler project. Intel, XeSS and Xe are trademarks of Intel Corporation; AMD, FidelityFX and FSR are
trademarks of Advanced Micro Devices, Inc.; NVIDIA and DLSS are trademarks of NVIDIA Corporation; Steam is a trademark
of Valve Corporation. They are used here only to say what FreeFG works with.

## In plain words

- **What you get:** in a supported game, frame generation at 2× with about a fifth more frames per second than XeFG
  gives with Intel's own shaders on the same BC-250 (Cyberpunk 2077, 1440p, FSR 4 Performance: 103.3 instead of 85.3
  FPS; see [MEASUREMENTS.md](packaging/public/MEASUREMENTS.md) for how that was measured and what it does not cover).
- **What stays the same:** the generated images. In the synthetic tests so far they are bit-for-bit the same as with
  Intel's shaders wherever that was compared ([MEASUREMENTS.md](packaging/public/MEASUREMENTS.md) gives the exact scope).
- **What it does not do:** it does not raise Intel's limit of one generated frame per real frame on GPUs other than
  Intel's (no 3× or 4×). It does not modify Intel's DLL, does not replace your graphics driver and does not run on
  Windows.
- **How it works**, in one paragraph: FreeFG places a small `libxess_fg.dll` where the game or OptiScaler loads
  Intel's runtime. It passes every call on to Intel's unmodified runtime, which sits beside it, and while the runtime
  runs it substitutes some of the runtime's GPU shaders with this project's own. A Vulkan layer holds each finished
  frame until its turn so that VRR displays show them evenly. [ARCHITECTURE.md](packaging/public/ARCHITECTURE.md) describes exactly
  what is replaced and what is not.

## Status

**0.9.0, a private pre-release for review.** It is for the AMD BC-250 only, and this package generates one frame per
real frame (2×) only. FreeFG 0.9.0 has been checked as follows:

- **Build:** reproducible byte for byte from the source tree on the pinned toolchain ([BUILDING.md](packaging/public/BUILDING.md)).
- **Static check:** every shader in the package is compiled from this project's HLSL source, and the check finds no
  Intel file, none of the shader programs of Intel's runtime and none of Intel's weight tables in it
  ([NOTICE.md](NOTICE.md)).
- **Installer:** unit tests pass, and an offline install and Restore in a throwaway game folder return the folder to
  its original files.
- **Wine loader check:** without a GPU, the DLL loads under Wine and forwards to Intel's runtime. It refuses a missing or
  altered runtime.
- **GPU, headless, BC-250:** synthetic XeFG scenes at 2× (SDR and HDR10, two kinds of motion vectors, 1440p and 4K)
  produced the same images as the reference runs in all five configurations. Cyberpunk 2077's built-in benchmark
  completed all 6 runs with this build (SDR and HDR10).
- **Live install and Restore, BC-250:** the installer (`install.py`, which Setup runs) put this build into two games
  and took it out again. That was the installer before its messages were reworded for this release; what it installs
  and restores is the same. Echo Point Nova (Steam, OptiFG input) started from Steam to its main menu with the
  accelerated path active. Cyberpunk 2077 (GOG through Heroic, native XeSS FG) ran its benchmark with the launch
  settings the installer wrote, at 2.001 presents per game frame. Restore gave both game folders and their Steam and
  Heroic entries back as they were ([MEASUREMENTS.md](packaging/public/MEASUREMENTS.md#live-install-and-restore)).
- **On a TV with VRR, BC-250:** Cyberpunk 2077's benchmark on an LG G5 OLED TV at 1440p and 120 Hz, VRR active in
  every run: 2.000 presents per game frame, and the same frame pacing as an earlier private build at a 0.9% (SDR) and
  1.3% (HDR10) lower frame rate ([MEASUREMENTS.md](packaging/public/MEASUREMENTS.md#on-a-tv-with-vrr)).
- **Not yet done with this build:** gameplay (so far only main menus and benchmarks), a game started from Heroic
  itself, the desktop Setup window in a live install, and a count of generated frames on the OptiFG route. Earlier
  private builds with the same installer have been played on a BC-250.

It is qualified only on the **AMD BC-250 under Proton, in Steam Game Mode (gamescope)**. Everything else is untested.

## Requirements

**Hardware:** an AMD BC-250 (ASRock board with AMD's Cyan Skillfish APU, PCI ID `1002:13fe`). Other GPUs: see
[Other GPUs](#other-gpus).

**System** (Setup's **Check system** reports each item):

| Item | Needed | Tested with |
| --- | --- | --- |
| Linux distribution | any with Steam and Proton | CachyOS, kernel `linux-cachyos-bc250` 7.2.8 |
| Graphics driver | Mesa RADV, any current version. The BC-250's compute queue (off in stock Mesa) is optional. | Mesa 26.2.2, a BC-250 build with the compute queue on |
| Proton | GE-Proton 11-6 or 11-7 (other Proton builds are untested) | GE-Proton 11-7 |
| Compositor | gamescope 3.16.28 or newer, ideally with realtime priority (`CAP_SYS_NICE`, see [Extras](#extras)). Frame pacing works only under gamescope, as in Steam Game Mode. | gamescope 3.16.28 |
| Memory | a larger GTT helps at 1440p and 4K | 6 GiB GTT (`ttm.pages_limit=1572864`) |
| Setup | Python 3.11 or newer, Zenity (for the desktop Setup), `bsdtar` (libarchive) | Python 3.14 |
| Network | internet access the first time you install: about 110 MB for a fresh setup, 59 MB more for a DLSS input in a game whose own `nvngx_dlss.dll` OptiScaler does not find ([PRIVACY.md](packaging/public/PRIVACY.md)) | |

A patched Mesa that turns the compute queue on needs a kernel with the matching BC-250 fixes. Never use such a Mesa
on a kernel without them; **Check system** warns about that combination.

**Games:** 64-bit DirectX 12 games under Proton, launched from Steam, Heroic or Lutris, with an input that OptiScaler
supports (see [Install](#install)). DirectX 11 and Vulkan games are not supported. Game folders must have ASCII-only
paths. Do not use FreeFG in online games with anti-cheat. It loads DLLs into the game process, and anti-cheat
software may treat that as tampering.

## Supported games

Setup carries a recipe for 19 games: the frame-generation input, OptiScaler settings, the game's own frame-generation
setting and a DirectX 12 launch option where one is needed. **Restore** undoes all of it. The table says what was
observed on a BC-250 with **earlier private builds** that use the same installer, recipes and frame-generation route at
2×. So far, FreeFG itself has run in Cyberpunk 2077 (benchmark, headless and on a TV) and Echo Point Nova (main
menu); the rows say so.

| Game | Input the recipe picks | Observed on a BC-250 |
| --- | --- | --- |
| CONTROL Resonant | DLSS FG (turns the game's DLSS frame generation on) | 2.0 presents per game frame |
| Crimson Desert | FSR 3.1 FG (turns the game's frame generation on) | played at 2× |
| Cyberpunk 2077 | native XeSS FG | played at 2×; with this build: installed and restored, benchmark at 2.0 (headless and on a TV with VRR) |
| Dead as Disco | FSR 3.1 FG (`FrameGenerationMode=FSR`) | 2.0 |
| Echo Point Nova | OptiFG | 2.0; with this build: installed, started to the main menu, restored |
| Kingdom Come: Deliverance II | OptiFG | 2.0 in gameplay |
| RoboCop: Rogue City | DLSS FG (the game's DLSS upscaling and frame generation) | 2.0 |
| System Shock | OptiFG, `-dx12` | 2.0 at start-up |
| The Invincible | OptiFG, `-dx12` | 2.0 in gameplay |
| VOIN | OptiFG, `-dx12` | 2.0 |
| Witchfire | DLSS FG (turns the game's `DLSS_FG` on) | 2.0; played at 2× |
| Assassin's Creed Black Flag Resynced | native XeSS FG | installed; generation not checked |
| Hogwarts Legacy | DLSS FG (turns the game's DLSS frame generation on) | installed; generation not checked |
| Red Dead Redemption 2 | OptiFG | installed; generation not checked |
| Tainted Grail: The Fall of Avalon | OptiFG, `-force-d3d12` | installed; generation not checked |
| Thymesia | OptiFG, `-dx12` (needs an in-game resolution scale above 100%) | installed; generation not checked |
| TRYP FPV | OptiFG, `-dx12` | installed; generation not checked |
| Deadzone: Rogue | FSR 3.1 FG | **does not generate yet** |
| Deep Rock Galactic | DLSS FG, `-dx12` | **did not generate**: choose an upscaler (DLSS / DLSS FG) once in the game's own Video menu |

For about 750 other games, Setup shows what the [OptiScaler wiki](https://github.com/optiscaler/OptiScaler/wiki) reports
(preferred inputs, settings, a link) and applies only its DirectX 12 launch option. Most of those reports come from
Windows PCs with other GPUs. OptiScaler's own built-in per-game fixes keep working.

## Install

1. Extract the release archive and run **`Start-freefg.sh`** in Desktop Mode. It opens Setup.
2. **Add games:** select each game's rendering `.exe`. For Unreal Engine games that is often the one in
   `Binaries/Win64`, not the launcher in the game's root folder.
3. **Install**, then choose the frame-generation input. **Automatic** is recommended: it uses the recipe's input where
   there is one, else native XeSS FG where the game ships it, otherwise OptiFG. If the game or its launcher is still
   running, Setup names it and waits until you close it. Install games that need different inputs separately.
4. Start the game from Steam, Heroic or Lutris as usual. In its graphics settings, select the upscaler that activates
   FSR 4 (the game may still call it DLSS, FSR or XeSS), and turn frame generation on, except with OptiFG (see the
   table below).

| Input | What to set in the game |
| --- | --- |
| Automatic | Nothing beyond what the recipe or the table rows below say. |
| DLSS FG | Enable the game's DLSS frame generation (Streamline 2 or newer). |
| FSR 3.1 FG / FSR 3.0 FG | Enable the game's FSR frame generation. The HUD is interpolated with the scene, so fast-moving HUD elements can smear slightly in generated frames. |
| OptiFG | Use the game's usual upscaler. Leave the game's own frame generation off. OptiFG derives its inputs from upscaling and can affect HUDs. |
| Native XeSS FG | Enable the game's XeSS frame generation. Its runtime DLL must be beside the `.exe`. |

The first start, or the first start with a new frame-generation mode, can pause while shaders compile.

**What Setup does:** it downloads and checks the files listed in [PRIVACY.md](packaging/public/PRIVACY.md) (once; they are kept in
`~/.cache/bc250-xefg-testers`). It saves every game file it will replace, then places OptiScaler, the FSR 4 DLL,
FreeFG's `libxess_fg.dll` and Intel's runtime (as `bc250_xefg_original.dll`) beside the game. It writes the launch
settings into the game's entry in Steam, Heroic or Lutris. You copy no launch command and need no wrapper script.
Existing launch options and other wrappers stay in place. The launcher must be closed while Setup writes or restores
those settings, so it does not overwrite them; Setup waits for that.

**Games that already have OptiScaler:** it must be the 10.0.0-pre1 nightly of 4 or 29 September 2026. Restore or update
any other OptiScaler first. A game with a custom DLL path in `OptiScaler.ini`, symlinked game files or another proxy DLL
needs manual integration.

**Command line** (in the extracted folder):

```sh
python3 install.py preview '/path/to/Game.exe'                    # what would change; downloads, changes nothing
python3 install.py install '/path/to/Game.exe'                    # Automatic input
python3 install.py install '/path/to/Game.exe' --fg-input dlssg   # or upscaler, fsrfg, fsrfg30
python3 install.py install '/path/to/Game.exe' --route native     # the game's own XeSS FG
python3 install.py status '/path/to/Game.exe'
python3 install.py restore '/path/to/Game.exe'
python3 install.py doctor                                          # Check system
```

## Using it

- **Frame generation on or off:** in the game's settings, or in OptiScaler's menu (press **Insert**, **Frame
  Generation**, **Active**). The multiplier stays at 2×. This build has no 3×/4× and no generated-frame scaling:
  generated frames always match the output resolution.
- **Pick the right display mode.** XeFG does not interpolate in exclusive fullscreen. On OptiScaler inputs the installer
  keeps the game borderless; with native XeSS FG, choose borderless or windowed in the game.
- **Mind the refresh rate.** When real FPS × 2 would exceed the display's refresh rate, the output stops at the refresh
  rate and the game's own frame rate drops to match, which adds latency without adding smoothness.
- **Latency:** generated frames make motion smoother but do not make the game respond faster. Even pacing holds each
  frame a few milliseconds until its turn.
- **Steam's screensaver:** in Game Mode, Steam starts its screensaver behind a running game after the idle timeout
  (5 minutes by default). Every 20 seconds it cross-fades for 2 seconds and takes GPU time, which shows as bursts of VRR
  flicker. Controller input resets the timer, so you meet it in long cutscenes or when you leave a game running. Set
  the screensaver timeout to **Never**, or install the optional helper (see [Extras](#extras)).

## Restore and uninstall

**Restore** (Setup, or `install.py restore`): close the game and its launcher first. Restore puts back every file
Setup replaced and removes what it added. It also removes the launch settings Setup wrote and undoes recipe changes to
the game's settings, key by key. Some changes stay:

- Launch options you added after installing.
- Settings you changed yourself.
- A file that changed after installation, for example a DLL that a game update replaced: it is kept and named. Its
  pre-installation copy stays in the backup folder.

The backup folder sits in the game folder (`.bc250-xefg-experimental`, renamed with a `-restored-…` suffix after
Restore). It also receives FreeFG's logs.

Use Restore before you change a game's input, hand its files to another installer or mod manager, or install another
build of FreeFG. If a game update replaces FreeFG's files, **Status** reports it. Then Restore, and install again.

**Uninstall completely:** Restore every game. Run `uninstall.sh` in any extra you installed. Then delete the extracted
folder, the download cache `~/.cache/bc250-xefg-testers` and, once you no longer need the backups, each game's
`.bc250-xefg-experimental-restored-…` folder.

## Troubleshooting

**Status** checks the installation and summarises the last session's log. The logs are in the game folder, beside the
`.exe`:

| Log | What to look for |
| --- | --- |
| `BC250-MFG.log` | `MFG proxy ready` means Intel's runtime was found and verified. `bc250_xefg_original.dll is missing or is not the pinned Intel XeFG runtime` means XeFG is unavailable in this game: run Install again. |
| `BC250-XeFG-fast.log` | `FAST_OWNER` and `MODEL_SEALED` mean the accelerated path is active, and so does `PRIVATE GAME TRIAL scoped prepared-model and Winograd path installed` (fixed text from the project's development, compiled into the DLL). `FAST_FALLBACK …` or `FAST_SKIP …` give the reason Intel's shaders are used instead. A `FAIL` line means FreeFG closed the game, because the runtime did something it does not recognise. Please report that. |
| the game's standard error output (for Steam: launch option `PROTON_LOG=1 %command%`, then `$HOME/steam-<appid>.log`) | `BC250_PACE on …` (pacing active), `BC250_PACE holding: XeFG generates frames`, `BC250_PACE passing presents through` |

| Symptom | What to try |
| --- | --- |
| The frame rate does not go up; only real frames are shown | Turn the game's frame generation on (DLSS FG and FSR FG inputs); check that the game is not in exclusive fullscreen; check `BC250-XeFG-fast.log`. |
| Uneven frame pacing or VRR flicker | Give gamescope realtime priority ([Extras](#extras)); rule out Steam's screensaver; stay below the refresh rate; check the `BC250_PACE` lines. |
| `Existing OptiScaler must be the 10.0.0-pre1 nightly …` | Restore or update the game's OptiScaler first. |
| `Cannot download …` | The first installation needs internet, or the file already in `~/.cache/bc250-xefg-testers`. |
| `version.dll is occupied` or `An existing XeSSMFG folder …` | Another mod, or a test build of this project from before its public release, occupies those files: restore it with its own installer first. |

**Switches** (launch options before `%command%`, for troubleshooting only; Setup keeps them on reinstall and Restore
leaves them in place):

| Launch option | Effect |
| --- | --- |
| `BC250_XEFG_DISABLE=1` | Intel's original shaders instead of the accelerated path. Presents then pass through unpaced. |
| `BC250_XEFG_PACE=0` / `=1` | Output pacing off / hold every present, also while XeFG is not generating. |
| `BC250_XEFG_PACE_NUDGE=0` / `=1` | The X nudge for stock gamescope off / on. |
| `BC250_XEFG_PACE_QUEUE=app` | Present from the game's own queue even when a compute queue exists. |
| `BC250_XEFG_ANY_GPU=1` | The accelerated path on a GPU other than the BC-250 (untested; see [Other GPUs](#other-gpus)). |

The DLL also reads `BC250_CAPTURE_TAG_FRAMES=1`, a switch for latency measurements: it turns on the debug marker that
Intel's XeFG API draws on generated frames, so that capture tools can tell them apart. Leave it unset for play.

When you report a problem, send the two logs, the game, Proton and Mesa versions, resolution, HDR on or off, the
upscaler mode and the frame-generation input. Logs alone do not show whether the picture or the pacing looked right, so
describe what you saw.

## Other GPUs

Everything is built and measured on the BC-250. On another GPU under Proton, Setup installs the same files, and:

- **By default** FreeFG passes everything through to Intel's runtime: Intel's shaders, generated frames at output
  resolution. In this build the pacing layer gets no generation signal on that path, so presents are not held (plain
  XeFG pacing). `BC250-XeFG-fast.log` says `FAST_FALLBACK requires BC250 adapter (this one is vvvv:dddd; …)`.
- **With `BC250_XEFG_ANY_GPU=1`** the accelerated path runs on that GPU too. **Nobody has tested this.** FreeFG
  checks what Intel's runtime hands it and closes the game (a `FAIL` line) rather than show frames it cannot vouch for.
  RDNA 2 and newer GPUs have the int8 dot-product instructions that Intel's shaders use, so it is not known whether
  FreeFG's shaders are faster there. On RDNA 1 they replace work the driver emulates, as on the BC-250.
- The FSR 4 DLL that Setup installs is a BC-250 build; on other GPUs it is untested.
- Intel GPUs are not a target: FreeFG accelerates only contexts that generate one frame per real frame.

## Extras

Optional host helpers in `extras/`, each with its own README and an `uninstall.sh`:

- **`gamescope-cap-sys-nice`** gives gamescope realtime priority (`CAP_SYS_NICE`), which most distributions other than
  SteamOS leave out. Without it gamescope's composition and page flips queue behind the game's GPU work, which shows as
  uneven VRR refresh. It asks for `sudo` once. On pacman systems it adds a hook that sets the capability again after
  gamescope updates. Side effect: gamescope then ignores `LD_PRELOAD` and drops it for the programs it starts (see that
  README).
- **`steam-screensaver-in-game`** keeps Steam's screensaver timeout at Never only while a game runs and puts your value
  back afterwards. It needs Steam's local DevTools port (see [SECURITY.md](packaging/public/SECURITY.md)).

## FAQ

**Is this made by Intel, AMD or NVIDIA?** No. FreeFG is an independent project that works with their software.

**Why only 2×?** Intel's runtime generates at most one frame per real frame on GPUs other than Intel's, as Intel
documents. FreeFG keeps that limit.

**Does it change Intel's DLL?** No. Setup downloads Intel's `libxess_fg.dll` from a pinned source and checks its SHA-256.
FreeFG's DLL verifies it again before loading it, unmodified. While the runtime runs, FreeFG carries out part of
its GPU work with its own shaders: [ARCHITECTURE.md](packaging/public/ARCHITECTURE.md) lists every such change. Intel's licence terms
for the runtime apply to you as its user; see [NOTICE.md](NOTICE.md).

**Are the generated frames really the same?** In synthetic XeFG scenes, yes, bit for bit, wherever that was compared
([MEASUREMENTS.md](packaging/public/MEASUREMENTS.md) gives the exact scope). The shaders are written so that every intermediate sum is
an integer that FP32 holds exactly, so rounding cannot differ. In games, nothing has been compared pixel by pixel.

**Why does Setup download files instead of shipping them?** Intel's runtime, AMD's FSR 4 DLL, OptiScaler's support
files and NVIDIA's DLSS helper belong to their publishers and come from their own release locations, checked by hash.
The download contains only this project's files and the OptiScaler build it needs.

**Why a modified OptiScaler?** The OptiScaler nightly this build is based on (29 September 2026) can deadlock at
start-up in some Streamline games: CONTROL Resonant hung on about half of its starts. The bundled build reverts the
upstream change behind that and adds a few small fixes. Its source is linked in [NOTICE.md](NOTICE.md). Its version string (in OptiScaler's log and
menu) ends in `(BC250 private)`: fixed text of that build, which does not mean that its source is private.

**Does it work on Windows, on the Steam Deck, or with DirectX 11 or Vulkan games?** Windows: no. Steam Deck: untested
(not a BC-250). DirectX 11 and Vulkan games: no.

**Does it send anything anywhere?** No. See [PRIVACY.md](packaging/public/PRIVACY.md).

## Known limitations

- 2× only; no generated-frame scaling.
- Qualified only on the BC-250, under Proton in Steam Game Mode. This build has run in main menus and benchmarks, not
  yet in gameplay (see [Status](#status)).
- Frame pacing works only under gamescope. With Intel's shaders (`BC250_XEFG_DISABLE=1`, or another GPU) this build does
  not pace presents.
- Only the first XeFG context of a game process is accelerated.
- Deadzone: Rogue does not generate frames yet; Deep Rock Galactic needs an upscaler chosen in its own menu first.
- If FreeFG meets a frame-generation graph it does not know, for example after an update to Intel's runtime pin, it
  closes the game rather than show frames it cannot vouch for.
- Sandboxed launchers (Flatpak Steam, Flatpak Heroic) are not qualified.

## Rights holders

If you hold rights in software that FreeFG works with, for example Intel, AMD or NVIDIA, and have a concern about
this project, open an issue at <https://github.com/daniel-h-0/freefg/issues>, or raise it privately through the
repository's **Security** tab: **Report a vulnerability** (GitHub's private reporting,
<https://github.com/daniel-h-0/freefg/security/advisories/new>) reaches only the maintainers. GitHub's own
[DMCA process](https://docs.github.com/en/site-policy/content-removal-policies/dmca-takedown-policy) is open to rights
holders too. We will answer promptly, and we will take the release down on a credible request.

## More

[ARCHITECTURE.md](packaging/public/ARCHITECTURE.md) (how it works) · [MEASUREMENTS.md](packaging/public/MEASUREMENTS.md) (numbers and their scope) ·
[PRIVACY.md](packaging/public/PRIVACY.md) (downloads) · [NOTICE.md](NOTICE.md) (licences) · [BUILDING.md](packaging/public/BUILDING.md) (build from source) ·
[CHANGELOG.md](packaging/public/CHANGELOG.md) · [CONTRIBUTING.md](packaging/public/CONTRIBUTING.md) · [SECURITY.md](packaging/public/SECURITY.md)

FreeFG's own code is MIT-licensed. Other components keep their own licences; see [NOTICE.md](NOTICE.md).
