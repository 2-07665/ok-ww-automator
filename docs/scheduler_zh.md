# 调度器入口点 (Scheduler)

`src/ok_ww_automator/scheduler.py` 模块是专为 Windows 任务计划程序设计的唯一入口点。

它的主要工作是发现已配置的账号，更新上游仓库，并安全地为每个账号生成执行进程。

## 子进程隔离

当一次运行包含多个账号任务时，调度器会在独立的 Python 子进程中生成每个账号。这是一个关键的设计要求，因为 `ok-script` 保留了进程全局状态和命名的 Windows 互斥锁。在同一个 Python 进程中构建第二个 `OK` 运行时将导致在游戏就绪检查期间发生死锁。

## 发现与模式

调度器将 `env/` 文件夹中的每个 `.env` 文件（`.env.example` 除外）视为一个独立的、可运行的账号配置文件。

账号 ID 源自文件名：
- `env/cn.env` -> 账号 ID: `cn`
- `env/global.env` -> 账号 ID: `global`
- `env/.env` -> 账号 ID: `default`

调度器需要明确的模式，并且不会自动组合任务。请将日常登录和额外的体力登录作为单独的触发器进行计划：
- `--mode daily`
- `--mode stamina`
- `--mode weekly`
- `--mode stamina-weekly`

## 使用示例

为所有发现的账号运行日常任务：
```powershell
uv run --active python -m ok_ww_automator.scheduler --mode daily
```

空跑测试以验证计划而不启动游戏：
```powershell
uv run --active python -m ok_ww_automator.scheduler --mode daily --dry-run
```

运行特定账号：
```powershell
uv run --active python -m ok_ww_automator.scheduler --mode daily --account cn
```

## Windows 任务计划程序预设

`windows/` 文件夹中提供了 XML 预设以简化设置：

- `windows/daily_task.xml`
- `windows/stamina_task.xml`
- `windows/weekly_task.xml`：默认禁用，导入后设置运行星期和时间，再启用。

### 如何使用：

1. 打开 **任务计划程序 (Task Scheduler)**。
2. 点击操作窗格中的 **导入任务... (Import Task...)**。
3. 选择其中一个 XML 文件。
4. **重要提示:** 编辑导入的任务。在 **操作 (Actions)** 选项卡下，更新 **程序或脚本 (Command)** (共享环境 Python 可执行文件) 和 **起始于 (Working Directory)** 路径以匹配您的本地设置。预设默认使用 `D:\game\ok-ww`。使用当前登录用户并勾选最高权限，仅在用户已登录时运行；检查触发器已启用。

## 周常乐园

运行星期和时刻完全由 **Windows 任务计划程序** 的触发器决定，不在 env 配置。导入 `windows/weekly_task.xml` 后编辑触发器（模板仅以系统本地时间每天 05:00 为例），并启用任务；可设为每周一、三、五运行。执行命令是 `python -m ok_ww_automator.scheduler --mode weekly`，可用 `--account cn` 限定账号，`--skip-update` 跳过更新。

env 只指定本周仍未完成时的通知日：

```dotenv
WEEKLY_NOTICE_DAY=5
```

`1` 至 `7` 对应周一至周日，默认 `7`。此配置不创建或修改 Windows 触发器，也不会限制运行日期。

- 每次触发时，本周未成功就启动游戏并运行上游 `GardenTask`，尝试次数为 `RETRY_MAX_ATTEMPTS` 与 2 的较小值，即最多重试一次，等待时间沿用 `RETRY_DELAY_SECONDS`；每次尝试使用新子进程。按每天触发一次安排，不额外保存每日次数或限制重复触发。
- 周次按北京时间周一 04:00 划分。Garden 无错误结束，或当前任务 `info_get("Log")` 为 `乐园任务完成, 已达到上限`，即记录成功。完成信息优先于错误字段或等待异常，已有报错仍输出到日志；只读取本次子进程中的任务信息，不读取历史日志文件。本周后续定时运行直接跳过，不更新上游、不启动游戏。
- 通知日按北京时间自然日计算；若设为周一，从新一周 04:00 起算。到通知日或之后，当次重试仍失败才通知，上游更新失败也计入。通知后仍允许下次任务触发重试。
- 仅在 `NOTICE_ENABLED=true`、`NOTICE_CHANNEL` 包含 `wxpusher` 且 `WXPUSHER_SPT` 非空时发送，每周成功送达一次；发送失败可在后续触发时重试。周常不发成功通知，不调用 Sheets、Waves API、Mailgun 或 Healthchecks。
- **通知也需要任务触发**，请在通知日或之后安排至少一次运行。没有独立的轮询或定时通知进程。已记录但未完成的周，会在下一次触发时补报；整周从未运行过则没有可补报的记录。
- 成功记录保存在 `.state/weekly/`，按 env 文件绝对路径区分账号，同一账号并发运行时后来的请求跳过。记录不提交 Git，删除记录或重命名 env 会失去本地去重。

启动器第一页面的 **周常乐园** 使用 `--mode weekly --run-now`，手动运行始终执行，不因本周已成功而跳过。手动成功会记录本周完成；手动重跑失败不会清除此前的成功记录，也不会将已成功的一周误报为失败。上游 Garden 自己检测到本周已完成时仍可能立即结束。周常运行结束后清理游戏进程，不执行日常、不消耗体力、不关机。

## 体力 → 周常 → 关机

19 点的任务可以将参数从 `--mode stamina` 改为 `--mode stamina-weekly`：

```powershell
python -m ok_ww_automator.scheduler --mode stamina-weekly
```

也可导入 `windows/stamina_weekly_task.xml`，编辑路径和触发时间后启用；替换原体力任务，不要让两个任务同时触发。原来单独的 `stamina` 和 `weekly` 模式仍然可用。

执行顺序是所有账号的体力任务（各自完成 Healthchecks 上报、日志及通知），再执行所有账号的周常。周常本周已成功则跳过；组合入口不会使用强制手动周常参数。这样一个账号的周常不会推迟另一个账号的体力心跳。上游更新仍在体力阶段之前执行一次，周常阶段不再重复更新。

体力 Runner 读取到的 `shutdown_after_stamina` 配置仍决定是否关机，但关机请求会写入本轮临时文件，由外层延后执行。任一所选账号请求关机，就在所有账号的周常结束后关机一次；全部未请求则不关机。体力失败或跳过仍会继续周常；周常失败、超时或异常也不会跳过最后的关机步骤。周常结果不会修改已经完成的体力 Healthchecks 状态。

每个账号的周常有 **每轮 40 分钟总执行预算**，更新（单独周常模式）、启动游戏、Garden 执行、重试等待及游戏子进程的退出清理共同使用该预算。Garden 单次仍限时 30 分钟。外层等待游戏子进程也有超时，因此原生初始化或退出卡死不会无限等待；超时终止子进程树并清理游戏，再记录失败、按通知日规则通知。强制清理和通知会额外花少量时间。组合模板不再使用原体力模板的 2 小时总限制，以免多账号尚未收尾就被 Windows 直接终止；体力阶段仍沿用原有超时行为。

启动器的 **体力 + 周常** 选项使用同一组合入口，并同样遵守表格中的关机设置。单独的 **周常乐园** 仍是强制手动运行入口。
