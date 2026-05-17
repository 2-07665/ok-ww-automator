# 任务执行器 (Runners)

Runners 充当调度环境、Google Sheets 和游戏客户端之间的高级编排层。

虽然 `scheduler.py` 负责账号发现和多进程管理，但 `runners.py` 模块定义了特定日常流程的业务逻辑。

## 架构边界

**重要提示**: Runners 不直接与游戏进行交互。所有游戏执行逻辑（如点击 UI 元素或将特定配置应用于 `ok-script` 任务）都已被提取到 `ok_ww_automator.game_clients` 模块中。Runners 纯粹编排“何时”以及“为何”执行任务。

## 日常执行器 (Daily Runner)

`DailyRunner` 管理主要日常登录流程的执行：
- 从 Google Sheets 存储中获取 `SheetRunConfig`。
- 评估 `run_daily` 和 `skip_daily_once` 标志。
- 尝试通过可选的 Waves API 进行签到并获取初始指标。
- 如果消耗了单次跳过标志，则将其清除。
- 委托 `DailyGameClient` 执行游戏任务。
- 为短暂的游戏崩溃编排重试循环。
- 将最终结果持久化到 `DailyRuns` 工作表。
- 分发执行通知。
- 如果配置了关机，则请求系统关机。

## 体力执行器 (Stamina Runner)

`StaminaRunner` 管理一个单独的额外登录，专门用于消耗多余的体力。
- 获取 `SheetRunConfig`。
- 评估 `run_stamina` 和 `skip_stamina_once` 标志。
- 通过 Waves API 获取当前体力（如果 API 被禁用或失败，则回退到快速登录游戏并使用 OCR 读取）。
- 使用 `time_utils.calculate_burn()` 智能地决定是否需要消耗体力，以防止在下一次计划的日常运行之前体力溢出。
- 如果不需要消耗体力，则完全跳过启动繁重的游戏客户端。
- 如果需要消耗体力，则委托 `StaminaGameClient` 执行领域或无音区任务。
- 将最终结果持久化到 `StaminaRuns` 工作表。
- 分发执行通知。