# Google Sheets Integration

The `src/ok_ww_automator/sheets.py` module manages the bidirectional sync of configuration and execution results with a Google Spreadsheet.

## Config Worksheet Layout

The configuration worksheet uses a pairwise label-value layout to allow arbitrary placement of settings. Blank labels are ignored.

*Example Layout:*
- Column A: Label, Column B: Value
- Column C: Label, Column D: Value

Labels must be strictly unique. This allows the system to not only parse the configuration but also locate the exact cell coordinates required to automatically clear `skip-once` flags after they are consumed.

### Expected Labels

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
| `run_nightmare` | 梦魇祓除 | Boolean |

## Result Logs

Run results are appended to their respective worksheets (`DailyRuns`, `StaminaRuns`, `5to1`). 

The formats are strictly serialized by the data models (e.g., `RunResult.as_daily_row()`) to decouple the internal game state from the presentation in Google Sheets. Notably, **live game stamina is not written back to the Config worksheet**; it is only logged in the result rows.

## Live Verification

You can test the parser and identify which cells the automator plans to target for updates:

```powershell
uv run --active python -m ok_ww_automator.sheets --env-file cn.env --show-cells
```