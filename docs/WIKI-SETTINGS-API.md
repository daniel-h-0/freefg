# Wiki settings API

This is format 1 of the interface between FreeFG's wiki settings
planner, its installer and Proton integrations. It has been part of
FreeFG since 1.2.0. It does not require or import a GUI. Applying wiki
settings changes INI values only. Runtime, shader and provider versions
stay unchanged.

## Preview

`install.wiki_settings_plan(package, exe)` is read-only. It returns a
JSON-safe object with `format`, `digest`, `context`, `rows`,
`automatic`, `vetoes`, `weak_vetoes`, `quirks_current`, and
`requirements` (title, text and page links).

Each row contains `id`, `key`, `value`, `current`, `when`, `condition`
(`true`, `false`, or `null`), `strength`, `action`, `reason`,
`confirmations`, and `source` (title, page links, wiki revision, tested
context and reviewed status). `confirmations` are worded ("if crashing
on startup", "with the game's FSR 3.1 input"). To show `when` itself,
word each condition with `compat.condition_text(key, value)`, as Check
does.

| `action` | Meaning |
| --- | --- |
| `automatic` | A reviewed, strongly matched fix whose conditions hold. The ordinary installation planner uses these defaults where the user left auto. |
| `prefill` | A ready INI value that the player may explicitly select. Start unselected. |
| `conditional` | Requires explicit confirmation of the displayed identity, conditions or both. It is not an automatic default. |
| `handled`, `inapplicable`, `unsupported`, `conflict`, `advice` | Display the reason. These rows cannot be applied through this interface. |

## Apply

Apply only the selected row IDs, with the digest of the displayed
preview:

```python
install.apply_wiki_settings(
    exe, selected_ids, confirmed_ids,
    package=package, expected=preview['digest'],
)
```

- `confirmed_ids` must be a subset of `selected_ids`. Include a row only
  when the player confirmed its displayed game or unknown conditions.
- Confirmation cannot bypass a known false condition, unsupported key,
  runtime-owned fix or incompatible output policy.
- A changed preview is refused.
- An explicit selection can replace an existing value. Show
  `current → value` before applying.

Writes use the normal installation lock and recoverable generation
transaction. They change only OptiScaler.ini and its ownership and
provenance record. Rollback and Restore keep their existing merge rules,
including later player edits. No release or provider upgrade and no game
configuration edit is implied. The installation must already be managed.
This API adds no second write to Install.

## Command line

For a subprocess-based GUI:

```text
python install.py wiki-plan GAME.exe
python install.py wiki-apply GAME.exe --wiki-setting ROW_ID \
  --wiki-plan-digest DIGEST [--wiki-confirm ROW_ID]
```

Repeat `--wiki-setting` and `--wiki-confirm` as needed. `wiki-plan`
emits JSON. `wiki-apply` uses the normal operation output and exit
status and accepts one game per reviewed plan. A native GUI should run
the preview off its UI thread, discard stale preview results, and check
that the game is closed before applying.

## Catalogue interface

```python
compat.wiki_plan(data, ids, ctx, supported_keys=..., current=...,
                 recipe_ini=..., quirk_exe=..., optiscaler_commit=...)
```

`wiki_plan` performs no filesystem or network access.

Identity uses FreeFG's `wiki_matches` convention:

| Match | Strength |
| --- | --- |
| A store ID | strong |
| The executable together with a title or folder | strong |
| The title alone, or a non-generic executable name alone | weak |

Titles compare as `recipes.norm()` gives them, edition included ("grand
theft auto v enhanced"). Beside a matching executable, a title or folder
also matches without its store edition (`recipes.loose()`): GOG's "The
Witcher 3: Wild Hunt — Remastered" with `witcher3.exe` is the wiki's
"The Witcher 3: Wild Hunt".

`match.alias` (a title without its store edition) and
`match.generic_exe` (an executable name that many games share) are kept
apart from `title` and `exe`. They are never matched on their own,
because they sometimes name another game. Integrations should not act on
them either.

Integrations should provide the actual input and output, provider, store
and proxy context in `ctx`, plus the keys that the selected OptiScaler
build supports. `current` and `recipe_ini` use `Section.Key` strings.

`compat.select_wiki_settings(plan, selected_ids, confirmed_ids)`
validates the selection. It returns `settings` (`Section.Key → value`),
`selected` provenance rows and `plan_digest`. Proton stores these as
explicit per-game settings and uses its own prefix transaction. It must
not run the game-local installer.

The installed planner identifies supported keys from the actual
OptiScaler DLL's hash and a pinned INI key manifest. For an unrecognized
build it falls back to the keys in the current INI. Integrations may
provide `files` (relative dependency paths) and `upscaler_input` when
known. A known missing file cannot be confirmed away. Unknown symptoms
or input choices still need explicit confirmation.

## Catalogue files

`research/recipes/build_recipes.py` generates both catalogue files
offline from the inputs committed beside it:

| Input | Contents |
| --- | --- |
| `wiki.json` | The wiki's facts per title |
| `wiki-curation.json` | Maintainers' launcher IDs, titles and requirements |
| `optiscaler.json` | Builds, INI key lists, quirk tables |
| `wiki_promote.json`, `verified/*.json`, `community/*.json` | Promoted wiki items and the verified and community recipes |

Never edit the generated files. `build_recipes.py --check` fails when
they differ from what the inputs build.

| File | Form |
| --- | --- |
| `packaging/recipes/recipes.json` | The full file. |
| `recipes-runtime.json` (a package's `recipes/recipes.json`) | Compact. Wiki page links are relative to `wiki_url`. Each OptiScaler.ini's keys are kept once, in `optiscaler_ini_keys` by INI digest. |

`recipes.load()` restores absolute links and
`optiscaler_builds[commit]['keys']`. A reader that parses the compact
file itself must do the same.

### Catalogue review

The October 30 catalogue review covers wiki commit `5f927893`, with 761
titles and 295 INI instructions. The catalogue keeps the 739 game titles
(286 INI instructions). The 22 topic pages ("… (general)") match no
game. Six existing automatic values now have verified Steam identities.
Other usable values remain explicit prefills. The review record is
[`utilization-review-20261030.json`](../research/recipes/utilization-review-20261030.json).
No new automatic promotion or gameplay qualification is implied.

### Launch instructions

A wiki entry's `launch_args` holds the DX12 switches that FreeFG may add
itself (an unconditional instruction). Every other launch instruction is
one `launch` item:

| Field | Contents |
| --- | --- |
| `text` | The whole line as the page gives it. Show it whole, never per token. |
| `kind` | `args` (game flags), `env` (assignments), `steam` (a launch-options line with `%command%`) or `wrapper` (another program around the game). |
| `when` | Optional condition. |
| `conflicts` | The variables FreeFG sets or refuses that the item contains (`WINEDLLOVERRIDES`, `VK_*`, `VKD3D_*`, `XEFG_*`, `BC250_*`, GE-Proton's `PROTON_USE_OPTISCALER` and `PROTON_*_UPGRADE`), or its switches that leave DirectX 12. |

An item with conflicts is not usable beside FreeFG as it stands.
Instructions that the extraction marked low-confidence are left out, as
INI items are.
