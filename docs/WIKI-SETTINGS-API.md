# Wiki settings API (format 1)

This is the shared planner/installer contract for the FreeFG 1.2.0 candidate and
Proton integrations. It does not require or import a GUI. Runtime/shader/provider
versions are unchanged by an INI-only application.

## Installed-game preview and application

`install.wiki_settings_plan(package, exe)` is read-only and returns a JSON-safe
object with `format`, `digest`, `context`, `rows`, `automatic`, `vetoes`,
`weak_vetoes`, `quirks_current`, and `requirements` (title, text and page links).

Each row contains `id`, `key`, `value`, `current`, `when`, `condition`
(`true`, `false`, or `null`), `strength`, `action`, `reason`, `confirmations`,
and `source` (title, page links, wiki revision, tested context and reviewed status).
`confirmations` are worded ("if crashing on startup", "with the game's FSR 3.1
input"); to show `when` itself, word each condition with
`compat.condition_text(key, value)`, as Check does.

- `automatic`: a reviewed, strongly matched fix whose conditions hold. The
  ordinary installation planner uses these defaults where the user left auto.
- `prefill`: a ready INI value the player may explicitly select. Start unselected.
- `conditional`: requires explicit confirmation of the displayed identity and/or
  conditions. It is not an automatic default.
- `handled`, `inapplicable`, `unsupported`, `conflict`, `advice`: display the
  reason; these rows cannot be applied through this interface.

Apply only the selected row IDs, with the digest of the displayed preview:

```python
install.apply_wiki_settings(
    exe, selected_ids, confirmed_ids,
    package=package, expected=preview['digest'],
)
```

`confirmed_ids` must be a subset of `selected_ids`; include a row only when the
player confirmed its displayed game/unknown conditions. Confirmation cannot
bypass a known false condition, unsupported key, runtime-owned fix or incompatible
output policy. A changed preview is refused. An explicit selection can replace
an existing value; show `current → value` before applying.

Writes use the normal installation lock and recoverable generation transaction.
They change only OptiScaler.ini and its ownership/provenance record. Rollback and
Restore preserve their existing merge rules, including later player edits. No
release/provider upgrade or game configuration edit is implied. The installation
must already be managed; this first API does not add a second mutation to Install.

For a subprocess-based GUI:

```text
python install.py wiki-plan GAME.exe
python install.py wiki-apply GAME.exe --wiki-setting ROW_ID \
  --wiki-plan-digest DIGEST [--wiki-confirm ROW_ID]
```

Repeat `--wiki-setting` and `--wiki-confirm` as needed. `wiki-plan` emits JSON;
`wiki-apply` uses the normal operation output and exit status. It accepts one game
per reviewed plan. The native GUI should run preview off its UI thread, discard
stale preview results, and check that the game is closed before application.

## Pure catalogue interface

`compat.wiki_plan(data, ids, context, supported_keys=..., current=...,
recipe_ini=..., quirk_exe=..., optiscaler_commit=...)` performs no filesystem or
network access. Identity uses FreeFG's `wiki_matches` convention: store ID or
executable plus title/folder is strong; title alone is weak. Titles compare as
`recipes.norm()` gives them, edition included ("grand theft auto v enhanced").
`match.alias` (a title without its store edition, `recipes.loose()`) and
`match.generic_exe` (an exe name many games share) are kept apart from `title`
and `exe` and never matched: sometimes they name another game, so integrations
should not act on them either. Integrations should provide the actual
input/output, provider, store and proxy context, plus the keys supported by the
selected OptiScaler build. `current` and `recipe_ini` use `Section.Key` strings.

`compat.select_wiki_settings(plan, selected_ids, confirmed_ids)` validates the
selection and returns `settings` (`Section.Key → value`), `selected` provenance
rows and `plan_digest`. Proton stores these as explicit per-game settings and
uses its own prefix transaction; it must not run the game-local installer.

The October 30 catalogue review covers wiki commit `5f927893`, with 761 titles
and 295 INI instructions. The catalogue keeps the 739 game titles (286 INI
instructions); the 22 topic pages ("… (general)") match no game. Six existing
automatic values now have verified Steam identities; other usable values remain
explicit prefills. The review record is
[`utilization-review-20261030.json`](../research/recipes/utilization-review-20261030.json).
No new automatic promotion or gameplay qualification is implied.

The installed planner identifies supported keys from the actual OptiScaler DLL's
hash and a pinned INI key manifest, falling back to keys in the current INI for
an unrecognized build. Integrations may provide `files` (relative dependency
paths) and `upscaler_input` when known. A known missing file cannot be confirmed
away; unknown symptoms or input choices still need explicit confirmation.

## Catalogue files

`research/recipes/build_recipes.py` generates both catalogue files offline from
the inputs committed beside it: `wiki.json` (the wiki's facts per title),
`wiki-curation.json` (maintainers' launcher IDs, titles and requirements),
`wiki_promote.json`, `optiscaler.json` (builds, INI key lists, quirk tables),
`verified/*.json` and `community/*.json`. Never edit the generated files;
`build_recipes.py --check` fails when they differ from what the inputs build.

`packaging/recipes/recipes.json` is the full file. The compact
`recipes-runtime.json` (a package's `recipes/recipes.json`) keeps wiki page
links relative to `wiki_url` and each OptiScaler.ini's keys once, in
`optiscaler_ini_keys` by INI digest. `recipes.load()` restores absolute links
and `optiscaler_builds[commit]['keys']`; a reader that parses the compact file
itself must do the same.

A wiki entry's `launch_args` holds the DX12 switches FreeFG may add itself (an
unconditional instruction). Every other launch instruction is one `launch` item:
`text` (the whole line as the page gives it; show it whole, never per token),
`kind` (`args` game flags, `env` assignments, `steam` a launch-options line with
`%command%`, `wrapper` another program around the game), optional `when`, and
`conflicts`: the variables FreeFG sets or refuses (`WINEDLLOVERRIDES`, `VK_*`,
`VKD3D_*`, `XEFG_*`, `BC250_*`, GE-Proton's `PROTON_USE_OPTISCALER` and
`PROTON_*_UPGRADE`) or the switches leaving DirectX 12 it contains. An item with
conflicts is not usable beside FreeFG as it stands. Instructions the extraction
marked low-confidence are left out, as INI items are.
