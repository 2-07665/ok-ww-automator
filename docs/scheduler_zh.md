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

### 如何使用：

1. 打开 **任务计划程序 (Task Scheduler)**。
2. 点击操作窗格中的 **导入任务... (Import Task...)**。
3. 选择其中一个 XML 文件。
4. **重要提示:** 编辑导入的任务。在 **操作 (Actions)** 选项卡下，更新 **程序或脚本 (Command)** (Python 可执行文件) 和 **起始于 (Working Directory)** 路径以匹配您的本地设置。预设默认使用 `D:\dev\game\ok-ww`。