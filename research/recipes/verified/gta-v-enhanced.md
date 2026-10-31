# GTA V Enhanced: Social Club swapchain fix

Local qualification, 30 October 2026: Steam 3240220, GTA 1.0.1158.16,
GE-Proton11-11, AMD BC-250, AMD FSR 4 RC12, 2560×1440 SDR, DLSS Quality
input, OptiFG → XeFG at 2×. Tests used Story Mode with BattlEye disabled.

## Reproduction

The unmodified game reached the bank prologue and opened Social Club. With
OptiScaler `25db192b`, Social Club's legacy `CreateSwapChain` requested a
0×0 descriptor for a 119×100 client window. It entered XeFG and faulted at
Intel runtime offset `0x2123AA`, reading address `0x58`. A synthetic main plus
overlay pair reproduced that fault. Turning generation off does not avoid
creation of the XeFG swapchain.

Factory wrapping avoided that crash but left GTA at Initializing in a bounded
trial. Resolving zero axes before the existing under-100 check fixed an 111×66
probe but still crashed in GTA: the real 119×100 window is outside that rule.
These failed candidates are not the qualified fix. The internal cause of the
wrapping stall and Intel's null dereference was not independently established.

## Fix and evidence

OptiScaler `273e8d449763d0e9e051dee831dc42badcd15d00` marks factories created
by SocialClubD3D12Renderer and passes their swapchains through native DXGI.
The marker is DXGI private data, so it follows interface aliases and object
lifetime. It covers normal and DLSSG hook paths; the game's factory still uses
frame generation. Separately, tiny-window checks resolve omitted dimensions
from the HWND without changing the descriptor.

DLL SHA-256: `044cac6be344a6619e02af9cb0930eed4165ec606dc74486a1d28a573242ec87`.

Two successful short Story Mode starts reached gameplay with sustained 2.0
generated presents per game frame. The first run required enabling XeFG because
the diagnostic preset deliberately matched the report's disabled setting. A
fresh start retained Enabled=true, reached gameplay, and kept generation active
while Social Club opened and closed. The final build reached 84 °C with no
recorded GPU faults. Seven final probe cases passed: native control, explicit
and zero legacy descriptors, partially zero legacy/HWND descriptors, a small
HWND, and overlay-before-game with zero main dimensions. Sixteen geometry/source
regression checks passed.

This is short functional qualification. Online, long play, HDR, 3×/4×,
frame pacing and image equivalence were not tested.

## Recipe and integration

Install selects OptiFG, enables XeFG and adds the Story Mode launch argument
`-nobattleye` after the existing per-game anti-cheat acceptance. The recipe
lists it under `required_args`, not as its API switch (`launch_args` is
empty), so it is added whatever API switch the user chose. Restore before
playing GTA Online: without the argument, OptiScaler would load beside
BattlEye. Select DLSS in GTA and leave its own
frame generation off. Keep factory wrapping at auto/false and remove an old
Social Club DLL-disable override. The overlay remains available. The normal
per-game anti-cheat refusal still applies; the recipe does not accept it.

For Proton integrations, carry the runtime fix before adopting this recipe.
An INI-only preset cannot repair the swapchain routing bug. Keep an existing
user FG-off choice; offer an explicit per-game Enable XeFG action when the
integration deliberately seeds FG off. Refresh an existing INI deliberately,
preserving unrelated user values; a downloaded preset is not proof it was applied.
