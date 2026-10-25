# How FreeFG works

Four parts run in the game process, set up by the installer and the compatibility check:

```
game (DirectX 12, under Proton)
 ├─ OptiScaler (dxgi.dll) ── FSR 4 or HelixSR (upscaling)
 ├─ libxess_fg.dll (the proxy) ──> bc250_xefg_original.dll (Intel's XeFG runtime, unmodified)
 ├─ BC250-XeFG/shaders/ (the shader profile)
 └─ Vulkan: vkd3d-proton → libxefg_wave.so (the pacing layer) → Mesa RADV → gamescope
```

## The proxy

Games with native XeSS frame generation, and OptiScaler with XeFG output, load `libxess_fg.dll` from the game folder:
the proxy, with Intel's runtime beside it as `bc250_xefg_original.dll`.

### Exports

The proxy exports the 57 entry points of Intel's runtime 1.3.1.78 at the same ordinals (checked at build). 49 are
forwarders the Windows loader binds to Intel's DLL, unseen by the proxy's code; the other 8 do FreeFG's bookkeeping
and call Intel's function of the same name through Intel's export table:

| Wrapped entry | Purpose |
| --- | --- |
| `xefgSwapChainD3D12CreateContext`, `xefgSwapChainD3D12InitFromSwapChain`, `xefgSwapChainD3D12InitFromSwapChainDesc`, `xefgSwapChainDestroy` | Context lifecycle: scoped objects, setup, release |
| `xefgSwapChainSetNumInterpolatedFrames` | Frame count: retires what the old count used |
| `xefgSwapChainGetLastPresentStatus` | Presented frames, for the generation signal |
| `xefgSwapChainD3D12GetSwapChainPtr` | First call after an initialisation |
| `xefgSwapChainTagFrameConstants` | Once per frame: reads the present status |

The last four also run initialisation work deferred while another mod hooks the runtime ([Callers kept](#callers-kept)).
Four exports after Intel's last ordinal are FreeFG's settings interface and initialisation call.

### Loading Intel's runtime

On the first call, the proxy checks `bc250_xefg_original.dll` against the pinned size and FNV-1a hash and loads it by
absolute path. If it is missing or different, every wrapped entry returns
`XEFG_SWAPCHAIN_RESULT_ERROR_CANT_LOAD_LIBRARY`, no XeFG context is created, and `BC250-MFG.log` says why. The proxy
imports only `kernel32.dll` and `ucrtbase.dll`, installs no hooks, writes nothing into Intel's module, and leaves the
game's Direct3D objects and method tables alone.

### Which contexts are accelerated

A context is accelerated when the GPU is the BC-250 (PCI ID `1002:13fe`) or `BC250_XEFG_ANY_GPU=1` is set,
`BC250_XEFG_DISABLE=1` is not, every shader profile file matches the manifest built into the proxy (size and hash; only
listed files are loaded), and it is the process's first XeFG context. Without another mod on Intel's runtime, the
runtime must also generate one frame per real frame (its limit on GPUs other than Intel's); beside another mod,
OptiScaler must have created the context, which is then accelerated at any frame count.

Any other context runs entirely on Intel's shaders, with the reason in `BC250-MFG.log` or `BC250-XeFG-fast.log`
(`FAST_FALLBACK`, `FAST_SKIP`). One ruled out at creation (another GPU, `BC250_XEFG_DISABLE=1`, a second context, a
game's own context beside another mod) also gets the caller's own device and queue.

## Inside an accelerated context

The proxy hands Intel's runtime scoped Direct3D 12 objects in place of the game's device, command queue and command
lists. They forward every call to the real objects and show FreeFG the pipelines the runtime creates, the buffers it
uploads and the dispatches it records; the game keeps its own objects. On the runtime's work:

1. Pipeline substitution: a compute pipeline whose bytecode hash has a shader in the profile is built from that shader,
   with the runtime's own root signature and pipeline description. For seven of them, F4Q (on by default) builds the
   pipeline from a second, faster shader of the profile (`<hash>.f4q.dxil`; [below](#f4q-identical-in-every-test-not-proven)):
   the U-Net decoder `b3941ac8` and encoder `f030948d`, with F4Q2 the encoders `1a3b0782`, `e83e868f` and
   `9e0080ee`, and with F4Q3 the row layers `60edebbb` and `b3ddf030`. By default seven U-Net pipelines are built from
   their FP16 form instead (`<hash>.fp16.dxil`; [below](#fp16-forms-the-default-slightly-different)). If such a
   pipeline cannot be created, the regular shader is used for it (`F4Q_FALLBACK`, `FP16_FALLBACK` in the fast log).
2. Kernel substitution: some of the network's convolution dispatches are recorded as FreeFG's kernels at the same
   point in the command list, and the runtime's pipeline and bindings are restored after them. The kernels compute the
   same convolution in the Winograd domain (transform, multiply, inverse transform) or as one fused refinement pass.
3. Coefficient layouts: the runtime uploads the network's coefficients (weights, biases, quantisation slopes) to GPU
   buffers at initialisation. FreeFG gives those buffers their own allocations and appends pre-transformed copies
   after Intel's bytes, which keep Intel's offsets, so Intel's shaders read exactly what the runtime uploaded;
   FreeFG's kernels read the copies through widened views. This is all in memory, every session; no coefficient
   is written to disk or shipped.
4. Root signature extension: one root signature gets two buffer bindings appended (Winograd scratch space), its first
   three parameters unchanged. Pipelines created on it, Intel's included, run with the extension, whose bindings
   Intel's shaders do not declare.
5. Dispatch sizes: replacement shaders that cover more pixels per thread group get their group counts divided
   (`dispatch-scale.txt`); a dispatch that binds an F4Q pipeline gets that shader's own group counts, and the fused
   refinement's groups are counted from the output size.
6. Checks that end the game: the kernels fit the pinned runtime's network sizes and buffer and descriptor layouts (2×
   and multi-frame networks). A mismatch before acceleration starts sends the context to Intel's shaders; anything
   unexpected later (another buffer write, an unknown layout) makes FreeFG log `FAIL` and end the process rather than
   show unverified frames. Beside another mod, the network make-up checks [step aside](#stepping-aside) instead.
7. Generation signal: every 20 ms the proxy writes a count to a shared-memory page that the pacing layer reads. It
   advances with the accelerated passes and with the frames the runtime reports presented (`framesPresented` − 1 per
   present, from the caller's status queries or else one query per frame), so it moves whenever XeFG generates, also on
   Intel's shaders.
8. Frame-count changes: the runtime rebuilds its pipelines and resources. FreeFG reuses identical pipelines and
   coefficient sets (pooled) and, once the GPU has finished the old count's work, stops tracking the command lists and
   descriptor heaps the runtime released.

GPU time by stage: [MEASUREMENTS.md](MEASUREMENTS.md#gpu-time-per-generated-frame).

## Another mod on Intel's runtime

A tool such as MFG Unlocker hooks Intel's runtime in memory, patching its entry points and parts of its code, and may
tell callers apart by return address (the game, OptiScaler, the runtime itself). FreeFG neither patches nor reads
such a module; it detects the hooks.

### Detection

When the runtime loads, FreeFG reads the first 16 bytes of eight entry points (the wrapped ones except
`xefgSwapChainD3D12GetSwapChainPtr`, plus `xefgSwapChainGetProperties`) from `bc250_xefg_original.dll` on disk, through
its own parse of the export table. At every context creation, initialisation and destruction it compares them with
memory, skipping relocated bytes, and checks that `GetProcAddress` still returns the export's own address; a difference
is logged once (`FAST_COEXIST`, `BC250-MFG.log`).

### Callers kept

`xefgSwapChainD3D12GetSwapChainPtr` and `xefgSwapChainTagFrameConstants` always tail-call Intel's entry, and the four
lifecycle entries do while another module hooks the runtime, so that module sees the return address of the proxy's
caller (OptiScaler or the game). The proxy's own work after those calls moves:

- Initialisation (or destruction, if never initialised) claims the scoped device of the context's creation: the
  creation whose output holds the handle, else the only pending one on the device of the initialisation's queue.
- The first later call with the handle (usually `xefgSwapChainD3D12GetSwapChainPtr`, made right after initialising;
  else the frame count, present status or frame tag) completes the initialisation (model census, network setup) before
  reaching Intel, once `xefgSwapChainD3D12GetInitializationParameters` confirms it, so the census holds only what the
  initialisation allocated.
- The next creation or initialisation releases a destroyed context's resources.

`xefgSwapChainGetLastPresentStatus` and `xefgSwapChainSetNumInterpolatedFrames` take the context first and stay ordinary
calls. `release/check_proxy_wine.py --variant intel-free-mfg` tests the callers with a stand-in hook on eight entries.

### OptiScaler's contexts only

Beside another mod, only contexts OptiScaler created (by the creating module's version resource) are accelerated. A
game's own XeFG context keeps the game's device: such a mod may compare the device Intel gets with that of the game's
queue and swap chain, which FreeFG's forwarding device never matches, so frame generation would not start. That
context runs Intel's or the other mod's shaders at every frame count, 2× included. On this route MFG Unlocker works
only where OptiScaler is loaded (Setup loads it for FSR 4), and the game sets the frame count.

### Own shaders on Intel's remaining work

An accelerated context keeps pipeline substitution at every frame count, on every pipeline the runtime still creates
from Intel's bytecode; a program the other module substituted has another hash and is left alone. FreeFG also creates
Intel's original beside each pipeline it replaces, to switch back.

### Stepping aside

Beside another mod, the network make-up checks (the set of coefficient buffers a reader needs, the initial census,
network work before setup) do not end the game; the context steps aside once instead. Its scoped device, queue and
command-list tables return to plain forwarding, replaced pipelines are bound as Intel's originals, and the network,
census and dispatch checks stop; `FAST_ASIDE` in both logs gives the reason. FreeFG's resources live until the
context is destroyed, as earlier recorded work may use them. The other checks of item 6 still end the game.

## The shader profile

`BC250-XeFG/shaders/` beside the proxy holds 61 files: 13 hash replacements (`<hash>.dxil`, item 1), the F4Q form of 7
of them (`<hash>.f4q.dxil`) and the FP16 form of 7 (`<hash>.fp16.dxil`); 20 kernels, 15 for the 2× network and 5 for
the multi-frame network (item 2); 5 check kernels of F4Q's diagnostic (`f4q-check-*.dxil`, used only with
`BC250_XEFG_F4Q_SHADOW=1`); `dispatch-scale.txt`, divisors for 11 shaders (item 5); `waves.txt`, wave sizes for 142
shaders ([pacing layer](#the-pacing-layer)); and 7 `*.required` markers that switch on parts of the accelerated path.

The 52 shaders are DXIL (50 of shader model 6.6, 2 of 6.9) compiled with Microsoft's DirectX Shader Compiler from this
project's HLSL ([BUILDING.md](BUILDING.md)). They hold no weights: they read the network's coefficients at run time from
the buffers of item 3. Nine of the U-Net replacements compute their input transform in FP16 pairs, which represent its
small integers exactly, so their products and sums are those of the FP32 form.

### Exact arithmetic

All network shaders except the seven F4Q kernels ([below](#f4q-identical-in-every-test-not-proven)) and the seven FP16
forms ([below](#fp16-forms-the-default-slightly-different)) accumulate int8
inputs and integer coefficients in FP32 so that every partial sum is an integer below 2^24, which FP32 represents
exactly in any order. Their results therefore equal the runtime's own integer results, and the generated images are
bit-identical where tested ([MEASUREMENTS.md](MEASUREMENTS.md#generated-images-bit-identical)). On the BC-250 (RDNA 1),
which lacks the int8 dot-product instructions Intel's shaders use in hardware, this is faster.

### F4Q: identical in every test, not proven

F4Q replaces the Winograd F(2×2) kernels of two U-Net layers (the decoder `b3941ac8`, at both of its sizes, and the
encoder `f030948d`) by F(4×4) kernels, which need fewer multiplications. Their coefficients (24 G g Gᵀ, at most
73,728 in size) are exact in FP32, but the F(4×4) transforms and the final scaling round in FP32, so exact results are
not guaranteed by construction as they are for the other shaders. Their outputs matched the F(2×2) kernels' in every
test: byte for byte in a software rasteriser on test inputs; in all 20 SDK test rows (SDR and HDR10, engine and pixel
motion vectors, 1440p and 4K), where the generated images with F4Q on and off were identical to each other and to
Intel's shaders'; and on the GPU in Cyberpunk 2077 (native 2× and OptiScaler 3×, SDR), where this release's proxy, with
the diagnostic `BC250_XEFG_F4Q_SHADOW=1`, ran both kernels on the same input and compared 64-bit fingerprints of the two
layers' outputs 96,480 times, with none differing. The same number of comparisons with a test build of the same
kernels also found none. HDR10, 4× and other games were not compared in a game, and in a game the comparison ran only
with the diagnostic on. That is identical in every test, not proven for every input.

F4Q2 (1.1.2) applies the same arithmetic to the encoders `1a3b0782` (16→16), `e83e868f` (32→64) and `9e0080ee`
(64→128). Their kernel keeps one FP32 channel sum over all 32 or 64 input channels, in order, as the F(4×4) form of F4Q's
encoder does over 16. Their outputs matched the F(2×2) kernels' in every test on realistic data: byte for byte in a
software rasteriser on test inputs; 640 of 640 generated SDK frames identical to the F(2×2) kernels' on 19 configurations,
and 162,992 in-game comparisons in Cyberpunk 2077 (native 2× and OptiScaler 3×, SDR) with none differing, both with a
test build of the same kernels; with this release's proxy, 704 of 704 SDK images identical to Intel's shaders' on 20
configurations (exact switch); and, with an earlier 1.1.2 candidate whose F(4×4) kernels and diagnostic this release keeps
unchanged, 8,790 in-game comparisons per layer, none differing ([MEASUREMENTS.md](MEASUREMENTS.md#checks-of-112)).
None differed in at least 10⁹ outputs per layer from realistic weights and inputs. Inputs constructed to provoke
rounding are the exception: there, unlike F4Q's two layers, all three give some different outputs (2×10⁻⁵ to 9×10⁻⁴ of
them). Not proven for every input.

F4Q3 (1.1.2) applies it to the U-Net's two row layers, `60edebbb` (16→16) and `b3ddf030` (32→16), in place of their
1D F(2,3) kernel: signed, unpooled outputs, from F4Q's coefficient segments. Their outputs matched in every test: none
differed in 8×10⁸ outputs per layer from realistic weights and inputs; 704 of 704 generated SDK images identical to
Intel's shaders' on 20 configurations and 30,172 in-game comparisons per layer in Cyberpunk 2077 (native 2× and
OptiScaler 3×, SDR) with none differing, all with test builds of the same kernels; with this release's proxy, the same
704 SDK images; and, with the earlier candidate, 8,790 in-game comparisons per layer, none differing. Constructed inputs
give some different outputs on `b3ddf030` (4,521 in 2×10⁸, 5 of them changing an int8 output). Not proven for every
input.

Three other changes of 1.1.2 are exact by construction, so they give the same outputs for every input the model owner
accepts: F4Q's decoder fills and transforms in packed 16-bit integer and FP16 arithmetic where every operation is exact;
F4Q's two kernels skip thread groups whose outputs all lie below the image (their stores would all be discarded); and
the fused flow refinement runs 32 × 4 px groups and divides its exact sums by 4 with a shift.

F4Q, F4Q2 and F4Q3 are on by default. To turn all of them off, set `BC250_XEFG_F4Q=0` in
the game's launch options, or `F4Q=0` under `[BC250]` in `BC250-XeFG/settings.ini` in the game folder; to turn off F4Q2,
`BC250_XEFG_F4Q2=0` or `F4Q2=0` (its three layers then run their F(2×2) kernels, also by default, without their FP16
form). The launch option wins; Setup keeps the file's keys on reinstall. The F(2×2) and 1D kernels then run, as in
1.0.x (or as in 1.1.1 for F4Q2's layers). F4Q off also turns the FP16 forms off. `BC250_XEFG_F4Q_SHADOW=1` is a
diagnostic: the F(2×2) and 1D kernels keep the output, the F(4×4) kernels run beside them, and FreeFG's own GPU
passes count equal and differing outputs (`F4Q_COUNT` lines in `BC250-XeFG-fast.log`; nothing of the content leaves the
GPU); the FP16 forms are off while it runs. The fast log names every state at every accelerated start (`F4Q_CONFIG`,
`F4Q2_CONFIG`, `FP16_CONFIG`, `F4Q3_CONFIG`).

### FP16 forms: the default, slightly different

By default (1.1.2) seven U-Net kernels run in faster forms whose outputs differ slightly from the exact forms', and so
the generated frames differ slightly from Intel's:

- F4Q2's three F(4×4) kernels read their coefficients as FP16 pairs of U'/2 instead of FP32. U'/2 is rounded to FP16
  where it needs more than 11 significant bits, which the network's weights do in games.
- The F(2×2) kernels of `1f27b449`, `f2e2e13f`, `5654aa38` and `4bb52a63` multiply and add in packed FP16 (two channels
  per instruction), one rounded chain per 16 input channels; the chains are added exactly and the final division rounds
  to nearest. On test data 2–4% of their int8 outputs differ by one step.

F4Q's two kernels and F4Q3's run their exact F(4×4) form by default. The model owner adds FP16 copies of the
coefficients after the F4Q segment (`FP16_SEGMENT` in the fast log). Measured with a test build of the same kernels on
19 synthetic SDK scenes (SDR and HDR10, engine and pixel motion vectors, 1440p and 4K), the default's generated images
differ from Intel's in 0.12–16.2% of pixels (this release's images:
[MEASUREMENTS.md](MEASUREMENTS.md#checks-of-112)). Their error against the scenes' analytic truth is 0.985–1.007×
Intel's. No quality gate has passed these images. The project's gate (QM-X, unpublished research tooling) judges a
build's difference from Intel's output against the difference between Intel's shaders on an RTX 5080 and on the BC-250.
Its frozen version 1.2 passes these images on 7 of the 19 scenes, sends 10 to review and fails 2. Its frozen version
1.4, which can also clear a review where the local error against the scenes' analytic truth stays within the RTX 5080's,
passes 18 and fails 1 (a frame-to-frame check on one panning scene); on three held-out scenes it passes all three. The maintainer compared these images with those of an earlier 1.1.2
candidate, which ran four more kernels in FP16 forms, at the gate's failing spots, and judged them better overall.

`BC250_XEFG_EXACT=1` in the launch options, or `Exact=1` under `[BC250]` in `BC250-XeFG/settings.ini`, turns the FP16
forms off (`BC250_XEFG_EXACT=0` wins over the file). Every kernel then runs its exact form: F4Q, F4Q2 and F4Q3 run their
F(4×4) kernels and the other U-Net layers their F(2×2) kernels, and the generated images were identical to Intel's in
every test. The FP16 forms also need F4Q on: F4Q's switch or its diagnostic turns them off. Status and Check name the
last session's form (`Output:`, from `FP16_CONFIG`). Beside MFG Unlocker's own model, which replaces some of these
shaders, only some of the forms run; the line does not say which.

## The pacing layer

`libxefg_wave.so`, a Linux Vulkan layer in the game's process below vkd3d-proton, is enabled by the launch environment
(`VK_LAYER_PATH`, `VK_INSTANCE_LAYERS`), which also sets vkd3d-proton's `no_staggered_submit` option (`VKD3D_CONFIG`)
and its cache settings ([wave sizes](#wave-sizes-bc-250-only)).

### Present pacing (gamescope only)

XeFG passes on generated and real frames back to back, but they become ready unevenly, which a VRR display shows. The
layer:

- waits until each frame is rendered and releases it no sooner than 99% of the average frame interval after the
  previous one;
- after a late frame, grows its jitter allowance by 1 ms plus half the lateness, shrinking by 0.3 ms per second.
  The SDK output count sets its ceiling: 5 ms at 2×, 10 ms at 3× and 15 ms at 4×. A stream that never misses gains no
  extra allowance. Holds stay bounded at 3.5 output intervals, or 4.5 at 4×;
- requests three extra swapchain images where the surface permits them, so held MFG frames do not stall new GPU work;
- presents from a compute queue it reserves where the driver has one, else from the game's queue under a lock;
- after each paced present, changes a property on the game's X display's root window seven times within 2.6 ms: stock
  gamescope shows a frame that arrived complete only at its next refresh-timer tick, and each change wakes it to show
  the frame at once.

It holds frames only while XeFG generates, at any frame count, as the proxy's signal page in `/dev/shm` shows (item 7);
a game's own FSR 3 frame generation, frame generation off and menus pass through. With no signal page, or no proxy
answer within 3 seconds, it holds every present. The proxy also reports the SDK's actual frames per present through
that page; older producers leave the field zero and keep the previous 5 ms policy.

### Game-frame starts (OptiScaler XeLL output)

Even display intervals cannot correct alternating simulation intervals. At 3×/4× the bundled OptiScaler detects
sustained short/long game-frame starts and tops up starts that XeLL leaves clearly early. It resets on loading gaps,
multiplier changes, or eight consecutive holds, and does not act at 2×. This runs directly after OptiScaler's XeLL
sleep call, without new SDK hooks. `BC250_XELL_PACE=0` disables the correction. MFG Unlocker's additional output
pacing does not supply this game-frame correction.

### Wave sizes (BC-250 only)

The layer has the driver compile the compute shaders listed by hash in `waves.txt` (`XEFG_WAVE_CONFIG`), FreeFG's and
some unchanged ones of the runtime, with a required subgroup size of 32 or 64. The shader code is not changed.

A line takes effect only when the pipeline is compiled with it. On RADV, vkd3d-proton's cache normally stores a
pipeline's shader as an identifier, not as code; on a later start it recreates the pipeline from that identifier, so
the layer cannot tell which shader it is, and the driver returns the pipeline it compiled before (at its own wave size)
when its cache holds one. In 1.1.0, its five new lines for Intel's shaders (four 2× warp shaders and a convolution)
therefore took no effect in a game that ran with 1.0.x.

Since 1.1.1, Setup turns vkd3d-proton's use of identifiers off (`VK_EXT_shader_module_identifier` in
`VKD3D_DISABLE_EXTENSIONS`) and gives it a cache folder of the installation's own (`VKD3D_SHADER_CACHE_PATH`, in the
backup folder). vkd3d-proton then caches the shader code, the layer names every pipeline on every start, and the driver
compiles a listed shader with its wave size once. The new folder matters too: identifier entries already in the game's
old cache would otherwise be translated again on every start. A cache path you set yourself is kept. Where the game
folder's path is too long for vkd3d-proton's cache file names (over 178 characters minus the length of the `.exe`
name), Setup sets neither, and the lines behave as in 1.1.0. [MEASUREMENTS.md](MEASUREMENTS.md#shader-caches) gives
the measurements.

## OptiScaler and the upscaler

OptiScaler connects a game's upscaler and frame-generation inputs (DLSS, FSR, XeSS, or its own OptiFG) to an upscaler
and to XeFG. The installer sets the DirectX 12 upscaler (FSR 4 or HelixSR), XeFG output, Intel's XeLL for latency,
borderless window mode (XeFG does not interpolate in exclusive fullscreen) and `InterpolationCount=1` (2×) on every
Install, and `XeFGModel=default`, which only MFG Unlocker reads, where it is unset
([README.md](README.md#3-and-4-with-mfg-unlocker)). The OptiScaler and FSR 4 builds: [NOTICE.md](NOTICE.md).

### HelixSR

HelixSR, by lonewolf0622 ([NOTICE.md](NOTICE.md#helixsr)), provides NVIDIA's DLSS Model E network through the FidelityFX
(FSR 3.1) upscaler interface, as `amd_fidelityfx_upscaler_dx12.dll` (its "FSR drop-in"). OptiScaler loads its FidelityFX
upscaler from that file in its folder (`Libraries.FfxDx12SRPath`, default `OptiScaler/`) and, with
`FSR.UpscalerIndex=0`, uses the first version the DLL reports. The installer puts the DLL HelixSR's own setup built
there in place of FSR 4's, and nothing else of HelixSR's. `helixsr.ini` beside it sets `[DlssFrameGeneration] Enabled =
false`, which keeps HelixSR's DLSS frame generation from loading, and the installer never copies the `helixsr-fg` folder
that frame generation needs.

## The installer

`install.py`, with the Zenity front end `setup.py`, writes the launch environment into the game's Steam, Heroic or
Lutris entry: `WINEDLLOVERRIDES` for OptiScaler's DLL, the layer variables, the wave table and three vkd3d-proton
settings: `no_staggered_submit` in `VKD3D_CONFIG`, `VKD3D_DISABLE_EXTENSIONS` and `VKD3D_SHADER_CACHE_PATH`
([why](#wave-sizes-bc-250-only)). [What else it changes](README.md#what-setup-changes).

- `configure --upscaler` swaps the upscaler DLL as a pending update, which Restore can finish or undo if interrupted.
  Restore, or a switch to FSR 4, keeps an edited `helixsr.ini` in the backup folder; the next HelixSR installation
  starts from it.
- It refuses another proxy mod, a custom OptiScaler DLL path and an unknown OptiScaler build.
- This project's pre-release test builds loaded a third-party multi-frame enabler (`version.dll`, an `XeSSMFG` folder).
  The installer will not install over one, can restore one it made and keeps its settings, and installs neither.

## The compatibility check

`gamescan.py` reads the game's files and launcher records, read-only and offline
([PRIVACY.md](PRIVACY.md#what-the-installer-reads-and-writes-on-your-computer)). `compat.py` combines the scan with
`recipes/recipes.json`, which also carries OptiScaler wiki facts, into the verdict
([COMPATIBILITY.md](COMPATIBILITY.md)) and the install plan Install follows.

### Which source decides

The user's own choices come first (values set in `OptiScaler.ini`, an input picked in Setup or on the command line, the
game's launch options), then:

1. a verified recipe;
2. OptiScaler's own built-in fixes for the game (the installer never writes a key one of them sets);
3. a community recipe;
4. six promoted OptiScaler wiki fixes (reviewed by an agent for the maintainers, awaiting a maintainer's confirmation),
   only where the launcher ID, or the executable and title, identify the game (today only FINAL FANTASY VII REBIRTH and
   Soulstice);
5. the wiki's reports of a broken input;
6. detection;
7. the installer's defaults.

## What is changed at run time

While the runtime runs, FreeFG changes how part of its GPU work is carried out, as listed below; it does not modify
or ship Intel's file. Intel has not given this project permission for this. Intel's licence and your
position as its licensee: [NOTICE.md](NOTICE.md#intels-terms).

| The runtime's | Changed by FreeFG | Left alone |
| --- | --- | --- |
| DLL file | — | Byte for byte as downloaded; SHA-256 checked at install, size and hash at load |
| Code in memory | — | No hooks or patches; every call enters through Intel's export table |
| GPU pipelines | 13 built from FreeFG's shaders (by default 7 U-Net ones from their FP16 form and 4 from their F4Q form; with the exact switch 7 from their F4Q form) | All others, from Intel's bytecode |
| Command lists | Some convolution dispatches done by FreeFG's 20 kernels; group counts of 9 replaced shaders divided | All other dispatches |
| Coefficient buffers | Own allocations; pre-transformed copies appended | Intel's bytes at Intel's offsets |
| One root signature | Two buffer bindings appended | The original parameters |
| Shader compilation (Vulkan, BC-250 only) | Required wave size for 142 compute shaders | The shader code |
| Presentation | Frames held until their turn | Which frames are generated, and their order |
| Number of generated frames | — | Intel's: one per real frame on GPUs other than Intel's; more only where another tool the user installed lifts that limit |
| API behaviour towards the game | — | Unchanged |
| Hooks another mod put on it | — | Untouched; FreeFG only compares Intel's entry bytes with the file and passes the original caller through |

`BC250_XEFG_DISABLE=1` turns off items 1–6 and 8 [above](#inside-an-accelerated-context); item 7's signal then counts
only the frames the runtime reports presented. The pacing layer and, on the BC-250, its wave-size table stay active.
