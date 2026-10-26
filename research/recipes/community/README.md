# Community recipes (`community-bc250`)

One JSON file per game, named after its Steam AppID or a slug (`3669870.json`, `the-witcher-3.json`).
`build_recipes.py` validates every file (`check_community`) and builds it into `packaging/recipes/recipes.json` →
`community`; Setup applies it as tier B ("Reported working on BC-250 by N reports; not reproduced by the maintainers"),
game settings included (Restore reverts them key by key). See the [report checklist](../../../packaging/public/CONTRIBUTING.md#game-recipes). The example below is illustrative;
it is not a tested recipe.

```json
{
  "title": "Game Title",
  "match": {"steam": ["1234560"], "exe": ["game-win64-shipping.exe"]},
  "status": "community-bc250",
  "route": "opti",
  "fg_input": "upscaler",
  "ini": {},
  "game_settings": [],
  "launch_args": ["-dx12"],
  "manual_steps": ["Choose DLSS in Video > Upscaling."],
  "known_problems": [{"input": "dlssg", "text": "DLSS FG input gives a black screen"}],
  "reports": [
    {"issue": 123, "freefg": "1.1.3.1", "package_sha256": "...", "proton": "GE-Proton11-11", "mesa": "...", "kernel": "...",
     "gamescope": "...", "hdr": false, "vrr": true, "resolution": "2560x1440", "upscaler_mode": "Performance",
     "ratio": 2.0, "minutes": 30, "starts": 3, "restore_checked": true, "date": "2026-10-25"}
  ],
  "reviewed_by": "maintainer handle",
  "reviewed": "2026-10-26"
}
```

| Field | Rule |
|---|---|
| `match` | a launcher ID (`steam`, `gog`, `epic`), or `exe` names together with the title; generic exe names alone never match |
| `route`, `fg_input` | `native`, or `opti` with `upscaler`, `dlssg` or `fsrfg` (never FSR 3.0 FG; XeFG is always the generator) |
| `fg_input` `dlssg`/`fsrfg` | needs the game setting that turns the game's frame generation on, or a manual step saying so |
| `ini` | OptiScaler keys the shipped build reads; never an installer key, HUDFix, `Spoofing.Dxgi`, Reflex, quality/colour keys, and never a key OptiScaler's own fix for the exe sets |
| `game_settings` | `file` relative to the prefix's `drive_c/users/steamuser`, `format` (`json`, `json-options`, `xml-option`, `ini-replace`, `ini`), `values`; Restore reverts them key by key. `EngineDilateMotionVectors` tweaks are rejected by the community validator; a maintainer must investigate them separately |
| `launch_args` | DX12 switches only (`-dx12`, `-d3d12`, `-force-d3d12`); use the one the game needs |
| `known_problems` | inputs that failed on a BC-250: they leave the automatic choice like a wiki veto |
| `reports` | at least one, each with observed presents per game frame (`ratio` ≥ 1.95) over ≥ 10 minutes of gameplay, 3 starts without a hang, Restore checked |

Each report needs `issue`, `freefg`, `proton`, `ratio`, `minutes`, `starts`, `restore_checked` and `date`. The other
report fields shown are optional. `reviewed_by` and `reviewed` record the maintainer review.

Do not include copied source text, personal paths or user names.
