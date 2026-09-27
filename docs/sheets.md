# Google Sheets

[简体中文](sheets_zh.md) · [Configuration](config.md) · [Operations](operations.md)

Create a spreadsheet, share it with the service account as an editor, and set `GOOGLE_SHEET_ID` plus the Base64-encoded service-account JSON. The default worksheets are `Config`, `DailyRuns` and `StaminaRuns`; env variables can rename them. The app does not create worksheets or headers. Weekly and manual custom tasks do not require these sheets.

## Config layout

Use adjacent label/value columns: A/B, C/D, and so on. Each row can hold multiple pairs. Blank labels are ignored; all nonempty labels must be unique. Booleans can use checkboxes or `TRUE`/`FALSE`. Missing/blank fields use defaults: daily and stamina enabled, skip and shutdown disabled, Tacet #1, simulation Shell Credit, full Nightmare farming disabled but both Nightmare target types selected.

| Internal Field | Sheet Label | Expected Value Type |
| --- | --- | --- |
| `run_daily` | 日常任务 | Boolean (`TRUE`/`FALSE`) |
| `skip_daily_once` | 日常跳过一次 | Boolean |
| `shutdown_after_daily` | 日常后关机 | Boolean |
| `run_stamina` | 体力任务 | Boolean |
| `skip_stamina_once` | 体力跳过一次 | Boolean |
| `shutdown_after_stamina` | 体力后关机 | Boolean |
| `which_to_farm` | 刷什么 | String (`无音区`, `凝素领域`, `模拟领域`) |
| `tacet_name` | 无音区设置 | String |
| `tacet_serial` | 无音区序号 | Integer |
| `tacet_set1` | 无音区套装1 | String |
| `tacet_set2` | 无音区套装2 | String |
| `forgery_name` | 凝素领域设置 | String |
| `forgery_serial` | 凝素领域序号 | Integer |
| `forgery_weapon_type`| 凝素领域武器类型 | String |
| `forgery_version` | 凝素领域版本 | String |
| `simulation_material`| 模拟领域设置 | String |
| `run_nightmare` | 刷声骸 | Boolean |
| `farm_tacet_discord_nest` | 残象聚落 | Boolean (defaults to `TRUE`) |
| `farm_nightmare_purification` | 梦魇祓除 | Boolean (defaults to `TRUE`) |

Serial numbers start at 1 and follow the game's F2 list. Tacet names/sets and forgery name/weapon/version are descriptive fields; tasks select the numeric serial. Simulation material values are `共鸣者经验` (Resonator EXP), `武器经验` (Weapon EXP), or `贝币` (Shell Credit).

`刷声骸` enables full Nightmare farming; selecting neither target disables it. With full farming off, upstream DailyTask may still farm one echo to meet daily goals. Disable both targets to disable that path as well.

After a skip-once flag is consumed, the app writes `FALSE` to the cell beside its label. Live stamina only appears in result logs; it is not written back to Config.

## Result columns

You can add these headers to row 1; the app appends results in this order:

| Worksheet | Column order |
| --- | --- |
| `DailyRuns` | Start, end, duration, status, starting stamina, starting backup, consumed, remaining stamina, remaining backup, daily points, next-daily stamina, next-daily backup, sign-in result, full Nightmare farming, decision, error |
| `StaminaRuns` | Start, end, duration, status, starting stamina, starting backup, consumed, remaining stamina, remaining backup, next-daily stamina, next-daily backup, decision, error |

`5to1` and `SHEET_NAME_FASTFARM` remain for the legacy result-writing API. Launcher farming and five-to-one tasks currently do not append there, so normal setup does not need that worksheet.

## Read-only check

From the Automator directory, read the live sheet and print parsed settings and cell addresses without modifying it:

```powershell
../.venv/Scripts/python.exe -m ok_ww_automator.sheets --env-file cn.env --show-cells
```
