# How FreeFG works

FreeFG runs inside a DirectX 12 game under Proton:

```
game
 ├─ OptiScaler ── FSR 4 or HelixSR: upscaling
 ├─ libxess_fg.dll: FreeFG proxy ── bc250_xefg_original.dll: Intel XeFG runtime
 ├─ BC250-XeFG/shaders/: replacement shaders and helper kernels
 └─ vkd3d-proton → libxefg_wave.so → Mesa RADV → gamescope
```

The proxy accelerates part of XeFG's GPU work. The Vulkan layer selects wave sizes and schedules output frames.
The bundled OptiScaler also corrects uneven game-frame starts at 3×/4×. These are separate mechanisms.

## The proxy

Native XeSS FG games and OptiScaler's XeFG output load the proxy as `libxess_fg.dll`. Intel's unmodified runtime sits
beside it as `bc250_xefg_original.dll`.

### Exports

The proxy preserves Intel runtime 1.3.1.78's **57 exports and ordinals**: 49 forward directly and eight are wrapped.
Four additional exports provide FreeFG's settings/initialisation interface.

| Wrapped calls | Work before or after forwarding |
| --- | --- |
| `xefgSwapChainD3D12CreateContext`, `xefgSwapChainD3D12InitFromSwapChain`, `xefgSwapChainD3D12InitFromSwapChainDesc`, `xefgSwapChainDestroy` | Context and resource lifecycle |
| `xefgSwapChainSetNumInterpolatedFrames` | Frame-count changes and resource retirement |
| `xefgSwapChainGetLastPresentStatus` | Generation signal |
| `xefgSwapChainD3D12GetSwapChainPtr`, `xefgSwapChainTagFrameConstants` | Deferred initialisation; per-frame status polling |

### Loading Intel's runtime

The first wrapped call checks the runtime's pinned size and FNV-1a hash, then loads it by absolute path. A missing or
changed runtime produces `XEFG_SWAPCHAIN_RESULT_ERROR_CANT_LOAD_LIBRARY` and a reason in `BC250-MFG.log`.
FNV-1a is an identity check, not a cryptographic security boundary; installation uses SHA-256.

The proxy imports only `kernel32.dll` and `ucrtbase.dll`. It does not patch Intel's code or the game's Direct3D method
tables. It provides separate forwarding objects to the runtime.

### Which contexts are accelerated

Acceleration requires:

- a BC-250 (`1002:13fe`), or the experimental `BC250_XEFG_ANY_GPU=1` override;
- `BC250_XEFG_DISABLE` not set to `1`;
- a profile matching the size/hash manifest embedded in the proxy;
- the first eligible context selected at initialisation. Later contexts are not accelerated.

Without another mod hooking Intel's runtime, only one generated frame per real frame is accelerated. Beside such a
mod, only OptiScaler-created contexts qualify, at the factor the runtime actually accepts. FreeFG does not raise
Intel's frame-count limit. A context rejected at creation keeps the caller's device and queue; logs identify
fallbacks and skips.

## Inside an accelerated context

The runtime receives scoped Direct3D 12 devices, queues and command lists. These forward calls while tracking only
that context's work; the game retains its own objects.

| Mechanism | Effect |
| --- | --- |
| Pipeline replacement | Recognises 13 compute programs by bytecode hash and builds their replacements with the runtime's pipeline description/root signature. F4Q/FP16 forms, enabled by default, select alternatives within this set. |
| Helper dispatches | Replaces selected convolutions with Winograd transform/multiply/inverse-transform passes or a fused refinement pass. Original bindings are restored afterwards. |
| Coefficient preparation | Gives uploaded coefficient buffers their own allocations, preserving Intel's bytes and offsets, then appends layouts used by the replacement kernels. Coefficients remain in memory and are not shipped or saved. |
| Root-signature extension | Appends two scratch-buffer bindings to one root signature; its first three parameters remain unchanged. |
| Dispatch sizing | Applies `dispatch-scale.txt` divisors, F4Q-specific group counts and output-size-based refinement groups. |
| Runtime checks | Validates the expected network sizes, buffers and descriptor layouts. A pre-acceleration mismatch falls back; an unexpected later operation can log `FAIL` and end the process. Some coexistence failures instead [step aside](#stepping-aside). |
| Frame-count changes | Reuses matching pipelines/coefficient sets and retires released command lists and descriptor heaps after the GPU finishes their work. |

A worker updates a shared generation counter and heartbeat every 20 ms. The counter combines observed accelerated
work with the SDK's `framesPresented - 1`. The latter keeps the signal working when Intel's shaders run, including
with `BC250_XEFG_DISABLE=1`. Status comes from the caller's queries or a per-frame query; `BC250_XEFG_STATUS_POLL=0`
disables the additional query. The page also reports the SDK's actual output factor.

[Stage timings](MEASUREMENTS.md#gpu-time-per-generated-frame) · [Pacing](#the-pacing-layer).

## Another mod on Intel's runtime

MFG Unlocker can hook Intel's entry points, distinguish callers by return address and replace some programs.
FreeFG detects those hooks and preserves the call patterns needed for coexistence. It does not inspect or modify
MFG Unlocker's module.

### Detection

At runtime load, the proxy reads the first 16 bytes of eight selected Intel exports from the verified DLL on disk.
At context creation, initialisation and destruction, it compares those bytes with memory, excluding relocations, and
checks the resolved export addresses. A difference produces `FAST_COEXIST`.

### Callers kept

`GetSwapChainPtr` and `TagFrameConstants` tail-call Intel. The four lifecycle wrappers do so when hooks are present,
preserving the original caller's return address. Work that must happen afterwards is deferred to the next suitable
call: claim the context's scoped device, confirm initialisation, prepare the network, or release destroyed resources.
`GetLastPresentStatus` and `SetNumInterpolatedFrames` remain ordinary wrapped calls.

`release/check_proxy_wine.py` tests this with stand-in hooks on all eight entries; it is a CPU-only loader test.

### OptiScaler's contexts only

With hooks present, the proxy identifies OptiScaler by the creating module's version resource. A game's native XeSS
FG context is left on the caller's device because other mods can require that device to match the game's queue and
swapchain. Such a context receives no FreeFG shader acceleration, even at 2×.

### Own shaders on Intel's remaining work

Only recognised Intel programs are replaced. Programs substituted by the other mod have different hashes and remain
untouched. With MFG Unlocker 1.6.0, `XeFGModel=default` retains the full Intel network and allows all 13 replacements;
its own model left seven replaceable programs in the tested Cyberpunk route.

### Stepping aside

For a hooked context, an unsupported model census, missing coefficient set or premature network work triggers
`FAST_ASIDE`. Forwarding tables revert to pass-through behavior, replacement pipelines are rebound to Intel's
originals, and network checks stop for that context. Resources remain alive until destruction because previously
recorded GPU work may still use them. Other runtime consistency checks can still terminate the process.

## Generated-frame scaling

Match output leaves the scaling hooks inactive. When scaling is requested, the proxy first observes a complete
unmodified graph and checks its geometry, root layouts and resource formats. An unsupported observed layout keeps
full output. A new output size, input format, relevant pipeline or frame count requires another observation.

The active path resamples scene/UI colour into private float textures, binds those views to Intel's original
preprocessing, warp and final pipelines, and reduces the flow and reconstruction geometry. The U-Net uses bounded
forms of the selected ordinary, F4Q or FP16 kernels, preserving each SDK allocation's padding while excluding stale
pixels outside the reduced region. Logically invalid reads redirect to a physical out-of-bounds load, whose
zero result preserves the original padding behavior. At tiny sizes the virtual network keeps all five levels, including one-pixel
levels. Engine depth and motion-vector resources and their coordinate conventions are retained.

The final pass writes directly into a private reduced-size texture. Owned filter work enlarges it into the original
SDK output, avoiding the former copy out of a larger generated buffer. Bilinear and Area are reduction choices; Bilinear, Catmull–Rom, Lanczos2 and AMD FSR 1 EASU are enlargement
choices. EASU uses AMD's CPU constants and keeps bilinear alpha. No RCAS sharpening or transfer-function conversion
is added. Colour intermediates use RGBA16 float, or RGBA32 float for a 32-bit float source.

Immutable descriptor batches keep their resources until recorded lists release them and a queue fence confirms GPU
completion. Read-only colour views share their reduction within one frame and command list. A history created by an
SDK whole-resource copy can keep its reduced image across later frames on the same queue. Copies, transitions to
writable states and aliasing barriers revoke that reuse; a wildcard aliasing barrier invalidates every cached history.
Resetting an unsubmitted recording discards its pending reduction. Full-resolution history copies remain intact for
fallback. Supported colour allocations also allow render-target compression without changing their format or precision.
Resolution/HDR changes recycle completed batches. MFG Unlocker's default model repeats the native network; each
generated phase receives the same scaling treatment. Its alternate model can retain full output while
ordinary FreeFG acceleration continues. The F4Q shadow diagnostic also retains full output.

Settings apply at process startup. Logs distinguish requested settings from actual scaling decisions. Layout changes
after a scaled graph has begun remain consistency errors; the observation gate is not a guarantee for an arbitrary
modified runtime. [Controls](README.md#generated-frame-scaling).

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

The 83 shaders are compiled from the supplied HLSL, including AMD's MIT-licensed EASU implementation: 81 use shader
model 6.6 and two use 6.9. The shipped wave table has 173 entries; the dispatch-scale table has 11. [Rebuild instructions](BUILDING.md#the-shader-profile) and
[per-file recipes](../../release/profile/ORIGIN.md).

### Exact arithmetic

The base convolutions exploit bounded integer arithmetic: FP32 represents integer partial sums below 2²⁴ exactly,
and packed 16-bit paths require partial sums within their signed range. The model owner checks the coefficient
conditions required by those paths. Exact input transforms, omitted out-of-image work and an exact divide-by-four
shift further reduce work without changing the bounded results.

F(4×4) transforms have separate rounding considerations. The default FP16 forms deliberately trade exact output for
speed. Neither should be described as universally bit-identical.

### F4Q: rounding and tested equivalence

F4Q uses Winograd F(4×4) tiles to reduce multiplications compared with F(2×2). It covers two U-Net layers; F4Q2 adds
three encoders, and F4Q3 adds two row layers. All are enabled by default. F4Q2 can be disabled separately; F4Q3 follows
F4Q.

These paths matched Intel's generated images in the reported SDK comparisons and matched the earlier kernels in the
reported Cyberpunk comparisons. Constructed rounding-sensitive inputs produced differences in F4Q2 and one F4Q3
layer. The evidence supports the tested cases, not equivalence for every input.
[Counts, configurations and limitations](MEASUREMENTS.md#checks-of-112).

| Setting | Effect |
| --- | --- |
| `BC250_XEFG_F4Q=0` / `F4Q=0` | Disable F4Q, F4Q2, F4Q3 and all FP16 alternatives. Use the base F(2×2)/1D kernels. |
| `BC250_XEFG_F4Q2=0` / `F4Q2=0` | Disable the three F4Q2 encoders and their FP16 forms; other F4Q paths remain enabled. |
| `BC250_XEFG_F4Q_SHADOW=1` | Diagnostic: base kernels produce output while F(4×4) kernels run alongside for comparison. FP16 alternatives are disabled. Adds GPU work. |

File settings belong under `[BC250]` in `BC250-XeFG/settings.ini`; environment variables take precedence. The fast log
records effective choices as `F4Q_CONFIG`, `F4Q2_CONFIG`, `F4Q3_CONFIG` and `FP16_CONFIG`. Diagnostic `F4Q_COUNT` lines
contain comparison counts, not tensor contents.

<a id="fp16-forms-the-default-slightly-different"></a>

### FP16 forms: approximate output by default

Seven alternatives are enabled by default:

- Three F4Q2 encoders read FP16 coefficient pairs, rounding coefficients that require more precision.
- Four F(2×2) U-Net kernels use packed FP16 multiply-adds and combine their partial results.

On the 19 synthetic SDK scenes reported for 1.1.2, generated images differed from Intel's in 0.12–16.2% of pixels;
error against analytic scene truth was 0.985–1.007× Intel's. Those figures do not establish perceptual equivalence.
The research quality gate did not pass every case. [Evidence](MEASUREMENTS.md#checks-of-112).

`BC250_XEFG_EXACT=1`, or `Exact=1` in the settings file, disables these seven alternatives. F4Q-family paths remain
active and matched Intel in the reported tests, with the limitations above. `BC250_XEFG_EXACT=0` overrides a file value
of `1`. F4Q off or its diagnostic also disables FP16 alternatives.

Status and Check report the last session's mode from `FP16_CONFIG`; this is not an image-quality assessment.

## The pacing layer

`libxefg_wave.so` runs below vkd3d-proton. Launcher settings enable the layer and select its wave table. Automatic
pacing is enabled when gamescope's environment is present; explicit pacing outside gamescope is unqualified.

### Present pacing (gamescope only)

The layer waits for rendered frames, then spaces their release using a moving output-period estimate. After late
frames it adds a bounded jitter margin, which decays when timing settles.

| Policy | Bound |
| --- | --- |
| Jitter margin | Up to 5 ms at 2×, 10 ms at 3×, 15 ms at 4× |
| Hold relative to readiness | Up to 3.5 output periods; 4.5 at 4× |
| Swapchain capacity | Requests three extra images, subject to the surface limit |

Presents use a reserved compute queue when available, otherwise the application's queue under a lock. On stock
gamescope, a short series of X-property changes wakes the compositor after a ready frame is released.

The layer creates a `0600` shared-memory page in `/dev/shm`; the proxy updates it. Generation within the last 250 ms
activates holding. With a healthy signal and no generation, presents pass through. If the page is unavailable or no
heartbeat arrives within three seconds, the fallback holds every present. `BC250_XEFG_PACE=0` disables pacing;
`=1` forces holding. An older signal producer with no factor field retains the 5 ms margin ceiling.

These bounds are scheduling controls, not measured end-to-end latency. [TV evidence and remaining stalls](MEASUREMENTS.md#checks-of-113).

### Game-frame starts (OptiScaler XeLL output)

At 3×/4×, the bundled OptiScaler detects sustained alternating short/long starts and delays starts left clearly early
by XeLL. It runs after the XeLL sleep call, resets after loading gaps, multiplier changes or eight consecutive holds,
and does not act at 2×. `BC250_XELL_PACE=0` disables it. Regular output intervals alone cannot correct uneven
simulation intervals.

### Wave sizes (BC-250 only)

The layer requests subgroup size 32 or 64 for pipelines recognised by module hash in `waves.txt`. This changes
compilation, not shader bytecode. Since 1.1.3.1, `graph-prepare224.dxil` uses wave64 globally after a Cyberpunk 2.5
bisection associated wave32 with early faults. The underlying cause remains unresolved.

A wave request takes effect at pipeline compilation. Cached shader-module identifiers can hide the original bytecode
from the layer. Setup therefore disables `VK_EXT_shader_module_identifier` through `VKD3D_DISABLE_EXTENSIONS` and
normally assigns an installation-specific `VKD3D_SHADER_CACHE_PATH`. This gives the layer shader code to recognise on
each start and isolates older cache entries.

An explicit user cache path is preserved. If the game path is too long for vkd3d-proton's cache filenames, Setup omits
both changes; existing caches can then prevent new wave choices from taking effect.
[Cache behavior and measurements](MEASUREMENTS.md#shader-caches).

## OptiScaler and the upscaler

OptiScaler connects the game's DLSS, FSR, XeSS or OptiFG input to FSR 4/HelixSR and XeFG. Install selects XeFG output,
XeLL latency support and borderless mode for OptiScaler routes, and resets `InterpolationCount=1` (2×). It writes
`XeFGModel=default` where unset; only MFG Unlocker uses that key. Recipes can adjust the inputs and game settings.

### HelixSR

HelixSR 3.1.0, by lonewolf0622, provides distinct HLX DLSS (NGX) and HLX FSR 4 (FFX) upscalers.
FreeFG places them under `OptiScaler/custom/hlx-dlss/dlss/` and `OptiScaler/custom/hlx-fsr4/ffx/`, and selects their
custom folder names in `Upscalers.Dx12Upscaler`. The FFX provider keeps its checked AMD companion beside it.
`helixsr.ini` disables Helix’s own frame generation; its FG files are not copied. Legacy HelixSR 2.0.0 used the
main FidelityFX DLL slot; migration retains that owned file and its original backup until Restore.

For Cyberpunk 2.5 with HLX DLSS or HLX FSR 4, the recipe sets `InitFlags.DisableReactiveMask=true`. The per-upscaler recipe applies
only to unset/automatic values. Configure restores an owned value when switching to FSR 4 and preserves explicit
pre-installation choices or later edits. The recipe is stored with the installation so switching still works if the
launcher registration disappears. This workaround changes an upscaler input; it is not an image-equivalence claim.

## The installer

`install.py` implements changes; `setup.py` is the Zenity front end. A manifest records installed files, original
hashes, backups, launcher edits and recipe settings. Downloads are verified separately by SHA-256.

The launcher integration writes the proxy override, layer path/name, wave-table path, `no_staggered_submit`, and the
cache settings above. It preserves existing options and wrappers. Supported stores are Steam, Heroic and Lutris;
[PRIVACY.md](PRIVACY.md) lists the records read and written.

Upscaler switches record a pending operation so Restore can recover from interruption. Edited `helixsr.ini` values
are retained for later use. Restore reverts owned files and settings while preserving subsequent user edits; changed
binaries can require attention. [Installation and removal](README.md#restore-and-uninstall).

In-place updates (`install.py update`, Setup's **Update all**) operate on a coherent FreeFG/Intel set and the
selected compatible upscaler. `upscaler_updates.py` provides read-only adapters for pinned FidelityFX DLLs and the
legacy HelixSR FidelityFX/network format. `hlx.py` validates complete prepared model files and describes separate
custom NGX and FFX provider layouts. HLX DLSS retains its `helixsr.dll` filename to avoid the NGX file-redirection
hook; renaming it `nvngx.dll` prevents it from reading its embedded network on the tested integration. Adapters propose content and metadata; the shared transaction engine owns
all writes and recovery. Unknown provider formats are deferred. Core-only and upscaler-only updates use the same
engine. HLX preparation uses upstream’s build-only entry point inside a read-only host mount with network access
disabled and only its staging directory writable. The qualified preparation replaces the shared cache atomically;
games retain independent copies. No model-bearing output enters release artifacts.

Update verifies current owned files, original backups, package hashes, integration compatibility and game idleness.
It rechecks observed files after preparing dependencies. Changed owned binaries block the coupled transaction. An unavailable prepared provider can be deferred while
compatible core changes proceed. The transaction saves old bytes, permissions, modification times and component
metadata before recording a pending operation. Rollback restores that generation, preserves later settings edits and
provider choices outside the update's scope, and refuses conflicting binary edits. Interrupted updates are undone;
interrupted rollbacks finish before another update starts. Missing or damaged recovery data leaves the journal intact.
One completed generation is retained per game. This is per-game recovery, not an atomic transaction across a library.

`manifest.json.update_contract` and the game record agree on format, layout and configuration versions. Legacy
1.1.3.1/1.1.4/1.1.5 records are explicitly imported. Core version downgrades are refused; Rollback uses saved bytes.
The game record carries an installation ID and component identities. Format 2 supports integration DLL and loader
migrations, additive INI defaults and token-aware launcher deltas. Per-file launcher locks coordinate updates to
separate games sharing a config. Before runtime writes, the generation saves and verifies launcher snapshots and
entry deltas. Recovery reverts only those entries, preserving other games and user additions; exact original bytes
and metadata return when no later changes would be lost. Unknown layouts remain unsupported. Provider switches
also create generations, so Rollback always means the latest completed update or switch. Explicit recipe refresh
uses the same transaction for tested FG inputs and launcher arguments. Game settings are listed as manual steps;
obsolete pending writes are marked inactive while their original ownership remains available to Restore.

`freefg_library.py` maintains an optional, locked and atomically replaced index. Update all combines this index with
Steam/Heroic/Lutris discovery; game records remain authoritative. Index failures do not invalidate a completed game
transaction. Missing drives remain listed as unavailable. Registration can be rebuilt without reinstalling runtime
files. Each game is self-contained; there are no shared runtime symlinks or resident update service. A user-managed
deployment hook may invoke the batch CLI after extracting a verified package, using its exit status and per-game
summary. Pins apply to both core and provider updates.

## The compatibility check

`gamescan.py` reads executable metadata and launcher records; `compat.py` combines detection with
`recipes/recipes.json`. Check is offline and does not run game files. It produces the verdict and plan used by Install.
[Verdicts](COMPATIBILITY.md#verdicts).

### Which source decides

Explicit user input choices, INI values and launch options take precedence. The remaining sources are combined in
this order:

1. Curated BC-250 recipe.
2. OptiScaler's built-in game fixes, whose keys are left to OptiScaler.
3. Reviewed community recipe.
4. Promoted wiki fixes, applied only on a strong game match.
5. Wiki reports of broken inputs.
6. Executable detection.
7. Installer defaults.

Wiki entries are community evidence, not BC-250 qualification. Some advice is displayed for the user rather than
applied automatically.

## What is changed at run time

FreeFG keeps Intel's DLL bytes intact but changes part of its GPU execution. [Intel's terms](NOTICE.md#intels-terms)
apply to that distinction.

| Area | Change |
| --- | --- |
| CPU module | No FreeFG hooks or patches in Intel's module; calls use its exports. |
| GPU work | Recognised pipelines, selected convolutions, coefficient layouts, scratch bindings and dispatch counts are replaced or extended as described above. |
| Vulkan compilation | Wave-size requests for the 142 listed programs on the BC-250. |
| Presentation | Output frames are delayed and released in order. OptiScaler separately adjusts some 3×/4× game-frame starts. |
| Frame-count limit | Unchanged by FreeFG; higher factors require a separate tool. |

`BC250_XEFG_DISABLE=1` disables shader/network acceleration. The SDK generation signal, pacing layer and wave table
remain active. To compare Intel's shaders without FreeFG's wave overrides, point `XEFG_WAVE_CONFIG` to an empty file;
to compare without pacing, also disable `BC250_XEFG_PACE` and `BC250_XELL_PACE`.
