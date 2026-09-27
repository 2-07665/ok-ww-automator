# Google Sheets

[English](sheets.md) · [配置](config_zh.md) · [运行说明](operations_zh.md)

创建表格，将其以编辑权限共享给服务账号，并填写 `GOOGLE_SHEET_ID` 和 Base64 编码的服务账号 JSON。默认需要 `Config`、`DailyRuns`、`StaminaRuns` 三张工作表，名称可在 env 中修改。程序不自动创建工作表或表头。周常及手动自定义任务不依赖这些表。

## Config 布局

A/B、C/D 等相邻列分别为“标签/值”，每一行可放多组配置。空标签忽略，所有非空标签必须唯一。布尔值可使用复选框或 `TRUE`/`FALSE`；缺失或留空字段采用默认值。默认启用日常和体力、关闭跳过和关机、选择无音区 #1、模拟领域贝币、关闭完整梦魇刷取但保留两种梦魇目标。

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
| `run_nightmare` | 刷声骸 | 布尔值 |
| `farm_tacet_discord_nest` | 残象聚落 | 布尔值（默认为 `TRUE`） |
| `farm_nightmare_purification` | 梦魇祓除 | 布尔值（默认为 `TRUE`） |

序号从 1 开始，对应游戏 F2 列表。无音区名称/套装、凝素名称/武器类型/版本是描述字段，实际任务按序号选择。模拟领域材料使用 `共鸣者经验`、`武器经验` 或 `贝币`。

`刷声骸` 控制完整梦魇刷取；两个目标都关闭时不会刷取。即使完整刷取关闭，上游 DailyTask 仍可能为完成每日声骸目标刷一次，关闭两个目标可一并禁用。

消费“跳过一次”后，程序定位原标签旁的值单元格并写回 `FALSE`。实时体力只写入结果日志，不回写 Config。

## 结果列

可在首行自行添加以下表头，程序会按顺序追加结果：

| 工作表 | 列顺序 |
| --- | --- |
| `DailyRuns` | 开始时间、结束时间、时长、状态、初始体力、初始备用、消耗、剩余体力、剩余备用、每日活跃度、下次日常体力、下次日常备用、签到结果、完整梦魇刷取、决策、错误 |
| `StaminaRuns` | 开始时间、结束时间、时长、状态、初始体力、初始备用、消耗、剩余体力、剩余备用、下次日常体力、下次日常备用、决策、错误 |

`5to1` 和 `SHEET_NAME_FASTFARM` 仅保留旧版结果写入接口；目前启动器速刷、五合一不会自动追加此表，因此常规安装无需创建。

## 只读检查

在 Automator 目录执行，读取真实表格并打印解析结果和单元格位置，不修改表格：

```powershell
../.venv/Scripts/python.exe -m ok_ww_automator.sheets --env-file cn.env --show-cells
```
