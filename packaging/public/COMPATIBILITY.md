# Game compatibility

XeFG builds each generated frame from the game's motion vectors and depth. FreeFG gets them only in DirectX 12, from
an upscaler or frame-generation SDK that OptiScaler hooks (DLSS, FSR 2, FSR 3.x, XeSS, DLSS FG, FSR 3.1 FG) or from the
game's own XeSS frame generation. A game without one has nothing to generate from. The other requirements are in the
[refusals](#refusals).

Of the maintainers' 85 installed games on a BC-250, 22 have a usable input (19 with a recipe, 3 found automatically and
not yet checked in a game); 2 ship only the DLSS DLL that Unity bundles, unused by the game (refused unless you accept);
34 have no upscaler input; 27 cannot run FreeFG (12 native Linux builds, 6 32-bit games, 8 without DirectX 12, 1
tool).

## Supported games

Setup has a recipe for 19 games: the input, OptiScaler settings, the game's own frame-generation setting and a DirectX
12 launch option where needed. Restore undoes all of it. "Observed" was seen on a BC-250 with earlier private builds
that use the same installer, recipes and route at 2×; 2.0 is the measured presents per game frame. "FreeFG:" marks
runs with FreeFG itself (0.9.0 or 1.0.0).

| Game | Input the recipe picks | Observed |
| --- | --- | --- |
| CONTROL Resonant | DLSS FG (turns the game's DLSS frame generation on) | 2.0 |
| Crimson Desert | FSR 3.1 FG (turns the game's frame generation on) | played at 2× |
| Cyberpunk 2077 | native XeSS FG | played at 2×; FreeFG: installed and restored, benchmark at 2.0 (headless and on a TV with VRR) |
| Dead as Disco | FSR 3.1 FG (`FrameGenerationMode=FSR`) | 2.0 |
| Echo Point Nova | OptiFG | 2.0; FreeFG: installed, started to the main menu, restored |
| Kingdom Come: Deliverance II | OptiFG | 2.0 in gameplay |
| RoboCop: Rogue City | DLSS FG (the game's DLSS upscaling and frame generation) | 2.0 |
| System Shock | OptiFG, `-dx12` | 2.0 at start-up |
| The Invincible | OptiFG, `-dx12` | 2.0 in gameplay |
| VOIN | OptiFG, `-dx12` | 2.0 |
| Witchfire | DLSS FG (turns the game's `DLSS_FG` on) | 2.0; played at 2× |
| Deadzone: Rogue | FSR 3.1 FG | does not generate yet |
| Deep Rock Galactic | DLSS FG, `-dx12` | did not generate: choose an upscaler (DLSS / DLSS FG) once in the game's own Video menu |

Installed, generation not checked: Assassin's Creed Black Flag Resynced (native XeSS FG), Hogwarts Legacy (DLSS FG,
turns the game's DLSS frame generation on), Red Dead Redemption 2 (OptiFG), Tainted Grail: The Fall of Avalon (OptiFG,
`-force-d3d12`), Thymesia (OptiFG, `-dx12`; needs an in-game resolution scale above 100%), TRYP FPV (OptiFG, `-dx12`).

## Verdicts

Check (in Setup or `install.py check`) and Install give every game a verdict offline, with its reason and how sure the
check is, before anything is downloaded or written; a refusal stops there.

| Verdict | Meaning |
| --- | --- |
| Verified on BC-250 | A recipe [above](#supported-games); its input, settings and launch option are applied. |
| Community-reported on BC-250 | A reviewed recipe from other BC-250 owners, not reproduced by the maintainers; applied and labelled. |
| Automatic, guided by the OptiScaler wiki | No recipe. The [OptiScaler wiki](https://github.com/optiscaler/OptiScaler/wiki) identifies the game and supplies a DirectX 12 launch option, rules out an input it reports broken, or supplies one of six promoted fixes. |
| Automatic (no recipe) | Detection found a 64-bit DirectX 12 executable with an input: native XeSS FG beside it, else OptiFG from the game's upscaler, else the game's own frame generation. |
| Not supported | A [refusal](#refusals), with the way forward. |

Only verified recipes were played on a BC-250; automatic setups are labelled as such. A verdict can come with a step for
you (turn on the game's frame generation, select DirectX 12, check that OptiScaler loads under another proxy name the
wiki names), shown before you confirm Install. Other wiki advice is shown with its condition checked against your setup
(AMD, Linux, DirectX 12, XeFG output, FSR 4): applies, does not apply, or depends on what only you see in the game. Most
wiki reports come from Windows PCs with other GPUs. After a run, Check also reads the game's own logs. Which source
decides: [ARCHITECTURE.md](ARCHITECTURE.md#which-source-decides).

## Refusals

A soft refusal can be accepted per game: **Install anyway** in Setup, `--accept CODE` on the command line.

| Code | Reason | What to do |
| --- | --- | --- |
| `anticheat` | Anti-cheat files (Easy Anti-Cheat, BattlEye, GameGuard, XIGNCODE3, EA Javelin, ACE, mhyprot, EQU8, PunkBuster, Vanguard); FreeFG loads DLLs into the game process, which anti-cheat software may treat as tampering. | Nothing. |
| `native-linux` | Steam installed the Linux version. | Force a Proton version in the game's Compatibility properties, let Steam download the Windows version, Check again. |
| `32bit` | XeFG and FreeFG are 64-bit only. | Nothing. |
| `api-vulkan`, `api-opengl`, `api-dx11`, `no-dx12` | No DirectX 12 path. DirectX 11 stays refused until qualified: OptiScaler's DX11-to-DX12 bridge gave a black screen under this Proton stack. | Nothing; soft when you chose the input yourself, since detection can miss what you know. |
| `no-input` | DirectX 12, but no upscaler or frame-generation SDK. | As above. |
| `input-unconfirmed` (soft) | A Unity game whose only DLSS evidence is the DLL Unity's NVIDIA module bundles; its code never names DLSS. | Accept only if the game's menu offers DLSS. |
| `wrong-exe` | The executable is a launcher stub. | Choose the executable Check names. |
| `no-launcher` | No Steam, Heroic or Lutris entry starts the executable. | Add the game to one of them. |
| `shared-entry` | The launcher entry already starts an installation in another folder. | Restore that installation first. |
| `ge-optiscaler` | GE-Proton is told to place its own OptiScaler or upscaler DLLs (`PROTON_USE_OPTISCALER`, `PROTON_*_UPGRADE`). | Remove the variable from the launch options. |
| `protonfix-api` (soft) | GE-Proton's fix for the game switches it away from DirectX 12. | Accepting adds `PROTONFIXES_DISABLE=1`, turning off all of GE-Proton's fixes for the game (Check names what else the fix does); Restore removes it. |
| `wiki-not-working` (soft) | The OptiScaler wiki lists the game as not working (matched by launcher ID, or by executable and title; a title-only match is a note). | Accept to try anyway. |
| `installed`, `xessmfg`, `version-dll`, `existing-files`, `existing-optiscaler`, `optiscaler-paths`, `helixsr-installer`, `recipe-exe`, `ascii-path` | The game folder: an installation not yet restored, another frame-generation mod, an OptiScaler setup this package does not take over, HelixSR installed by its own installer, the wrong executable of a verified game, a path that is not ASCII. Check shows the plan Install follows once resolved. | What Check names: Restore, remove the other mod (HelixSR: with its own uninstaller), or choose the other executable. |

## Checking a game

Check only reads: it writes nothing and uses no network
([PRIVACY.md](PRIVACY.md#what-the-installer-reads-and-writes-on-your-computer) lists what it reads).

```sh
python3 install.py check GAME.exe            # verdict, plan, your steps, wiki notes, the last run
python3 install.py check GAME.exe --report   # plus issue text without paths or user name
python3 install.py check --all               # one line per installed Steam and Heroic game
python3 install.py install GAME.exe --accept protonfix-api            # a soft refusal, accepted
python3 install.py install A.exe B.exe --accept 'protonfix-api=A.exe' # accepted for one of the games only
```

## From report to recipe

Any report of a game on a BC-250, working or not, can become a community recipe and then a verified one: paste the
`--report` text into an issue with the **Game report** form ([CONTRIBUTING.md](CONTRIBUTING.md#game-recipes)).
