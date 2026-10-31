# Integration contract (format 1)

What a FreeFG installation does to a game, as data, for Proton builds and launchers that set a game up themselves.
Each release folder carries it as `integration.json`; `python3 install.py contract --json` prints the same text
(`--route opti|native`, `--runtime xemfg-proxy|xemfg` and `--owner dxgi.dll|winmm.dll|…` narrow it; without `--json`
it is one line per item). The installer applies the same data, so the two cannot differ. A change of meaning raises
`format`.

## Placeholders

| Placeholder | Meaning |
| --- | --- |
| `{game}` | The folder of the game's executable. |
| `{program}` | The executable's file name. |
| `{cache}` | A vkd3d-proton shader-cache folder of the integration's own for this game (FreeFG: `{game}/.bc250-xefg-experimental/vkd3d-cache`). |
| `{fg_input}` | The frame-generation input: `upscaler` (OptiFG), `dlssg`, `fsrfg` or `fsrfg30`. |

## Launch environment

Each entry of `routes` (one per runtime and route) lists `environment` operations, applied in order to the variables
the launcher already sets for the game:

| Operation | Effect |
| --- | --- |
| `replace` | Sets `value`. With `"when": "unset"` only where the variable is unset or empty: a user's value, `0` included, stays. |
| `prepend` | `value` first in the `sep`-separated list, then the existing members; empty and repeated members are dropped. |
| `append-member` | `value` last unless already a member. With `split`, those characters separate members too and the existing text stays as written; otherwise empty and repeated members are dropped. |
| `dll-override` | Wine overrides: the `sep`-separated `name=setting` entries of `value` after the existing entries, from which those DLL names (any case, with or without `.dll`) are taken out. |
| `remove` | Deletes the variable: the add-on reads it, and a stale value changes what it does. |

`"unless": {"VAR": "value"}` skips an operation where `VAR` holds that value (`BC250_XEFG_NO_STAGGERED_SUBMIT=0` keeps
vkd3d-proton's staggered submission). The two vkd3d-proton cache settings apply only where `vkd3d_cache.rule` holds,
since vkd3d-proton cuts longer cache paths; otherwise leave out `VK_EXT_shader_module_identifier` and
`VKD3D_SHADER_CACHE_PATH`. `owner` is OptiScaler's loader module: `dxgi.dll` in a fresh setup, while an existing
OptiScaler setup keeps its own name.

## Game arguments

Per game, from `recipes/recipes.json`: a verified recipe's graphics-API switch (`launch_args`) only where the game's
arguments choose no API (`arguments.api`), and its `required_args` always (GTA V Enhanced: `-nobattleye`).

## OptiScaler.ini

`routes[].ini` lists the keys the installer writes: `always` (the installation owns the value; Restore reverts a key
while it still holds it), `where-auto` (only where the file has no value or `auto`) and `repair` (only in the case
`when` names). A recipe's `ini` and `upscaler_ini` and reviewed wiki keys add per-game keys where the file says
`auto`.

## Files

Relative to `{game}`:

- `files.payload`: the package's `payload/` folder.
- `files.downloads`: Intel's XeFG runtime as `bc250_xefg_original.dll`, `libxell.dll`, and the FSR 4 DLL in
  OptiScaler's folder (an existing setup's `Libraries.FfxDx12SRPath`).
- `files.optiscaler`: in a game without OptiScaler, its pinned setup (`fresh_setup`) with the package's own build as
  the loader.
- `files.dlss_helper`: NVIDIA's `nvngx_dlss.dll`, only for a DLSS input where OptiScaler finds no copy of the game's.

Downloads are pinned by SHA-256 in `dependencies.json`.

## Settings, logs and checks

`settings` names the settings files, whose values are the user's. `logs.files` are written beside the executable; the
Vulkan layer writes `BC250_PACE` lines to the game's standard error. `optiscaler` names the bundled fork build (source
commit, release tag, SHA-256) and `host` the minimum host requirements where known.

An installation made with `--accept no-launcher` leaves these settings to the launcher. After a session,
`python3 install.py status GAME.exe` reads `Manual launch settings: added by you` once the logs show OptiScaler
loaded, the proxy ready and a frame-generation context selected.
