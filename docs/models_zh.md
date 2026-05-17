# 数据模型

`src/ok_ww_automator/models.py` 模块定义了纯 Python 的数据结构。在设计上，该模块对 Google Sheets、网络库或特定于游戏的启动器保持**零依赖**。

## 核心模型

1. **`SheetRunConfig`**: 这是一个数据类，用于存储从 Google Sheets 的 `Config` 工作表检索并解析后的配置。
2. **`RunResult`**: 追踪日常和体力任务的执行结果。它能计算出如 `duration`（耗时）、`stamina_used`（体力消耗）等衍生指标，并预测下次日常重置时的可用体力。
3. **`FastFarmResult`**: 追踪声骸快速刷取循环（例如，五合一融合）的执行结果。

## 显式序列化

模型通过显式方法处理自身的 Google Sheets 序列化，而不是隐藏这种依赖关系：
- `RunResult.as_daily_row()` -> 为 `DailyRuns` 格式化行数据
- `RunResult.as_stamina_row()` -> 为 `StaminaRuns` 格式化行数据
- `FastFarmResult.as_row()` -> 为 `5to1` 格式化行数据

## 时间工具

时间和体力计算位于 `src/ok_ww_automator/time_utils.py`。该模块基于以下假设：
- **当前体力上限**: 240
- **结晶单质上限**: 480
- **恢复速度**: 当前体力每 6 分钟恢复 1 点，结晶单质每 12 分钟恢复 1 点
- **时区**: 所有内部目标评估均使用北京时间 (UTC+08:00)，以便与服务器重置时间保持一致。