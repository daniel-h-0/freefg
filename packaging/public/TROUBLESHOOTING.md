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
| | `FAST_SKIP … only OptiScaler's own contexts are accelerated` | Another mod, such as MFG Unlocker, is loaded, and the game created its own XeFG context (its own XeSS frame generation): that context runs Intel's or that mod's shaders at every frame count. On an OptiScaler input, OptiScaler's context can still be accelerated (`FAST_OWNER`). |
| | `MFG_FACTOR`, `MFG_STATUS` | The frame count; the frames per present the runtime reports. |
| | `FAST_OWNER` | FreeFG selected the context it accelerates. |
| | `FAST_FALLBACK …`, other `FAST_SKIP …` lines | Why Intel's shaders are used instead. |
| `BC250-XeFG-fast.log` | `MODEL_SEALED`, `PRIVATE GAME TRIAL scoped prepared-model and Winograd path installed` (fixed text compiled into the DLL) | The accelerated path is active. |
| | `FAST_ASIDE …` | FreeFG stepped aside for the rest of that context, because another mod changed the runtime's work in a way it has not verified. |
| | `F4Q_CONFIG mode=… source=…` | F4Q's state (`on`, `off`, or `shadow` for the diagnostic) and what set it: `default`, `BC250_XEFG_F4Q`, `settings.ini`, `BC250_XEFG_F4Q_SHADOW`, or `layout` (a network layout F4Q does not know; the F(2×2) kernels run). `F4Q_FALLBACK …`: one pipeline runs its F(2×2) kernel. |
| | `F4Q2_CONFIG mode=… source=… layers=…` | F4Q2's state and what set it: `default`, `BC250_XEFG_F4Q2`, `settings.ini`, or `F4Q` (F4Q is off, so F4Q2 is too). `layers` is 7 when all three of its layers run; `dropped_by_layout` names layers a network layout keeps on F(2×2). |
| | `FP16_CONFIG mode=… source=… forms=…` | The FP16 forms' state (1.1.2): `on` (the default; the output differs slightly from Intel's) or `off`, and what set it: `default`, `BC250_XEFG_EXACT`, `settings.ini` (`Exact=1`), `F4Q` (F4Q off or its diagnostic) or `layout`. `forms` is 3 by default: F4Q2's three encoders (1) and four F(2×2) layers (2) ([ARCHITECTURE.md](ARCHITECTURE.md#fp16-forms-the-default-slightly-different)). `FP16_REPLACE` lines name each `<hash>.fp16.dxil` read (an `F4Q_FALLBACK` line for the same shader means its pipeline could not be created and its F(2×2) kernel ran), `FP16_FALLBACK` lines a layer that ran its exact form instead; the `Output:` line of Status and Check counts both. |
| | `F4Q3_CONFIG mode=… layers=…` | F4Q3's state for the row layers `60edebbb` and `b3ddf030`: `on` by default and with the exact switch, `shadow` in the diagnostic, `off` with `source=F4Q` while F4Q is off. |
| | `FAIL` | FreeFG closed the game because the runtime did something it does not recognise. Report it. |
| The game's standard error (for Steam: launch option `PROTON_LOG=1 %command%`, then `$HOME/steam-<appid>.log`) | `BC250_PACE on …` | Pacing is active. |
| | `BC250_PACE holding: XeFG generates frames`, `BC250_PACE passing presents through` | The layer holds presents, or passes them through. |

## Problems

| Problem | What to try |
| --- | --- |
| Frame generation adds fewer frames than expected | See [below](#frame-generation-adds-little). |
| Only real frames are shown; the frame rate does not go up | Turn the game's frame generation on (DLSS FG and FSR FG inputs); make sure the game is not in exclusive fullscreen; check `BC250-MFG.log` and `BC250-XeFG-fast.log`. |
| Uneven pacing or VRR flicker | Give gamescope realtime priority ([Extras](README.md#extras)); rule out Steam's screensaver (below); stay below the refresh rate; check the `BC250_PACE` lines. |
| Bursts of VRR flicker after some idle minutes, in long cutscenes or with a game left running | Steam's screensaver: in Game Mode it starts behind a running game after the idle timeout (5 minutes by default; controller input resets it) and every 20 seconds cross-fades for 2 seconds, taking GPU time. Set the timeout to **Never**, or install the `steam-screensaver-in-game` extra. |
| The first start after installing (or reinstalling) loads for longer | Expected once: vkd3d-proton fills the game's new shader cache in `.bc250-xefg-experimental/vkd3d-cache` ([MEASUREMENTS.md](MEASUREMENTS.md#shader-caches)). `install.py status` shows its size; Restore deletes it. |
| A game installed despite its anti-cheat does not start, or reports tampering | The anti-cheat refuses FreeFG's DLLs: Restore the game. The maintainers cannot help with bans ([COMPATIBILITY.md](COMPATIBILITY.md#anti-cheat)). |
| `Existing OptiScaler must be the 10.0.0-pre1 nightly …` | Restore or update the game's OptiScaler first. |
| `Cannot download …` | The first installation needs internet access, or the file already in `~/.cache/bc250-xefg-testers`. |
| `version.dll is occupied` or `An existing XeSSMFG folder …` | Another mod, or a test build of this project from before its public release, occupies those files; restore it with its own installer first. |
| Setup does not find HelixSR | Setup looks for an unpacked folder named `HelixSR…` in your home folder and its `Downloads` and `Applications` folders. Elsewhere, name it once with `--helixsr /path/to/HelixSR-2.0.0` (with `install.py helixsr`, `install` or `configure`); the folder is remembered. `install.py helixsr` says what is missing. FreeFG uses only official releases it knows (2.0.0): with another version present it offers to download 2.0.0, and a newer version needs an updated FreeFG. |

## Frame generation adds little

Setup's **Status** reads the last session's logs and says whether FreeFG ran the whole network, only part of it
(MFG Unlocker's own model) or nothing beside MFG Unlocker, and what to change. From the game folder's files, **Status**
and **Check** also name MFG Unlocker beside the native route, or with `XeFGModel` other than `default`. By hand, read
the logs beside the `.exe`:

| Installation's input | `BC250-MFG.log` | `BC250-XeFG-fast.log` | Meaning | What to do |
| --- | --- | --- | --- | --- |
| any | `FAST_OWNER` | 13 lines that start with `REPLACE` | Full acceleration. | Nothing ([gains measured at 4K](MEASUREMENTS.md#4k)). |
| OptiScaler | `FAST_OWNER` | 7 lines that start with `REPLACE` | MFG Unlocker's own model: FreeFG's shaders run on part of the network, at every frame count. | Set `XeFGModel=default` under `[XeFG]` in `OptiScaler.ini` ([README](README.md#3-and-4-with-mfg-unlocker)). |
| native XeSS FG (or the game's XeSS FG chosen in the game) | `FAST_SKIP beside another module …`, no `FAST_OWNER` or `CONTEXT_CALLER` | none or earlier | The game's own XeSS frame generation beside MFG Unlocker: FreeFG does not accelerate it. | Use OptiScaler's frame generation (install with an OptiScaler input), or remove MFG Unlocker for 2×. |
| any | `FAST_ASIDE …` | any | FreeFG stepped aside during the session ([Logs](#logs)). | Use MFG Unlocker 1.6.0 with `XeFGModel=default`, or remove the other mod. |
| any other case | no `FAST_OWNER` | none or earlier | `BC250_XEFG_DISABLE=1`, or the reason in a `FAST_FALLBACK` or `FAST_SKIP` line ([Logs](#logs)). | Remove `BC250_XEFG_DISABLE` from the launch options, or act on that line. |

`BC250-XeFG-fast.log` is written only in a session with `FAST_OWNER`; "earlier" is a log left by an earlier session,
which **Status** names as such; **Status** reads only the logs beside the `.exe` written since the installation.
`F4Q_REPLACE` lines are not counted. Beside MFG Unlocker, `BC250-MFG.log` also
has `FAST_COEXIST` lines, and on an OptiScaler input a `FAST_SKIP` line for the game's own context, whatever the model.
**Status** shows the installation's input.

FreeFG generates frames at the full output size (no generated-frame scaling), so at 4K the 1080p generated-frame
limit of earlier private test builds is faster ([MEASUREMENTS.md](MEASUREMENTS.md#4k)).

## Environment variables

For troubleshooting, as launch options before `%command%`. Setup keeps them on reinstall; Restore leaves them in place.

| Variable | Effect |
| --- | --- |
| `BC250_XEFG_DISABLE=1` | Intel's original shaders instead of the accelerated path. Presents are still held while XeFG generates. |
| `BC250_XELL_PACE=0` | Disable the bundled OptiScaler's adaptive 3×/4× game-frame correction for comparison. |
| `BC250_XEFG_PACE=0` / `=1` | Output pacing off / hold every present, also while XeFG is not generating. |
| `BC250_XEFG_PACE_NUDGE=0` / `=1` | The X nudge for stock gamescope off / on. |
| `BC250_XEFG_PACE_QUEUE=app` | Present from the game's own queue even when a compute queue exists. |
| `BC250_XEFG_ANY_GPU=1` | The accelerated path on a GPU other than the BC-250 (untested; [below](#other-gpus)). |
| `BC250_XEFG_STATUS_POLL=0` | No status read per frame for the pacing signal; only the caller's own status queries count. |
| `BC250_XEFG_F4Q=0` | F4Q, F4Q2, F4Q3 and the FP16 forms off: the F(2×2) and 1D kernels of the U-Net layers run, as in 1.0.x ([ARCHITECTURE.md](ARCHITECTURE.md#f4q-identical-in-every-test-not-proven)). `F4Q=0` under `[BC250]` in `BC250-XeFG/settings.ini` does the same; `BC250_XEFG_F4Q=1` wins over the file. |
| `BC250_XEFG_EXACT=1` | The FP16 forms off: every kernel runs its exact form, and the output was identical to Intel's in every test ([ARCHITECTURE.md](ARCHITECTURE.md#fp16-forms-the-default-slightly-different)). `Exact=1` under `[BC250]` in `BC250-XeFG/settings.ini` does the same; `BC250_XEFG_EXACT=0` wins over the file. |
| `BC250_XEFG_F4Q2=0` | F4Q2 off, F4Q on: the three encoder layers F4Q2 replaces run their F(2×2) kernels, as in 1.1.1, also by default (without their FP16 form). `F4Q2=0` under `[BC250]` in `BC250-XeFG/settings.ini` does the same; `BC250_XEFG_F4Q2=1` turns it on whatever that file says. |
| `BC250_XEFG_F4Q_SHADOW=1` | Diagnostic: the F4Q kernels (F4Q2's while it is on, and F4Q3's) run beside the F(2×2) and 1D ones, which keep the output, and `BC250-XeFG-fast.log` gets `F4Q_COUNT` lines with equal and differing outputs per layer. Costs GPU time; for checks and bug reports only. The FP16 forms are off while it runs. |
| `BC250_CAPTURE_TAG_FRAMES=1` | For latency measurements: turns on the debug marker that Intel's XeFG API draws on generated frames, so capture tools can tell them apart. Leave unset for play. |

## Other GPUs

Everything is built and measured on the BC-250. On another GPU under Proton, Setup installs the same files, and:

- By default, FreeFG passes everything through to Intel's runtime (Intel's shaders, generated frames at output
  resolution). The pacing layer still holds presents while XeFG generates. `BC250-MFG.log` says
  `FAST_FALLBACK requires BC250 adapter (this one is vvvv:dddd; …)`.
- `BC250_XEFG_ANY_GPU=1` runs the accelerated path on that GPU. Nobody has tested this. FreeFG checks what Intel's
  runtime hands it and closes the game (a `FAIL` line) rather than show frames it has not verified. RDNA 2 and newer
  have the int8 dot-product instructions Intel's shaders use, so whether FreeFG's shaders are faster there is not
  known; on RDNA 1 they replace work the driver emulates, as on the BC-250.
- The FSR 4 DLL is a BC-250 build, untested on other GPUs.
- Intel GPUs are not a target. Without another mod hooking Intel's runtime, FreeFG accelerates only 2× contexts.
