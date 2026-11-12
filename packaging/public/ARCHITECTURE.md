# Architecture

FreeFG runs inside a DirectX 12 game under Proton:

```
game
 ├─ OptiScaler ── FSR 4 or HelixSR: upscaling
 ├─ libxess_fg.dll: FreeFG proxy ── bc250_xefg_original.dll: Intel XeFG runtime
 ├─ BC250-XeFG/shaders/: replacement shaders and helper kernels
 └─ vkd3d-proton → libxefg_wave.so → Mesa RADV → gamescope
```

The proxy accelerates part of XeFG's GPU work. The Vulkan layer selects wave sizes and schedules output frames. The
bundled OptiScaler also corrects uneven game-frame starts at 3× and 4×. These are separate mechanisms.

## The proxy

Native XeSS FG games and OptiScaler's XeFG output load the proxy as `libxess_fg.dll`. Intel's unmodified runtime sits
beside it as `bc250_xefg_original.dll`.

### Exports

The proxy keeps the **57 exports** of Intel's runtime 1.3.1.78 at their ordinals:

- The 24 that Intel's headers declare are the proxy's own entries. Eight are wrapped (table below). Sixteen check and
  load the runtime beside the proxy, then tail-call it.
- The 26 unnamed and 7 undeclared exports forward directly. If a forwarder has already loaded another copy of the
  runtime, the proxy refuses to use either.

Four additional exports provide FreeFG's settings and initialisation interface.

| Wrapped calls | Work before or after forwarding |
| --- | --- |
| `xefgSwapChainD3D12CreateContext`, `xefgSwapChainD3D12InitFromSwapChain`, `xefgSwapChainD3D12InitFromSwapChainDesc`, `xefgSwapChainDestroy` | Context and resource lifecycle |
| `xefgSwapChainSetNumInterpolatedFrames` | Frame-count changes and resource retirement |
| `xefgSwapChainGetLastPresentStatus` | Generation signal |
| `xefgSwapChainD3D12GetSwapChainPtr`, `xefgSwapChainTagFrameConstants` | Deferred initialisation and per-frame status polling |

### Runtime loading

The first call to one of the proxy's 24 own entries checks the runtime's pinned size and FNV-1a hash, then loads it by
absolute path. A missing or changed runtime produces `XEFG_SWAPCHAIN_RESULT_ERROR_CANT_LOAD_LIBRARY` and a reason in
`BC250-MFG.log`. The FNV-1a hash identifies the file and gives no cryptographic protection. Installation verifies the
download by SHA-256.

The proxy imports only `kernel32.dll` and `ucrtbase.dll`. It does not patch Intel's code or the game's Direct3D method
tables.

### Accelerated contexts

Acceleration requires all of:

- a BC-250 (`1002:13fe`), or the experimental `BC250_XEFG_ANY_GPU=1` override
- `BC250_XEFG_DISABLE` not set to `1`
- a profile that matches the size and hash manifest embedded in the proxy
- the first eligible context selected at initialisation. Later contexts are not accelerated.

Without another mod hooking Intel's runtime, only one generated frame per real frame is accelerated. Beside
[such a mod](#another-mod-on-intels-runtime), only OptiScaler-created contexts qualify, at the factor the runtime
actually accepts. FreeFG does not raise Intel's frame-count limit.

A context rejected at creation keeps the caller's device and queue. The logs identify fallbacks and skips.

## Acceleration

For an accelerated context, the runtime receives scoped Direct3D 12 devices, queues and command lists. These forward
calls and track only that context's work. The game keeps its own objects.

| Mechanism | Effect |
| --- | --- |
| Pipeline replacement | Recognises 13 compute programs by bytecode hash and builds their replacements with the runtime's pipeline description and root signature. The [F4Q](#f4q) and [FP16](#fp16-forms) forms, on by default, select alternatives within this set. |
| Helper dispatches | Replaces selected convolutions with Winograd transform, multiply and inverse-transform passes, or with a fused refinement pass. The original bindings are restored afterwards. |
| Coefficient preparation | Gives uploaded coefficient buffers their own allocations with Intel's bytes and offsets, then appends the layouts that the replacement kernels use. Coefficients stay in memory. They are not shipped or saved. |
| Root-signature extension | Appends two scratch-buffer bindings to one root signature. Its first three parameters are unchanged. |
| Dispatch sizing | Applies the `dispatch-scale.txt` divisors, F4Q-specific group counts and refinement groups based on output size. |
| Runtime checks | Validates the expected network sizes, buffers and descriptor layouts. A mismatch before acceleration falls back to Intel's shaders. An unexpected later operation can log `FAIL` and end the process. Some coexistence failures [step aside](#stepping-aside) instead. |
| Frame-count changes | Reuses matching pipelines and coefficient sets. Released command lists and descriptor heaps are retired after the GPU finishes their work. |

[Stage timings](MEASUREMENTS.md#gpu-time-per-generated-frame).

### Generation signal

A worker updates a shared generation counter and heartbeat every 20 ms for the [pacing layer](#present-pacing). The
counter combines observed accelerated work with the SDK's `framesPresented - 1`. The SDK term keeps the signal working
when Intel's shaders run, including with `BC250_XEFG_DISABLE=1`. Status comes from the caller's queries or from one
extra query per frame, which `BC250_XEFG_STATUS_POLL=0` turns off. The shared page also reports the SDK's actual output
factor.

## Another mod on Intel's runtime

MFG Unlocker can hook Intel's entry points, distinguish callers by return address and replace some programs. FreeFG
detects those hooks and preserves the call patterns that coexistence needs. It does not inspect or modify MFG Unlocker's
module.

### Detection

At runtime load, the proxy reads the first 16 bytes of eight selected Intel exports from the verified DLL on disk. At
context creation, initialisation and destruction, it compares those bytes with memory, excluding relocations, and checks
the resolved export addresses. A difference means that another module hooks the runtime. The proxy logs it as
`FAST_COEXIST`.

### Caller preservation

`GetSwapChainPtr` and `TagFrameConstants` tail-call Intel. The four lifecycle wrappers do so when hooks are present,
which preserves the original caller's return address. Work that must happen afterwards is deferred to the next suitable
call: claiming the context's scoped device, confirming initialisation, preparing the network, or releasing destroyed
resources. `GetLastPresentStatus` and `SetNumInterpolatedFrames` remain ordinary wrapped calls.

`release/check_proxy_wine.py` tests this with stand-in hooks on all eight entries. It is a CPU-only loader test.

### OptiScaler contexts

With hooks present, the proxy accelerates only OptiScaler's contexts. It identifies OptiScaler by the creating module's
version resource. A game's native XeSS FG context is left on the caller's device, because other mods can require that
device to match the game's queue and swapchain. Such a context gets no FreeFG shader acceleration, even at 2×.

### Replaced programs

Only recognised Intel programs are replaced. Programs that the other mod substitutes have different hashes and stay
untouched. With MFG Unlocker 1.6.0, `XeFGModel=default` keeps the full Intel network and allows all 13 replacements. MFG
Unlocker's own model left seven replaceable programs in the tested Cyberpunk route.

### Stepping aside

A context that steps aside (`FAST_ASIDE`) runs Intel's or the other mod's shaders until it is destroyed. For a hooked
context, the triggers are an unsupported model census, a missing coefficient set and premature network work. Forwarding
tables revert to pass-through behaviour, replacement pipelines are rebound to Intel's originals, and network checks stop
for that context. Resources stay alive until destruction, because GPU work recorded earlier may still use them.

Without another mod, a failed model census steps aside the same way while a context is set up: before any frame, with
generated-frame scaling off. Intel's originals are then created from the pipeline cache. Other runtime consistency
checks can still end the process.

## Generated-frame scaling

Match output leaves the scaling hooks inactive. Settings apply at process startup. Logs distinguish requested settings
from actual scaling decisions. [Controls](CONFIGURATION.md#generated-frame-scaling).

### Observation

When scaling is requested, the proxy first observes one complete unmodified graph and checks its geometry, root layouts
and resource formats. An unsupported layout keeps full output. A new output size, input format, relevant pipeline or
frame count requires another observation.

A layout change after a scaled graph has begun remains a consistency error. The observation does not guarantee correct
handling of an arbitrarily modified runtime.

### Scaled path

While scaling is active:

- Scene and UI colour are resampled into private float textures. Those views are bound to Intel's original
  preprocessing, warp and final pipelines.
- The flow and reconstruction geometry is reduced.
- The U-Net uses bounded forms of the selected ordinary, F4Q or FP16 kernels. They keep each SDK allocation's padding
  and exclude stale pixels outside the reduced region. A logically invalid read is redirected to a physical
  out-of-bounds load, whose zero result preserves the original padding behaviour. At tiny sizes the virtual network
  keeps all five levels, including one-pixel levels.
- Engine depth and motion-vector resources and their coordinate conventions are retained.
- The final pass writes directly into a private reduced-size texture. Owned filter work enlarges it into the original
  SDK output. This avoids the former copy out of a larger generated buffer.

MFG Unlocker's default model repeats the native network, and each generated phase gets the same scaling treatment. Its
alternate model can keep full output while ordinary FreeFG acceleration continues. The F4Q shadow diagnostic also keeps
full output.

### Filters

| Stage | Choices |
| --- | --- |
| Reduction | Bilinear, Area |
| Enlargement | Bilinear, Catmull–Rom, Lanczos2, AMD FSR 1 EASU |

EASU uses AMD's CPU constants and keeps bilinear alpha. No RCAS sharpening or transfer-function conversion is added.
Colour intermediates use RGBA16 float, or RGBA32 float for a 32-bit float source.

### Resource reuse

- Immutable descriptor batches keep their resources until recorded lists release them and a queue fence confirms GPU
  completion. Resolution and HDR changes recycle completed batches.
- Read-only colour views share their reduction within one frame and command list.
- A history created by an SDK whole-resource copy can keep its reduced image across later frames on the same queue.
  Copies, transitions to writable states and aliasing barriers revoke that reuse. A wildcard aliasing barrier
  invalidates every cached history. Resetting an unsubmitted recording discards its pending reduction. Full-resolution
  history copies remain intact for fallback.
- Supported colour allocations also allow render-target compression without a change of format or precision.

## The shader profile

The installed `BC250-XeFG/shaders/` directory has **93 files**:

| Files | Count |
| --- | ---: |
| Hash-matched replacements | 13 |
| F4Q/F4Q2/F4Q3 alternatives | 7 |
| FP16 alternatives | 7 |
| Helper kernels: 15 for 2×, five for the multi-frame network | 20 |
| Diagnostic comparison kernels | 5 |
| Bounded convolution forms for scaling | 25 |
| Colour reduction/enlargement filters | 6 |
| Tables: `waves.txt`, `dispatch-scale.txt` | 2 |
| Feature markers (`*.required`) | 8 |

The 83 shaders are compiled from the supplied HLSL, including AMD's MIT-licensed EASU implementation. 81 use shader
model 6.6 and two use 6.9. The shipped wave table has 173 entries and the dispatch-scale table has 11.
[Rebuild instructions](BUILDING.md#the-shader-profile) ·
[Per-file recipes](https://github.com/daniel-h-0/freefg/blob/main/release/profile/ORIGIN.md).

### Exact arithmetic

The base convolutions rely on bounded integer arithmetic. FP32 represents integer partial sums below 2²⁴ exactly. Packed
16-bit paths require partial sums within their signed range. The model owner checks the coefficient conditions that
those paths require. Exact input transforms, omitted out-of-image work and an exact divide-by-four shift reduce work
further without changing the bounded results.

F(4×4) transforms have separate rounding considerations ([F4Q](#f4q)). The default [FP16 forms](#fp16-forms) trade exact
output for speed. Neither is bit-identical for every input.

### F4Q

F4Q uses Winograd F(4×4) tiles, which need fewer multiplications than F(2×2). F4Q covers two U-Net layers. F4Q2 adds
three encoders and F4Q3 adds two row layers. All are on by default. F4Q2 can be turned off separately. F4Q3 follows F4Q.

These paths matched Intel's generated images in the reported SDK comparisons and matched the earlier kernels in the
reported Cyberpunk comparisons. Constructed rounding-sensitive inputs produced differences in F4Q2 and one F4Q3 layer.
The evidence supports the tested cases. It does not show equivalence for every input.
[Counts, configurations and limitations](MEASUREMENTS.md#checks-of-112).

| Setting | Effect |
| --- | --- |
| `BC250_XEFG_F4Q=0` / `F4Q=0` | Disable F4Q, F4Q2, F4Q3 and all FP16 alternatives. Use the base F(2×2)/1D kernels. |
| `BC250_XEFG_F4Q2=0` / `F4Q2=0` | Disable the three F4Q2 encoders and their FP16 forms. Other F4Q paths remain enabled. |
| `BC250_XEFG_F4Q_SHADOW=1` | Diagnostic: base kernels produce the output while F(4×4) kernels run alongside for comparison. FP16 alternatives are disabled. Adds GPU work. |

File settings belong under `[BC250]` in `BC250-XeFG/settings.ini` beside the game's `.exe`, or in the file that
`BC250_XEFG_SETTINGS` names. Environment variables take precedence. The fast log records the effective choices as
`F4Q_CONFIG`, `F4Q2_CONFIG`, `F4Q3_CONFIG` and `FP16_CONFIG`. Diagnostic `F4Q_COUNT` lines contain comparison counts and
no tensor contents.

### FP16 forms

Seven alternatives are on by default. Their output is approximate:

- Three F4Q2 encoders read FP16 coefficient pairs, which rounds coefficients that need more precision.
- Four F(2×2) U-Net kernels use packed FP16 multiply-adds and combine their partial results.

On the 19 synthetic SDK scenes reported for 1.1.2, generated images differed from Intel's in 0.12–16.2% of pixels. Error
against analytic scene truth was 0.985–1.007× Intel's. Those figures do not establish perceptual equivalence. The
research quality gate did not pass every case. [Evidence](MEASUREMENTS.md#checks-of-112).

`BC250_XEFG_EXACT=1`, or `Exact=1` in the settings file, disables these seven alternatives. The F4Q-family paths stay
active. They matched Intel in the reported tests, with the limits in [F4Q](#f4q). `BC250_XEFG_EXACT=0` overrides a file
value of `1`. Turning F4Q off, or its shadow diagnostic on, also disables the FP16 alternatives.

Status and Check report the last session's mode from `FP16_CONFIG`. That report is no image-quality assessment.

## The pacing layer

`libxefg_wave.so` runs below vkd3d-proton. Launcher settings enable the layer and select its wave table.

### Present pacing

Pacing turns on automatically for Wine games when gamescope's environment is present. Explicit pacing outside gamescope
is unqualified. Native programs that inherit a game's environment (a nested gamescope, a native launcher) are never
paced.

The layer waits for rendered frames, then spaces their release using a moving estimate of the output period. After late
frames it adds a bounded jitter margin, which decays when timing settles.

| Policy | Bound |
| --- | --- |
| Jitter margin | Up to 5 ms at 2×, 10 ms at 3×, 15 ms at 4× |
| Hold relative to readiness | Up to 3.5 output periods; 4.5 at 4× |
| Swapchain capacity | Requests three extra images, subject to the surface limit |

Presents use a reserved compute queue when the driver has one. Otherwise they use the application's queue under a lock.
On stock gamescope, a short series of X-property changes wakes the compositor after a ready frame is released.

The layer creates a `0600` shared-memory page in `/dev/shm`, which the proxy updates with its
[generation signal](#generation-signal). Until the proxy's first heartbeat, presents and acquires go straight to the
driver. Launchers, a game before its XeFG context and processes without the proxy are therefore not paced. After the
first heartbeat, generation within the last 250 ms activates holding. With no generation, presents pass through.

`BC250_XEFG_PACE=0` disables pacing. `BC250_XEFG_PACE=1` holds every present. An older signal producer with no factor
field keeps the 5 ms margin ceiling.

These bounds are scheduling controls. End-to-end latency is not measured.
[TV evidence and remaining stalls](MEASUREMENTS.md#checks-of-113).

### Game-frame starts

This correction runs in the bundled OptiScaler, on its XeLL output. At 3× and 4×, it detects sustained alternating short
and long starts and delays starts that XeLL left clearly early. It runs after the XeLL sleep call. It resets after
loading gaps, multiplier changes or eight consecutive holds. It does not act at 2×. `BC250_XELL_PACE=0` disables it.

Regular output intervals alone cannot correct uneven simulation intervals.

### Wave sizes

The layer requests subgroup size 32 or 64 for pipelines that `waves.txt` lists by module hash. This changes compilation
and leaves the shader bytecode as it is. The table applies on the BC-250. `BC250_XEFG_ANY_GPU=1` applies it to any
device, for each size that device supports.

Since 1.1.3.1, `graph-prepare224.dxil` uses wave64 globally, after a Cyberpunk 2.5 bisection associated wave32 with
early faults. The underlying cause remains unresolved.

A wave request takes effect when a pipeline is compiled. Cached shader-module identifiers can hide the original bytecode
from the layer. Setup therefore disables `VK_EXT_shader_module_identifier` through `VKD3D_DISABLE_EXTENSIONS` and
normally assigns an installation-specific `VKD3D_SHADER_CACHE_PATH`. The layer then gets shader code to recognise on
each start, and older cache entries are isolated.

Setup keeps an explicit user cache path. If the game path is too long for vkd3d-proton's cache file names, Setup omits
both changes. Existing caches can then keep new wave choices from taking effect.
[Cache behaviour and measurements](MEASUREMENTS.md#shader-caches).

## OptiScaler

OptiScaler connects the game's DLSS, FSR, XeSS or OptiFG input to the upscaler (FSR 4 or HelixSR) and to XeFG. For
OptiScaler routes, Install selects XeFG output, XeLL latency support and borderless mode, and resets
`InterpolationCount=1` (2×). It writes `XeFGModel=default` where the key is unset. Only MFG Unlocker uses that key.
Recipes can adjust the inputs and game settings.

### HelixSR

HelixSR 3.3.0, by lonewolf0622, provides four upscalers. FreeFG places each in a custom provider folder of its own and
selects the folder name in `Upscalers.Dx12Upscaler`.

| Upscaler | Folder under `OptiScaler/custom/` | Runtime |
| --- | --- | --- |
| HLX DLSS Model E | `hlx-dlss/dlss/` | NGX |
| HLX DLSS Preset K | `hlx-dlss-k/dlss/` | NGX |
| HLX FSR 4 | `hlx-fsr4/ffx/` | FFX |
| HLX FSR 4 Full | `hlx-fsr4-full/ffx/` | FFX |

- Both FFX providers keep AMD's checked upscaler DLL beside them as `amd_fidelityfx_upscaler_dx12.amd.dll`.
- Preset K and HLX FSR 4 Full bring HelixSR's own settings file. An edited one is kept.
- An NGX provider's `helixsr.ini` keeps Helix's own frame generation off. No Helix FG files are copied.
- HLX DLSS keeps its `helixsr.dll` file name to avoid the NGX file-redirection hook. Renamed to `nvngx.dll`, it cannot
  read its embedded network on the tested integration.
- The recipe tables name upscaler rules per family: `helixsr` for both HLX DLSS networks, `hlx-fsr4` for both HLX FSR 4
  forms.
- Per-upscaler recipe settings apply only to unset or installer-owned values. Switching providers restores owned values
  where appropriate and preserves explicit or later user edits.
- A provider installed earlier can be selected again from its hash-checked game-local copy, even after the preparation
  cache is removed.

Legacy HelixSR 2.0.0 used the main FidelityFX DLL slot. Migration puts AMD FSR 4 in that slot. The previous Helix bytes
remain in the rollback generation, and the original backup remains available to Restore.

## The installer

`install.py` implements changes. `setup.py` starts Setup's GTK 4/libadwaita window (`setup_app.py`). The window shows
what `setup_model.py` reads from the installer and game folders, and runs every change as an `install.py` command in a
process of its own. Without GTK 4 and libadwaita 1.5, `setup.py` keeps its Zenity dialogs.

A manifest records installed files, original hashes, backups, launcher edits and recipe settings. Downloads are verified
separately by SHA-256. Each game is self-contained. There are no shared runtime symlinks and no resident update service.

### Launcher integration

Supported stores are Steam, Heroic and Lutris. The integration preserves existing options and wrappers and writes:

- the Wine DLL override for OptiScaler's loader module
- the layer's path and name
- the wave-table path
- `no_staggered_submit`
- the cache settings in [Wave sizes](#wave-sizes)

Per-file launcher locks coordinate installs and updates of separate games that share a config. Before runtime writes, a
generation saves and verifies launcher snapshots and entry deltas. Recovery reverts only those entries and preserves
other games and user additions. The exact original bytes and metadata return when no later change would be lost.

[PRIVACY.md](PRIVACY.md) lists the records read and written.

### Updates

In-place updates (`install.py update`, Setup's **Update All Games**) operate on a coherent FreeFG/Intel set and the
selected compatible upscaler. Core-only and upscaler-only updates use the same transaction engine, which owns all writes
and recovery.

`upscaler_updates.py` provides read-only adapters for pinned FidelityFX DLLs and the legacy HelixSR FidelityFX/network
format. `hlx.py` validates complete provider files, built or as shipped, and describes the custom NGX and FFX provider
layouts. Adapters only propose content and metadata. Unknown provider formats are deferred.

Update verifies current owned files, original backups, package hashes, integration compatibility and game idleness. It
rechecks observed files after preparing dependencies. Changed owned binaries block the coupled transaction. An
unavailable prepared provider can be deferred while compatible core changes proceed. The transaction saves old bytes,
permissions, modification times and component metadata before it records a pending operation. An interrupted update is
undone.

An explicit recipe refresh uses the same transaction for tested FG inputs and launcher arguments. Game settings are
listed as manual steps. Obsolete pending writes are marked inactive, and their original ownership remains available to
Restore.

### Update contract

`manifest.json.update_contract` and the game record agree on format, layout and configuration versions. The game record
carries an installation ID and component identities.

- Legacy 1.1.3.1, 1.1.4 and 1.1.5 records are explicitly imported.
- Core version downgrades are refused. Rollback uses saved bytes.
- Format 2 supports integration DLL and loader migrations, additive INI defaults and token-aware launcher deltas.
- Unknown layouts remain unsupported.

### Rollback and Restore

Rollback restores the saved generation. It preserves later settings edits and provider choices outside the update's
scope, and refuses conflicting binary edits. An interrupted rollback finishes before another update starts. Missing or
damaged recovery data leaves the journal intact.

One completed generation of each kind is kept per game, and Rollback undoes the newest
([kinds](INSTALLATION.md#updates-and-recovery)). Recovery is per game: there is no atomic transaction across a library.

An upscaler switch records a pending operation, so Restore can recover from an interruption. Edited `helixsr.ini` values
are retained for later use. Restore reverts owned files and settings and preserves later user edits. Changed binaries
can require attention. [Updates and recovery](INSTALLATION.md#updates-and-recovery).

### Helix preparation

Helix preparation runs upstream's build-only entry point in a bubblewrap sandbox
([SECURITY.md](SECURITY.md#the-installer)). It has no network, a read-only host, hidden home folder and session sockets,
and one writable staging directory. The qualified preparation replaces the shared cache atomically. Games keep
independent copies. No model-bearing output enters release artifacts.

### Library index

`freefg_library.py` maintains an optional index that is locked and replaced atomically. Update all combines this index
with Steam, Heroic and Lutris discovery. Game records remain authoritative, and an index failure does not invalidate a
completed game transaction. Missing drives remain listed as unavailable. Registration can be rebuilt without
reinstalling runtime files. Pins apply to both core and provider updates.

## The compatibility check

`gamescan.py` reads executable metadata and launcher records. `compat.py` combines that detection with
`recipes/recipes.json`. Check is offline and does not run game files. It produces the verdict and plan that Install
uses. [Verdicts](COMPATIBILITY.md#verdicts).

### Source order

Explicit user input choices, INI values and launch options take precedence. The remaining sources are combined in this
order:

1. Curated BC-250 recipe.
2. OptiScaler's built-in game fixes, whose keys are left to OptiScaler.
3. Reviewed community recipe.
4. Promoted wiki fixes, applied only on a strong game match.
5. Wiki reports of broken inputs.
6. Executable detection.
7. Installer defaults.

Wiki entries are community evidence without BC-250 qualification. Some advice is only shown to the user.

## Run-time changes

FreeFG keeps Intel's DLL bytes intact and changes part of its GPU execution. [Intel's terms](NOTICE.md#intels-terms)
apply to that distinction.

| Area | Change |
| --- | --- |
| CPU module | No FreeFG hooks or patches in Intel's module. Calls use its exports. |
| GPU work | Recognised pipelines, selected convolutions, coefficient layouts, scratch bindings and dispatch counts are replaced or extended ([Acceleration](#acceleration)). |
| Vulkan compilation | Wave-size requests for entries in the 173-entry table on the BC-250. |
| Presentation | Output frames are delayed and released in order. OptiScaler separately adjusts some 3× and 4× game-frame starts. |
| Frame-count limit | Unchanged by FreeFG. Higher factors require a separate tool. |

`BC250_XEFG_DISABLE=1` disables shader and network acceleration. The SDK generation signal, pacing layer and wave table
remain active. To compare Intel's shaders without FreeFG's wave overrides, point `XEFG_WAVE_CONFIG` to an empty file. To
compare without pacing as well, set `BC250_XEFG_PACE=0` and `BC250_XELL_PACE=0`.
