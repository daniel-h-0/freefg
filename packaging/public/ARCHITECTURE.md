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
   with the runtime's own root signature and pipeline description. For two of them, the U-Net decoder `b3941ac8` and
   encoder `f030948d`, F4Q (on by default) builds the pipeline from a second, faster shader of the profile
   (`<hash>.f4q.dxil`; [below](#f4q-identical-in-every-test-not-proven)); if that pipeline cannot be created, the
   regular shader is used for it (`F4Q_FALLBACK` in the fast log).
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
   (`dispatch-scale.txt`); a dispatch that binds an F4Q pipeline gets that shader's own group counts.
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

`BC250-XeFG/shaders/` beside the proxy holds 49 files: 13 hash replacements (`<hash>.dxil`, item 1) and the F4Q form
of 2 of them (`<hash>.f4q.dxil`); 20 kernels, 15 for the 2× network and 5 for the multi-frame network (item 2); 5 check
kernels of F4Q's diagnostic (`f4q-check-*.dxil`, used only with `BC250_XEFG_F4Q_SHADOW=1`); `dispatch-scale.txt`, divisors
for 9 shaders (item 5); `waves.txt`, wave sizes for 130 shaders ([pacing layer](#the-pacing-layer)); and 7 `*.required`
markers that switch on parts of the accelerated path.

The 40 shaders are DXIL (38 of shader model 6.6, 2 of 6.9) compiled with Microsoft's DirectX Shader Compiler from this
project's HLSL ([BUILDING.md](BUILDING.md)). They hold no weights: they read the network's coefficients at run time from
the buffers of item 3. Nine of the U-Net replacements compute their input transform in FP16 pairs, which represent its
small integers exactly, so their products and sums are those of the FP32 form.

### Exact arithmetic

All network shaders except F4Q's two kernels ([below](#f4q-identical-in-every-test-not-proven)) accumulate int8
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

F4Q is on by default. To turn it off, set `BC250_XEFG_F4Q=0` in the game's launch options, or `F4Q=0` under `[BC250]` in
`BC250-XeFG/settings.ini` in the game folder (the launch option wins; Setup keeps both on reinstall); the F(2×2) kernels
then run, as in 1.0.x. `BC250_XEFG_F4Q_SHADOW=1` is a diagnostic: the F(2×2) kernels keep the output, the F(4×4)
kernels run beside them, and FreeFG's own GPU passes count equal and differing outputs (`F4Q_COUNT` lines in
`BC250-XeFG-fast.log`; nothing of the content leaves the GPU). The fast log names F4Q's state at every accelerated
start (`F4Q_CONFIG`).

## The pacing layer

`libxefg_wave.so`, a Linux Vulkan layer in the game's process below vkd3d-proton, is enabled by the launch environment
(`VK_LAYER_PATH`, `VK_INSTANCE_LAYERS`), which also sets vkd3d-proton's `no_staggered_submit` option (`VKD3D_CONFIG`)
and its cache settings ([wave sizes](#wave-sizes-bc-250-only)).

### Present pacing (gamescope only)

XeFG passes on generated and real frames back to back, but they become ready unevenly, which a VRR display shows. The
layer:

- waits until each frame is rendered and releases it no sooner than 99% of the average frame interval after the
  previous one;
- after a late frame, keeps a margin of 1 ms plus half the lateness (at most 5 ms), shrinking by 0.3 ms per second;
- presents from a compute queue it reserves where the driver has one, else from the game's queue under a lock;
- after each paced present, changes a property on the game's X display's root window seven times within 2.6 ms: stock
  gamescope shows a frame that arrived complete only at its next refresh-timer tick, and each change wakes it to show
  the frame at once.

It holds frames only while XeFG generates, at any frame count, as the proxy's signal page in `/dev/shm` shows (item 7);
a game's own FSR 3 frame generation, frame generation off and menus pass through. With no signal page, or no proxy
answer within 3 seconds, it holds every present. MFG Unlocker, where loaded, also paces frame starts on AMD GPUs.

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
| GPU pipelines | 13 built from FreeFG's shaders (2 of them from their F4Q form while F4Q is on) | All others, from Intel's bytecode |
| Command lists | Some convolution dispatches done by FreeFG's 20 kernels; group counts of 9 replaced shaders divided | All other dispatches |
| Coefficient buffers | Own allocations; pre-transformed copies appended | Intel's bytes at Intel's offsets |
| One root signature | Two buffer bindings appended | The original parameters |
| Shader compilation (Vulkan, BC-250 only) | Required wave size for 130 compute shaders | The shader code |
| Presentation | Frames held until their turn | Which frames are generated, and their order |
| Number of generated frames | — | Intel's: one per real frame on GPUs other than Intel's; more only where another tool the user installed lifts that limit |
| API behaviour towards the game | — | Unchanged |
| Hooks another mod put on it | — | Untouched; FreeFG only compares Intel's entry bytes with the file and passes the original caller through |

`BC250_XEFG_DISABLE=1` turns off items 1–6 and 8 [above](#inside-an-accelerated-context); item 7's signal then counts
only the frames the runtime reports presented. The pacing layer and, on the BC-250, its wave-size table stay active.
