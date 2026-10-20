# Troubleshooting

Setup's **Status** checks an installation, summarises the last session's log, names the upscaler and where HelixSR's log
is, and reports FreeFG files that a game update replaced (Restore and install again). **Check system**
(`install.py doctor`) checks the computer, including whether HelixSR is ready.

## Logs

FreeFG's logs are beside the game's `.exe`. They do not show whether the picture or the pacing looked right, so
describe what you saw when you [report a problem](CONTRIBUTING.md#reporting-a-problem). Report HelixSR's own problems at
its [issues page](https://github.com/lonewolf0622/HelixSR/issues) with its `helixsr.log`.

| Log | Line | Meaning |
| --- | --- | --- |
| `BC250-MFG.log` | `MFG proxy ready` | Intel's runtime was found and verified. |
| | `bc250_xefg_original.dll is missing or is not the pinned Intel XeFG runtime` | XeFG is unavailable in this game; run Install again. |
| | `FAST_COEXIST another module hooks Intel's XeFG runtime (…; jumps to MODULE)` | Another module, such as MFG Unlocker, hooks Intel's runtime. FreeFG keeps working beside it and steps aside, rather than ending the game, on work it has not verified. |
| | `FAST_SKIP … only OptiScaler's own contexts are accelerated` | Another mod, such as MFG Unlocker, is loaded in a game using its own XeSS frame generation; Intel's or that mod's shaders run at every frame count. |
| | `MFG_FACTOR`, `MFG_STATUS` | The frame count; the frames per present the runtime reports. |
| `BC250-XeFG-fast.log` | `FAST_OWNER`, `MODEL_SEALED`, `PRIVATE GAME TRIAL scoped prepared-model and Winograd path installed` (fixed text compiled into the DLL) | The accelerated path is active. |
| | `FAST_FALLBACK …`, `FAST_SKIP …` | Why Intel's shaders are used instead. |
| | `FAST_ASIDE …` | FreeFG stepped aside for the rest of that context, because another mod changed the runtime's work in a way it has not verified. |
| | `FAIL` | FreeFG closed the game because the runtime did something it does not recognise. Report it. |
| The game's standard error (for Steam: launch option `PROTON_LOG=1 %command%`, then `$HOME/steam-<appid>.log`) | `BC250_PACE on …` | Pacing is active. |
| | `BC250_PACE holding: XeFG generates frames`, `BC250_PACE passing presents through` | The layer holds presents, or passes them through. |

## Problems

| Problem | What to try |
| --- | --- |
| Only real frames are shown; the frame rate does not go up | Turn the game's frame generation on (DLSS FG and FSR FG inputs); make sure the game is not in exclusive fullscreen; check `BC250-XeFG-fast.log`. |
| Uneven pacing or VRR flicker | Give gamescope realtime priority ([Extras](README.md#extras)); rule out Steam's screensaver (below); stay below the refresh rate; check the `BC250_PACE` lines. |
| Bursts of VRR flicker after some idle minutes, in long cutscenes or with a game left running | Steam's screensaver: in Game Mode it starts behind a running game after the idle timeout (5 minutes by default; controller input resets it) and every 20 seconds cross-fades for 2 seconds, taking GPU time. Set the timeout to **Never**, or install the `steam-screensaver-in-game` extra. |
| A game installed despite its anti-cheat does not start, or reports tampering | The anti-cheat refuses FreeFG's DLLs: Restore the game. The maintainers cannot help with bans ([COMPATIBILITY.md](COMPATIBILITY.md#anti-cheat)). |
| `Existing OptiScaler must be the 10.0.0-pre1 nightly …` | Restore or update the game's OptiScaler first. |
| `Cannot download …` | The first installation needs internet access, or the file already in `~/.cache/bc250-xefg-testers`. |
| `version.dll is occupied` or `An existing XeSSMFG folder …` | Another mod, or a test build of this project from before its public release, occupies those files; restore it with its own installer first. |
| Setup does not find HelixSR | Setup looks for an unpacked folder named `HelixSR…` in your home folder and its `Downloads` and `Applications` folders. Elsewhere, name it once with `--helixsr /path/to/HelixSR-2.0.0` (with `install.py helixsr`, `install` or `configure`); the folder is remembered. `install.py helixsr` says what is missing. FreeFG uses only official releases it knows (2.0.0): with another version present it offers to download 2.0.0, and a newer version needs an updated FreeFG. |

## Environment variables

For troubleshooting, as launch options before `%command%`. Setup keeps them on reinstall; Restore leaves them in place.

| Variable | Effect |
| --- | --- |
| `BC250_XEFG_DISABLE=1` | Intel's original shaders instead of the accelerated path. Presents are still held while XeFG generates. |
| `BC250_XEFG_PACE=0` / `=1` | Output pacing off / hold every present, also while XeFG is not generating. |
| `BC250_XEFG_PACE_NUDGE=0` / `=1` | The X nudge for stock gamescope off / on. |
| `BC250_XEFG_PACE_QUEUE=app` | Present from the game's own queue even when a compute queue exists. |
| `BC250_XEFG_ANY_GPU=1` | The accelerated path on a GPU other than the BC-250 (untested; [below](#other-gpus)). |
| `BC250_XEFG_STATUS_POLL=0` | No status read per frame for the pacing signal; only the caller's own status queries count. |
| `BC250_CAPTURE_TAG_FRAMES=1` | For latency measurements: turns on the debug marker that Intel's XeFG API draws on generated frames, so capture tools can tell them apart. Leave unset for play. |

## Other GPUs

Everything is built and measured on the BC-250. On another GPU under Proton, Setup installs the same files, and:

- By default, FreeFG passes everything through to Intel's runtime (Intel's shaders, generated frames at output
  resolution). The pacing layer still holds presents while XeFG generates. `BC250-XeFG-fast.log` says
  `FAST_FALLBACK requires BC250 adapter (this one is vvvv:dddd; …)`.
- `BC250_XEFG_ANY_GPU=1` runs the accelerated path on that GPU. Nobody has tested this. FreeFG checks what Intel's
  runtime hands it and closes the game (a `FAIL` line) rather than show frames it has not verified. RDNA 2 and newer
  have the int8 dot-product instructions Intel's shaders use, so whether FreeFG's shaders are faster there is not
  known; on RDNA 1 they replace work the driver emulates, as on the BC-250.
- The FSR 4 DLL is a BC-250 build, untested on other GPUs.
- Intel GPUs are not a target. Without another mod hooking Intel's runtime, FreeFG accelerates only 2× contexts.
