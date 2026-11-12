# Integration contract

The integration contract states, as data, what a FreeFG installation does to a game. It is for Proton builds and
launchers that set a game up themselves. This document describes format 1. A change of meaning raises `format`.

Each release folder carries the contract as `integration.json`. `python3 install.py contract --json` prints the same
text. Without `--json` it prints one line per item. `--route opti|native`, `--runtime xemfg-proxy|xemfg` and
`--owner dxgi.dll|winmm.dll|…` narrow the output. The installer applies the same data, so the two cannot differ.

## Placeholders

| Placeholder | Meaning |
| --- | --- |
| `{game}` | The folder of the game's executable. |
| `{program}` | The executable's file name. |
| `{cache}` | A vkd3d-proton shader-cache folder of the integration's own for this game (FreeFG: `{game}/.bc250-xefg-experimental/vkd3d-cache`). |
| `{fg_input}` | The frame-generation input: `upscaler` (OptiFG), `dlssg`, `fsrfg` or `fsrfg30`. |

## Launch environment

`routes` has one entry per runtime and route. Each entry lists `environment` operations. Apply them in order to the
variables that the launcher already sets for the game.

| Operation | Effect |
| --- | --- |
| `replace` | Sets `value`. With `"when": "unset"` only where the variable is unset or empty: a user's value, `0` included, stays. |
| `prepend` | `value` first in the `sep`-separated list, then the existing members. Empty and repeated members are dropped. |
| `append-member` | `value` last unless already a member. With `split`, those characters separate members too and the existing text stays as written. Otherwise empty and repeated members are dropped. |
| `dll-override` | Wine overrides: the `sep`-separated `name=setting` entries of `value` after the existing entries, from which those DLL names (any case, with or without `.dll`) are taken out. |
| `remove` | Deletes the variable. The add-on reads it, and a stale value changes what it does. |

`"unless": {"VAR": "value"}` skips an operation where `VAR` holds that value. Example:
`BC250_XEFG_NO_STAGGERED_SUBMIT=0` keeps vkd3d-proton's staggered submission.

The two vkd3d-proton cache settings apply only where `vkd3d_cache.rule` holds, because vkd3d-proton cuts longer cache
paths. Otherwise leave out `VK_EXT_shader_module_identifier` and `VKD3D_SHADER_CACHE_PATH`.

`owner` is OptiScaler's loader module. It is `dxgi.dll` in a fresh setup. An existing OptiScaler setup keeps its own
name.

## Game arguments

Per game, from `recipes/recipes.json`:

- A verified recipe's graphics-API switch (`launch_args`), only where the game's arguments choose no API
  (`arguments.api`).
- Its `required_args`, always. GTA V Enhanced requires `-nobattleye`.

## OptiScaler.ini

`routes[].ini` lists the keys that the installer writes. Each key has a `write` rule:

| `write` | Meaning |
| --- | --- |
| `always` | The installation owns the value. Restore reverts a key while it still holds that value. |
| `where-auto` | Written only where the file has no value or `auto`. |
| `repair` | Written only in the case that `when` names. |

A recipe's `ini` and `upscaler_ini` and reviewed wiki keys add per-game keys where the file says `auto`.

## Files

Paths are relative to `{game}`.

| Field | Contents |
| --- | --- |
| `files.payload` | The package's `payload/` folder. |
| `files.downloads` | Intel's XeFG runtime as `bc250_xefg_original.dll`, `libxell.dll`, and the FSR 4 DLL in OptiScaler's folder (an existing setup's `Libraries.FfxDx12SRPath`). |
| `files.optiscaler` | In a game without OptiScaler, its pinned setup (`fresh_setup`) with the package's own build as the loader. |
| `files.dlss_helper` | NVIDIA's `nvngx_dlss.dll`. Only in a fresh OptiScaler setup on a DLSS input where OptiScaler finds no copy of the game's own. |

Downloads are pinned by SHA-256 in `dependencies.json`.

## Settings, logs and checks

| Field | Contents |
| --- | --- |
| `settings` | The settings files. Their values are the user's. |
| `logs.files` | The logs written beside the executable. |
| `logs.stderr` | The Vulkan layer's `BC250_PACE` lines on the game's standard error. |
| `optiscaler` | The bundled fork build: source commit, release tag, upstream base and SHA-256. |
| `host` | The minimum host requirements, where known. |

An installation made with `--accept no-launcher` edits no launcher entry and leaves the launch settings to the launcher.
After a session, `python3 install.py status GAME.exe` prints `Manual launch settings: added by you` once the logs show
OptiScaler loaded, the proxy ready and a frame-generation context selected.
