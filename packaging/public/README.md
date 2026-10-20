# FreeFG

**Faster XeSS frame generation for the AMD BC-250 on Linux.** FreeFG works with Intel XeSS Frame Generation (XeFG)
in DirectX 12 games running under Proton. Intel's own runtime, downloaded unmodified, still generates the frames: one
generated frame for every real frame (2×), Intel's limit for GPUs other than its own. FreeFG runs part of the
runtime's GPU work with this project's own shaders, which are faster on the BC-250 and give the same pixels, and it
paces the output evenly for VRR displays. It also sets up upscaling with a BC-250 build of AMD FSR 4, through
OptiScaler, or, if you choose it, with HelixSR, a separate project by lonewolf0622
([Upscaler: FSR 4 or HelixSR](#upscaler-fsr-4-or-helixsr)). If you add MFG Unlocker by dashdogy, a separate tool that
lifts Intel's limit, FreeFG keeps running its own shaders at 3× and 4× wherever Intel's runtime still runs Intel's
([3× and 4× with MFG Unlocker](#3-and-4-with-mfg-unlocker)); FreeFG does not ship MFG Unlocker.

FreeFG is an independent project. It is not affiliated with, endorsed by or supported by Intel, AMD, NVIDIA, ASRock,
Valve or the OptiScaler project. Intel, XeSS and Xe are trademarks of Intel Corporation; AMD, FidelityFX and FSR are
trademarks of Advanced Micro Devices, Inc.; NVIDIA and DLSS are trademarks of NVIDIA Corporation; Steam is a trademark
of Valve Corporation. They are used here only to say what FreeFG works with.

## In plain words

- **What you get:** in a supported game, frame generation at 2× with about a fifth more frames per second than XeFG
  gives with Intel's own shaders on the same BC-250 (Cyberpunk 2077, 1440p, FSR 4 Performance: 103.3 instead of 85.3
  FPS, measured with 0.9.0, which runs the same shaders at 2×; see [MEASUREMENTS.md](MEASUREMENTS.md) for how that was
  measured and what it does not cover).
- **What stays the same:** the generated images. In the synthetic tests so far they are bit-for-bit the same as with
  Intel's shaders wherever that was compared ([MEASUREMENTS.md](MEASUREMENTS.md) gives the exact scope).
- **What it does not do:** it does not raise Intel's limit of one generated frame per real frame on GPUs other than
  Intel's itself. For 3× and 4× you add a separate tool that does, at your own choice; FreeFG does not ship it.
  FreeFG does not modify Intel's DLL, does not replace your graphics driver and does not run on Windows.
- **How it works**, in one paragraph: FreeFG places a small `libxess_fg.dll` where the game or OptiScaler loads
  Intel's runtime. It passes every call on to Intel's unmodified runtime, which sits beside it, and while the runtime
  runs it substitutes some of the runtime's GPU shaders with this project's own. A Vulkan layer holds each finished
  frame until its turn so that VRR displays show them evenly. [ARCHITECTURE.md](ARCHITECTURE.md) describes exactly
  what is replaced and what is not.

![Cyberpunk 2077 at 2× on an AMD BC-250, 2560×1440, FSR 4 Performance, native XeSS frame generation. Headless: XeFG with Intel's shaders 85.31 FPS (SDR, 15 October 2026) and FreeFG 103.28 FPS (SDR, 16 October), +21.1% measured a day apart; FreeFG in HDR10 101.58 FPS. On an LG G5 TV at 120 Hz with VRR: FreeFG 99.29 FPS in SDR and 97.24 FPS in HDR10 (18–19 October). Headless and TV figures are not comparable with each other.](../../docs/assets/cyberpunk-2x-fps.svg)

## Status

**1.0.0, proof-of-life qualified.** It is for the AMD BC-250 only. Proof-of-life means that this build was checked
without a GPU and then run on one BC-250, one short start per question. It has not been through the longer
qualification that 0.9.0, the 2×-only pre-release, had; [MEASUREMENTS.md](MEASUREMENTS.md) describes those runs, which
were made with 0.9.0's build. FreeFG 1.0.0 has been checked as follows:

- **Build:** reproducible byte for byte from the source tree on the pinned toolchain ([BUILDING.md](BUILDING.md)).
- **Static check:** every shader in the package is compiled from this project's HLSL source, and the check finds no
  Intel file, none of the shader programs of Intel's runtime and none of Intel's weight tables in it
  ([NOTICE.md](NOTICE.md)).
- **Installer:** unit tests pass, and an offline install and Restore in a throwaway game folder return the folder to
  its original files.
- **Wine loader check:** without a GPU, the DLL loads under Wine and forwards to Intel's runtime. It refuses a missing or
  altered runtime. With a stand-in module hooking eight of Intel's entry points, every call reaches that module once,
  with the caller it would see without FreeFG, and only OptiScaler's own contexts are accelerated; a unit test of
  this bookkeeping runs too.
- **Synthetic scenes, BC-250:** at 2×, 1.0.0's generated images are bit-identical to 0.9.0's (whose images match
  Intel's shaders where that was compared) in three configurations: SDR at 1440p, HDR10 with pixel motion vectors at
  1440p, and SDR at 4K, five images each. The proxy verified the network's coefficient buffers, and the runtime reported
  2 frames per present.
- **Echo Point Nova (Steam, OptiScaler's frame generation), BC-250**, installed by the installer of this build's package,
  whose OptiScaler DLL was then replaced by hand with this release's (the same file the 1.0.0 package ships):
  - 2×: accelerated, 2 frames per present.
  - With MFG Unlocker v1.6.0 and `XeFGModel=default`: 4× at 4 frames per present and 3× at 3 frames per present, both
    on FreeFG's shaders beside MFG Unlocker. One of the two 3× starts ended during start-up with no error in any log;
    the next start worked.
  - With MFG Unlocker's own model (no `XeFGModel` key): 3× at 3 frames per present, accelerated.
  - With HelixSR 2.0.0 as the upscaler: HelixSR's network ran, and XeFG at 2× was accelerated at 2 frames per present.
    OptiScaler's FSR 4 settings did not touch HelixSR's DLL. Switching back to FSR 4 worked.
- **Cyberpunk 2077 (GOG through Heroic, the game's own XeSS frame generation), BC-250, headless:** the built-in
  benchmark ran accelerated at 2.0 presents per game frame and 102.08 FPS. That is one run, not compared with 0.9.0 on
  the same day (0.9.0 measured 103.28 FPS on 16 October).
- **Restore** returned both game folders exactly as they were.
- **CONTROL Resonant (DLSS frame generation as the input), BC-250, with this release's OptiScaler build:** 32 of 32
  starts reached the game, none hung; 2 presents per game frame in the 12 starts where that was measured.
- **Not checked with this build:** same-day speed comparisons (1.0.0 against 0.9.0 at 2×, FreeFG against MFG
  Unlocker alone at 3× and 4×); 3× and 4× on a display with VRR, and the picture at 3× and 4×; changing the frame count
  while a game runs, and OptiScaler's Dynamic MFG; HDR10 at 3× and 4×; a game's own XeSS frame generation beside MFG
  Unlocker; games without a recipe; Steam or Heroic installed as Flatpaks; longer play sessions.

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
| Network | internet access the first time you install: about 110 MB for a fresh setup, 59 MB more for a DLSS input in a game whose own `nvngx_dlss.dll` OptiScaler does not find ([PRIVACY.md](PRIVACY.md)) | |

A patched Mesa that turns the compute queue on needs a kernel with the matching BC-250 fixes. Never use such a Mesa
on a kernel without them; **Check system** warns about that combination.

**Games:** 64-bit DirectX 12 games under Proton, launched from Steam, Heroic or Lutris, with an input that OptiScaler
supports (see [Game compatibility](#game-compatibility)). DirectX 11 and Vulkan games are not supported. Game folders
must have ASCII-only paths. Do not use FreeFG in online games with anti-cheat. It loads DLLs into the game process,
and anti-cheat software may treat that as tampering; Setup refuses games that ship anti-cheat files.

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

Every other game gets a verdict from Setup's **Check** before anything is installed: see
[Game compatibility](#game-compatibility).

## Game compatibility

FreeFG cannot work in every game, and more recipes would not change that. XeFG builds each generated frame from the
game's motion vectors and depth. FreeFG gets those only from an upscaler or frame-generation SDK that OptiScaler hooks
(DLSS, FSR 2, FSR 3.x, XeSS, DLSS FG, FSR 3.1 FG) or from the game's own XeSS FG, and only in DirectX 12. A game without
one of those has nothing to generate from. On the maintainers' BC-250 library of 85 installed games, 22 have an input
FreeFG can use (19 with a recipe; 3 found automatically, not yet checked in a game), 2 more ship only the DLSS DLL
that Unity bundles while their own code never uses DLSS (refused unless you accept), 34 have no upscaler input, and 27
cannot run FreeFG at all (12 native Linux builds, 6 32-bit games, 8 without DirectX 12, 1 tool).

What Setup promises instead:

1. **Every game gets a verdict before anything is written**, offline, with its reason and how sure the check is.
2. **A game with an input the check finds gets an automatic setup** (executable, route, input, DirectX 12 switch and
   OptiScaler settings) from the most trusted source that knows the game. Setups not yet checked in that game are
   labelled so: only the verified recipes above were played on a BC-250.
3. **Known-broken cases are refused** before anything is downloaded, and so is anything in the game folder that Install
   would refuse (another mod, an earlier installation). Restore puts back every byte and launcher field it changed.
4. **Verdicts improve without telemetry**: after a run, Check reads the game's own logs; a report you paste into a GitHub
   issue can become a community recipe.

| Verdict | Meaning |
| --- | --- |
| Verified on BC-250 | A recipe from the table above: its input, settings and launch option are applied. |
| Community-reported on BC-250 | A reviewed recipe from other BC-250 owners, not yet reproduced by the maintainers; applied and labelled. |
| Automatic, guided by the OptiScaler wiki | No recipe; the [OptiScaler wiki](https://github.com/optiscaler/OptiScaler/wiki) identifies the game and supplies a DirectX 12 launch option, rules out an input it reports broken, or one of six promoted fixes (below). |
| Automatic (no recipe) | Detection found a 64-bit DirectX 12 executable with an input: native XeSS FG beside the executable, else OptiFG from the game's upscaler, else the game's own frame generation as input. |
| Not supported | The reason and the way forward (below). |

Any verdict can come with **a step for you**: turn on the game's frame generation, select DirectX 12 in the game, or
check that OptiScaler loads where the wiki says the game needs another proxy name. Setup shows the steps before you
confirm Install.

**Who decides what.** Your own choices win (a value you set in `OptiScaler.ini`, an input you pick, your launch
options). Then, in order: a verified recipe; OptiScaler's own built-in fixes for the game (Setup never writes a key one
of them sets); a community recipe; six OptiScaler wiki fixes promoted for automatic use (reviewed by an agent for the
maintainers and awaiting a maintainer's confirmation; applied only where the game is identified by its launcher ID or
by its executable together with its title, which today only FINAL FANTASY VII REBIRTH and Soulstice can reach); the
wiki's reports of a broken input; detection; the installer's defaults. Everything else the wiki says is shown with its condition
checked against your setup (AMD, Linux, DirectX 12, XeFG output, FSR 4): applies, does not apply, or depends on
something only you can see in the game. Most wiki reports come from Windows PCs with other GPUs; FreeFG uses the
wiki's facts and links to its pages, and copies no page text.

| Refused | Why | Way forward |
| --- | --- | --- |
| `anticheat` | The game ships anti-cheat files (Easy Anti-Cheat, BattlEye, GameGuard, XIGNCODE3, EA Javelin, ACE, mhyprot, EQU8, PunkBuster, Vanguard). | None. |
| `native-linux` | Steam installed the Linux version. | Force a Proton version in the game's Compatibility properties, let Steam download the Windows version, Check again. |
| `32bit` | XeFG and FreeFG are 64-bit only. | None. |
| `api-vulkan`, `api-opengl`, `api-dx11`, `no-dx12` | No DirectX 12 path. DirectX 11 games stay refused until one is qualified (OptiScaler's DX11-to-DX12 bridge gave a black screen under this Proton stack). | None. Soft when you chose the input yourself: detection can miss what you know. |
| `no-input` | DirectX 12, but no upscaler or frame-generation SDK. | None inside FreeFG. Soft when you chose the input yourself. |
| `input-unconfirmed` (soft) | Unity game whose only DLSS evidence is the DLL Unity's NVIDIA module bundles; the game's code never names DLSS. | **Install anyway** only if the game's graphics menu offers DLSS. |
| `wrong-exe` | The executable is a launcher stub. | Choose the executable Check names. |
| `no-launcher` | No Steam, Heroic or Lutris entry starts the executable. | Add the game to one of them. |
| `shared-entry` | The launcher entry already starts an installation in another folder. | Restore that installation first. |
| `ge-optiscaler` | GE-Proton is told to place its own OptiScaler or upscaler DLLs (`PROTON_USE_OPTISCALER`, `PROTON_*_UPGRADE`). | Remove the variable from the launch options. |
| `protonfix-api` (soft) | GE-Proton's own fix for the game switches it off DirectX 12. | **Install anyway** adds `PROTONFIXES_DISABLE=1` to the launch options, which turns off all of GE-Proton's fixes for that game (Check names what else the fix does); Restore removes it. |
| `wiki-not-working` (soft) | The OptiScaler wiki lists the game as not working, matched by launcher ID or executable and title (a title-only match is a note). | **Install anyway** if you want to try. |
| `installed`, `xessmfg`, `version-dll`, `existing-files`, `existing-optiscaler`, `optiscaler-paths`, `helixsr-installer`, `recipe-exe`, `ascii-path` | Before Install, not about the game: an installation not yet restored, another frame-generation mod, an OptiScaler setup this package does not take over, HelixSR installed by its own installer, the wrong executable of a verified game, a folder path that is not ASCII. Check shows the plan Install will follow once this is resolved. | What Check names: Restore, remove the other mod (HelixSR: its own uninstaller), or choose the other executable. |

**Check a game** (Setup: **Check**; it reads, writes nothing and uses no network):

```sh
python3 install.py check '/path/to/Game.exe'            # verdict, plan, your steps, the wiki's notes, the last run
python3 install.py check '/path/to/Game.exe' --report   # plus a text for a GitHub issue, without paths or user name
python3 install.py check --all                           # one line per installed Steam and Heroic game
python3 install.py install '/path/to/Game.exe' --accept protonfix-api   # a soft refusal, accepted
python3 install.py install A.exe B.exe --accept 'protonfix-api=A.exe'    # accepted for one of the games only
```

A game that works, or does not, is worth a report: see [CONTRIBUTING.md](CONTRIBUTING.md#game-recipes).

## Install

1. Extract the release archive and run **`Start-freefg.sh`** in Desktop Mode. It opens Setup.
2. **Add games:** select each game's rendering `.exe`. For Unreal Engine games that is often the one in
   `Binaries/Win64`, not the launcher in the game's root folder.
3. **Install**, then choose the frame-generation input. **Automatic per game** is recommended: it uses the recipe's input
   where there is one, else native XeSS FG where the game ships it, else OptiFG, and lists each game's verdict and any
   step it needs from you. Then choose the upscaler: **FSR 4** (the default) or **HelixSR**
   ([below](#upscaler-fsr-4-or-helixsr)). If the game or its launcher is still running, Setup names it and waits until
   you close it. Install games that need different explicit inputs separately.
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

**What Setup does:** it downloads and checks the files listed in [PRIVACY.md](PRIVACY.md) (once; they are kept in
`~/.cache/bc250-xefg-testers`). It saves every game file it will replace, then places OptiScaler, the FSR 4 DLL (or
HelixSR's), FreeFG's `libxess_fg.dll` and Intel's runtime (as `bc250_xefg_original.dll`) beside the game. It writes
the launch settings into the game's entry in Steam, Heroic or Lutris. You copy no launch command and need no wrapper
script. Existing launch options and other wrappers stay in place. The launcher must be closed while Setup writes or
restores those settings, so it does not overwrite them; Setup waits for that.

**Games that already have OptiScaler:** it must be the 10.0.0-pre1 nightly of 4 or 29 September 2026. Restore or update
any other OptiScaler first. A game with a custom DLL path in `OptiScaler.ini`, symlinked game files or another proxy DLL
needs manual integration.

![What Setup changes in a game, recorded in a live install of FreeFG 0.9.0 (Echo Point Nova, Steam, OptiFG input); 1.0.0 places the same files plus five shaders. In the game folder: OptiScaler as dxgi.dll (an OptiScaler the game already has keeps its own name) and OptiScaler.ini, which Setup writes; OptiScaler's support files and FSR 4 in OptiScaler/ (with HelixSR chosen, HelixSR's DLL takes FSR 4's place, with helixsr.ini beside it); FreeFG's libxess_fg.dll; Intel's unmodified XeFG runtime as bc250_xefg_original.dll and XeLL as libxell.dll; NVIDIA's nvngx_dlss.dll only for a DLSS input where the game has none; BC250-XeFG/ with the pacing layer, 33 own shaders with 9 control files (0.9.0's 2× package, where the layout was recorded, had 28), and settings; and the backup folder .bc250-xefg-experimental that Restore reads. In the launcher entry: WINEDLLOVERRIDES gains OptiScaler's DLL, plus VK_LAYER_PATH, VK_INSTANCE_LAYERS, XEFG_WAVE_CONFIG and VKD3D_CONFIG=no_staggered_submit.](../../docs/assets/setup-file-layout.svg)

**Command line** (in the extracted folder):

```sh
python3 install.py preview '/path/to/Game.exe'                    # what would change; downloads, changes nothing
python3 install.py install '/path/to/Game.exe'                    # Automatic input
python3 install.py install '/path/to/Game.exe' --fg-input dlssg   # or upscaler, fsrfg, fsrfg30
python3 install.py install '/path/to/Game.exe' --route native     # the game's own XeSS FG
python3 install.py install '/path/to/Game.exe' --upscaler helixsr # HelixSR instead of FSR 4 (see below)
python3 install.py configure '/path/to/Game.exe' --upscaler fsr4  # switch an installed game (fsr4 or helixsr)
python3 install.py status '/path/to/Game.exe'
python3 install.py restore '/path/to/Game.exe'
python3 install.py helixsr                                         # HelixSR: download it, or say what is missing
python3 install.py doctor                                          # Check system
python3 install.py check '/path/to/Game.exe'                      # compatibility verdict; changes nothing
```

## Upscaler: FSR 4 or HelixSR

FSR 4 (the BC-250 build, RC11) is the default upscaler. **HelixSR** is the alternative. It is a separate project by
**lonewolf0622**, <https://github.com/lonewolf0622/HelixSR>, under its own licence (the HelixSR Freeware License). Its
source is not published. HelixSR runs NVIDIA's DLSS Model E upscaling network as Direct3D 12 compute shaders, without
an NVIDIA GPU, and it is developed and tested on the BC-250. FreeFG ships none of it. All credit for HelixSR belongs
to its author. Report HelixSR's own problems at its [issues page](https://github.com/lonewolf0622/HelixSR/issues), with
its `helixsr.log`, and FreeFG's problems here.

Frame generation is the same with either upscaler: XeFG, as described above. HelixSR has its own DLSS frame generation;
FreeFG keeps it off.

**First use:**

1. In Setup, choose **HelixSR (by lonewolf0622)** as the upscaler (Install, or **Upscaler** for installed games). If
   HelixSR is not on your computer yet, Setup offers to download HelixSR's complete, official release from its GitHub
   releases (137 MB, pinned by version and SHA-256), and unpacks it as it is into
   `~/.cache/bc250-xefg-testers/helixsr/`. `python3 install.py helixsr` does the same.
2. Build it once with **HelixSR's own setup**, in a terminal. Setup shows the command:

   ```sh
   cd ~/.cache/bc250-xefg-testers/helixsr/HelixSR-2.0.0 && ./helixsr-setup.sh --no-fg
   ```

   HelixSR's setup asks you before it downloads NVIDIA's DLSS DLL, and it builds the network on your computer. That
   network is NVIDIA's: it stays on your computer, and HelixSR's licence says not to share it. `--no-fg` builds the
   upscaler only. When the setup then lists your games, press **Ctrl+C** at the first game question (or answer **n**
   for each): it changes no game until its last question, and FreeFG places HelixSR in the games you choose. Do not
   just press Enter there: Enter installs HelixSR its own way, and in a game set up by FreeFG that puts HelixSR
   Scaler in place of FreeFG's OptiScaler.
3. Choose HelixSR in Setup again. In the game, choose the upscaler as you would for FSR 4.

A HelixSR you already unpacked elsewhere is found in your home folder or its `Downloads` or `Applications` folder (a
folder named `HelixSR…`), or name it once with `--helixsr /path/to/HelixSR-2.0.0` (with `install.py helixsr`, `install`
or `configure`; it is remembered). FreeFG uses only an official HelixSR release it knows (2.0.0); with only another
version on your computer, Setup and `install.py helixsr` offer to download 2.0.0 instead, and a newer one needs an
updated FreeFG.

**What is placed:** the DLL HelixSR's setup built, as `OptiScaler/amd_fidelityfx_upscaler_dx12.dll` (where FSR 4 would
go: OptiScaler runs it through its FidelityFX upscaler interface), and `OptiScaler/helixsr.ini`, which turns HelixSR's
own DLSS frame generation off. Nothing else of HelixSR's goes into the game. FreeFG never changes HelixSR's files,
never downloads NVIDIA's files for it and never builds its network.

**Switching:** Setup's **Upscaler** (or `install.py configure GAME.exe --upscaler fsr4|helixsr`) swaps the DLL in place.
**Status** names the upscaler a game uses and where HelixSR's log is; **Check system** says whether HelixSR is ready.
Restore removes exactly what was placed, whichever upscaler the game has then. If you edited `helixsr.ini`, Restore and a
switch to FSR 4 keep your edited copy in the game's backup folder, and the next HelixSR installation starts from it.
Restore also moves `helixsr.log` into the game's backup folder. Use Restore, not HelixSR's uninstaller, for games
FreeFG installed.

## Using it

Under gamescope the pacing layer hands frames to the display evenly. Without it, XeFG's real and generated frames
alternate between short and long intervals, which a VRR display shows as uneven motion:

![Frame pacing on an LG G5 TV with VRR at 2×, Cyberpunk 2077, 2560×1440, SDR: intervals between display commits. Without pacing (29 September 2026, earlier private builds, no compute queue), the intervals alternate between about 5 and 16 ms (5th to 95th percentile 4.8 to 16.4 ms, 577 intervals over 1.5 times their run's median in 60 seconds). In the same session, a layer that paces from the game's queue gives 9.0 to 11.1 ms with 3 such intervals in 90 seconds. FreeFG 0.9.0's proxy, layer and shaders with a compute queue (18–19 October): 8.9 to 11.0 ms, 7 such intervals in 120 seconds, none over 25 ms.](../../docs/assets/vrr-pacing.svg)

- **Frame generation on or off:** in the game's settings, or in OptiScaler's menu (press **Insert**, **Frame
  Generation**, **Active**). The multiplier is 2×; for 3× and 4× see
  [3× and 4× with MFG Unlocker](#3-and-4-with-mfg-unlocker). This build has no generated-frame scaling: generated
  frames always match the output resolution.
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

## 3× and 4× with MFG Unlocker

FreeFG generates 2× on its own. **MFG Unlocker** (<https://github.com/dashdogy/MFG-Unlocker>, MIT licence; its DLL
also contains programs derived from Intel's XeSS SDK, under Intel's terms) is a separate tool that lifts Intel's limit
on GPUs other than Intel's, up to 6×, as an OptiScaler plugin. FreeFG does not ship it, link it into its own code or
change it, and its authors support it. Whether to use it, and Intel's licence terms for a runtime whose frame limit
another tool lifts, are your decision.

With it, FreeFG notices that another module has hooked Intel's runtime. It then passes Intel's entry points the
callers MFG Unlocker expects, so MFG Unlocker treats OptiScaler's frame generation as its own route, and on
OptiScaler's frame generation it keeps its own shaders on every part of the runtime's GPU work that is still Intel's,
at the frame count the runtime runs. Where it meets work it has not verified, it steps aside for that game session
(MFG Unlocker's and Intel's shaders run) instead of ending the game. `BC250-XeFG-fast.log` then says `FAST_ASIDE` and
why. A game's own XeSS frame generation is left to MFG Unlocker entirely (below).

1. Install FreeFG for the game as usual (Setup, **Install**) and check 2× once.
2. Close the game. Download `MFGUnlocker-v1.6.0.zip` from that project's Releases page and check it against its
   `SHA256SUMS.txt`.
3. Rename `MFGUnlocker.dll` to `MFGUnlocker.asi` and put it in `OptiScaler/plugins/` beside the game's `.exe` (Setup
   created that folder). Do not install it under a DLL name such as `dxgi.dll`: that name is OptiScaler.
4. In `OptiScaler.ini` beside the game's `.exe`, check that `LoadAsiPlugins=true` under `[Plugins]`: Setup sets it in
   the OptiScaler setups it creates (it loads the `OptiPatcher.asi` that Setup placed there); in an OptiScaler setup
   that was there before, set it yourself. Leave `FGOutput=xefg` under `[FrameGen]`.
5. Choose MFG Unlocker's model, under `[XeFG]` in the same file:
   - `XeFGModel=default` runs Intel's 2× model at every frame count. All of the network is then Intel's, so
     FreeFG's shaders run on all of it. MFG Unlocker's authors found that this model places the outer generated
     frames at the wrong points in time at 6×, which smears them; at 3× and 4× this has not been checked.
   - Without the key (MFG Unlocker's default), MFG Unlocker runs its own port of Intel's multi-frame model, with its
     own programs in place of five of the network's. FreeFG keeps its shaders on the rest where it recognises the
     work, and steps aside otherwise.
6. Start the game, press **Insert**, and set the frame count (3× or 4×) under Frame Generation in OptiScaler's menu.
   Setup and the installer always write 2× (`InterpolationCount=1`); OptiScaler saves the count you choose. OptiScaler's
   frame limit counts output frames: at 4×, a 117 FPS limit leaves about 29 real frames per second.
7. Back to plain 2×: remove `MFGUnlocker.asi` from `OptiScaler/plugins/` and set the frame count back to 2×. Leave
   `LoadAsiPlugins` on: `LoadAsiPlugins=false` also stops OptiPatcher, which some games need for their upscaler inputs.

Checked on one BC-250 in Echo Point Nova (Steam, OptiScaler's frame generation), one start each: with
`XeFGModel=default`, 3× and 4× ran on FreeFG's shaders at 3 and 4 frames per present; with MFG Unlocker's own model,
3× ran accelerated at 3 frames per present. One of two 3× starts with `XeFGModel=default` ended during start-up with no
error in any log; starting the game again worked. The picture at 3× and 4×, pacing on a VRR display at those counts,
HDR10 and changing the count while the game runs were not checked ([Status](#status)).

Frame pacing: MFG Unlocker paces frame starts on AMD GPUs itself. FreeFG's pacing layer holds presents while XeFG
generates, at every frame count, from the frames the runtime reports presented.

**Native XeSS FG games** (for example Cyberpunk 2077): MFG Unlocker works only where OptiScaler is loaded, which Setup
does for FSR 4. The game then asks for the frame count, not OptiScaler's menu. Beside MFG Unlocker, FreeFG does not
accelerate a game's own frame generation: MFG Unlocker checks that the game's frame generation runs on the game's own
Direct3D device, and the device FreeFG would hand Intel's runtime is a stand-in. So in such a game, with MFG Unlocker
loaded, every frame count, 2× included, runs MFG Unlocker's and Intel's shaders (`BC250-MFG.log` says `FAST_SKIP …
only OptiScaler's own contexts are accelerated`). For FreeFG's faster 2× there, leave MFG Unlocker out of that game
(remove its `.asi`). Whether 3× and 4× are reachable on this route has not been checked with FreeFG 1.0.0.

**Before FreeFG's Restore**, uninstall MFG Unlocker the way its README says: close the game, remove
`OptiScaler/plugins/MFGUnlocker.asi` and the `RTXMFG-*` files beside the `.exe` (keep `RTXMFG-Universal.json` elsewhere if
you want its settings). Otherwise Restore leaves them, and the `OptiScaler/plugins` folder, in place and says so. After a
Restore and a new Install, put MFG Unlocker back and set `XeFGModel` again: Setup does not carry it over (a new
OptiScaler setup has `LoadAsiPlugins=true` again), and Install sets the frame count back to 2×.

## Restore and uninstall

**Restore** (Setup, or `install.py restore`): close the game and its launcher first, and remove MFG Unlocker first if
you added it ([3× and 4× with MFG Unlocker](#3-and-4-with-mfg-unlocker)). Restore puts back every file
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
folder, the download cache `~/.cache/bc250-xefg-testers` (with HelixSR in it, if you downloaded it there) and, once you
no longer need the backups, each game's `.bc250-xefg-experimental-restored-…` folder. If you used HelixSR, HelixSR's own
setup also kept its downloads in `~/.local/share/HelixSR`.

## Troubleshooting

**Status** checks the installation and summarises the last session's log. The logs are in the game folder, beside the
`.exe`:

| Log | What to look for |
| --- | --- |
| `BC250-MFG.log` | `MFG proxy ready` means Intel's runtime was found and verified. `bc250_xefg_original.dll is missing or is not the pinned Intel XeFG runtime` means XeFG is unavailable in this game: run Install again. `FAST_COEXIST another module hooks Intel's XeFG runtime (…)` names the hooked entry and the module, for example MFG Unlocker. `MFG_FACTOR` lines give the frame count, and `MFG_STATUS` the frames per present that the runtime reports. |
| `BC250-XeFG-fast.log` | `FAST_OWNER` and `MODEL_SEALED` mean the accelerated path is active, and so does `PRIVATE GAME TRIAL scoped prepared-model and Winograd path installed` (fixed text from the project's development, compiled into the DLL). `FAST_FALLBACK …` or `FAST_SKIP …` give the reason Intel's shaders are used instead. `FAST_ASIDE …` means another mod changed the runtime's work in a way FreeFG has not verified, so it stepped aside for the rest of that context. A `FAIL` line means FreeFG closed the game, because the runtime did something it does not recognise. Please report that. |
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
| `BC250_XEFG_DISABLE=1` | Intel's original shaders instead of the accelerated path. Presents are still held while XeFG generates (from the frames the runtime reports presented). |
| `BC250_XEFG_PACE=0` / `=1` | Output pacing off / hold every present, also while XeFG is not generating. |
| `BC250_XEFG_PACE_NUDGE=0` / `=1` | The X nudge for stock gamescope off / on. |
| `BC250_XEFG_PACE_QUEUE=app` | Present from the game's own queue even when a compute queue exists. |
| `BC250_XEFG_ANY_GPU=1` | The accelerated path on a GPU other than the BC-250 (untested; see [Other GPUs](#other-gpus)). |
| `BC250_XEFG_STATUS_POLL=0` | No status read per frame for the pacing signal (only the caller's own status queries count). |

The DLL also reads `BC250_CAPTURE_TAG_FRAMES=1`, a switch for latency measurements: it turns on the debug marker that
Intel's XeFG API draws on generated frames, so that capture tools can tell them apart. Leave it unset for play.

When you report a problem, send the two logs, the game, Proton and Mesa versions, resolution, HDR on or off, the
upscaler mode and the frame-generation input. Logs alone do not show whether the picture or the pacing looked right, so
describe what you saw.

## Other GPUs

Everything is built and measured on the BC-250. On another GPU under Proton, Setup installs the same files, and:

- **By default** FreeFG passes everything through to Intel's runtime: Intel's shaders, generated frames at output
  resolution. The pacing layer still learns when XeFG generates (from the frames the runtime reports presented) and
  holds presents then. `BC250-XeFG-fast.log` says `FAST_FALLBACK requires BC250 adapter (this one is vvvv:dddd; …)`.
- **With `BC250_XEFG_ANY_GPU=1`** the accelerated path runs on that GPU too. **Nobody has tested this.** FreeFG
  checks what Intel's runtime hands it and closes the game (a `FAIL` line) rather than show frames it cannot vouch for.
  RDNA 2 and newer GPUs have the int8 dot-product instructions that Intel's shaders use, so it is not known whether
  FreeFG's shaders are faster there. On RDNA 1 they replace work the driver emulates, as on the BC-250.
- The FSR 4 DLL that Setup installs is a BC-250 build; on other GPUs it is untested.
- Intel GPUs are not a target: without another mod that hooks Intel's runtime, FreeFG accelerates only contexts
  that generate one frame per real frame, as the 2× build does.

## Extras

Optional host helpers in `extras/`, each with its own README and an `uninstall.sh`:

- **`gamescope-cap-sys-nice`** gives gamescope realtime priority (`CAP_SYS_NICE`), which most distributions other than
  SteamOS leave out. Without it gamescope's composition and page flips queue behind the game's GPU work, which shows as
  uneven VRR refresh. It asks for `sudo` once. On pacman systems it adds a hook that sets the capability again after
  gamescope updates. Side effect: gamescope then ignores `LD_PRELOAD` and drops it for the programs it starts (see that
  README).
- **`steam-screensaver-in-game`** keeps Steam's screensaver timeout at Never only while a game runs and puts your value
  back afterwards. It needs Steam's local DevTools port (see [SECURITY.md](SECURITY.md)).

## FAQ

**Is this made by Intel, AMD or NVIDIA?** No. FreeFG is an independent project that works with their software.

**Why does FreeFG not unlock 3× and 4× itself?** Intel's runtime generates at most one frame per real frame on
GPUs other than Intel's, as Intel documents. FreeFG does not change that limit. If you lift it with another tool,
FreeFG keeps working beside it ([3× and 4× with MFG Unlocker](#3-and-4-with-mfg-unlocker)).

**Does it change Intel's DLL?** No. Setup downloads Intel's `libxess_fg.dll` from a pinned source and checks its SHA-256.
FreeFG's DLL verifies it again before loading it, unmodified. While the runtime runs, FreeFG carries out part of
its GPU work with its own shaders: [ARCHITECTURE.md](ARCHITECTURE.md) lists every such change. Intel's licence terms
for the runtime apply to you as its user; see [NOTICE.md](NOTICE.md).

**Are the generated frames really the same?** In synthetic XeFG scenes, yes, bit for bit, wherever that was compared
([MEASUREMENTS.md](MEASUREMENTS.md) gives the exact scope). The shaders are written so that every intermediate sum is
an integer that FP32 holds exactly, so rounding cannot differ. In games, nothing has been compared pixel by pixel.

**Why does Setup download files instead of shipping them?** Intel's runtime, AMD's FSR 4 DLL, OptiScaler's support
files and NVIDIA's DLSS helper belong to their publishers and come from their own release locations, checked by hash.
The download contains only this project's files and the OptiScaler build it needs.

**Why a modified OptiScaler?** Upstream OptiScaler since 26 September 2026 can deadlock at start-up in some
Streamline games: CONTROL Resonant hung on about half of its starts with an earlier upstream build. The bundled build,
upstream master of 19 October 2026, takes its locks in a fixed order instead and adds two small fixes. Its source is
linked in [NOTICE.md](NOTICE.md). Its version string (in OptiScaler's log and
menu) ends in `(BC250 private)`: fixed text of that build, which does not mean that its source is private.

**Does it work on Windows, on the Steam Deck, or with DirectX 11 or Vulkan games?** Windows: no. Steam Deck: untested
(not a BC-250). DirectX 11 and Vulkan games: no.

**What is HelixSR, and who makes it?** An upscaler by lonewolf0622 that runs NVIDIA's DLSS network on other GPUs:
<https://github.com/lonewolf0622/HelixSR>. It is a separate project with its own licence; FreeFG only offers it as
a choice and downloads it from its author's release page when you pick it. See
[Upscaler: FSR 4 or HelixSR](#upscaler-fsr-4-or-helixsr).

**Does it send anything anywhere?** No. See [PRIVACY.md](PRIVACY.md).

## Known limitations

- 2× on its own; 3× and 4× only with MFG Unlocker, a separate tool ([3× and 4× with MFG
  Unlocker](#3-and-4-with-mfg-unlocker)). No generated-frame scaling.
- Qualified only on the BC-250, under Proton in Steam Game Mode. This build has run in main menus and benchmarks, not
  yet in gameplay (see [Status](#status)).
- Frame pacing works only under gamescope.
- Only the first XeFG context of a game process is accelerated.
- Deadzone: Rogue does not generate frames yet; Deep Rock Galactic needs an upscaler chosen in its own menu first.
- If FreeFG meets a frame-generation graph it does not know, for example after an update to Intel's runtime pin, it
  closes the game rather than show frames it cannot vouch for. Beside another mod that hooks Intel's runtime it steps
  aside instead for the checks that concern the network's make-up (its set of weights and the order of its work); its
  other checks still end the game.
- Sandboxed launchers (Flatpak Steam, Flatpak Heroic) are not qualified.
- HelixSR as the upscaler is not yet qualified with FreeFG in a live game (install, Restore, image and frame rate).

## Rights holders

If you hold rights in software that FreeFG works with, for example Intel, AMD or NVIDIA, and have a concern about
this project, open an issue at <https://github.com/daniel-h-0/freefg/issues>, or raise it privately through the
repository's **Security** tab: **Report a vulnerability** (GitHub's private reporting,
<https://github.com/daniel-h-0/freefg/security/advisories/new>) reaches only the maintainers. GitHub's own
[DMCA process](https://docs.github.com/en/site-policy/content-removal-policies/dmca-takedown-policy) is open to rights
holders too. We will answer promptly, and we will take the release down on a credible request.

## More

[ARCHITECTURE.md](ARCHITECTURE.md) (how it works) · [MEASUREMENTS.md](MEASUREMENTS.md) (numbers and their scope) ·
[PRIVACY.md](PRIVACY.md) (downloads) · [NOTICE.md](NOTICE.md) (licences) · [BUILDING.md](BUILDING.md) (build from source) ·
[CHANGELOG.md](CHANGELOG.md) · [CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md)

FreeFG's own code is MIT-licensed. Other components keep their own licences; see [NOTICE.md](NOTICE.md).
