# Google Sheets 集成

`src/ok_ww_automator/sheets.py` 模块负责管理配置和执行结果与 Google Spreadsheet 的双向同步。

## Config 工作表布局

配置工作表使用成对的标签-值布局，以允许任意放置设置项。空白标签会被忽略。

*布局示例:*
- A 列: 标签, B 列: 值
- C 列: 标签, D 列: 值

标签必须绝对唯一。这不仅允许系统解析配置，还能定位确切的单元格坐标，以便在消耗 `skip-once`（跳过一次）标志后自动清除它们。

### 预期标签

| 内部字段 | 表格标签 | 预期值类型 |
| --- | --- | --- |
| `run_daily` | 日常任务 | 布尔值 (`TRUE`/`FALSE`) |
| `skip_daily_once` | 日常跳过一次 | 布尔值 |
| `shutdown_after_daily` | 日常后关机 | 布尔值 |
| `run_stamina` | 体力任务 | 布尔值 |
| `skip_stamina_once` | 体力跳过一次 | 布尔值 |
| `shutdown_after_stamina` | 体力后关机 | 布尔值 |
| `which_to_farm` | 刷什么 | 字符串 (`无音区`, `凝素领域`, `模拟领域`) |
| `tacet_name` | 无音区设置 | 字符串 |
| `tacet_serial` | 无音区序号 | 整数 |
| `tacet_set1` | 无音区套装1 | 字符串 |
| `tacet_set2` | 无音区套装2 | 字符串 |
| `forgery_name` | 凝素领域设置 | 字符串 |
| `forgery_serial` | 凝素领域序号 | 整数 |
| `forgery_weapon_type`| 凝素领域武器类型 | 字符串 |
| `forgery_version` | 凝素领域版本 | 字符串 |
| `simulation_material`| 模拟领域设置 | 字符串 |
| `run_nightmare` | 梦魇祓除 | 布尔值 |

## 结果日志

运行结果会追加到各自对应的工作表中 (`DailyRuns`, `StaminaRuns`, `5to1`)。

日志格式严格由数据模型（例如 `RunResult.as_daily_row()`）进行序列化，以解耦内部游戏状态与 Google Sheets 中的呈现。值得注意的是，**实时游戏体力不会写回 Config 工作表**；它仅记录在结果日志行中。

## 实时验证

您可以测试解析器，并识别 automator 计划定位并更新哪些单元格：

```powershell
uv run --active python -m ok_ww_automator.sheets --env-file cn.env --show-cells
```