# OK Automator Launcher（Windows）

`OK Automator Launcher` 是现有 Automator 公共入口的轻量级提权桌面前端。它从 `env/*.env` 中发现账号配置，可启动常规 OK GUI 或单个所选账号的游戏，并按界面中的显示顺序为选定账号运行 Daily 或 Stamina 调度。它不会安装、修复、激活或更新 Python 环境。

## 工作区结构与可执行文件位置

启动器要求以下同级目录结构：

```text
<workspace>\
├── .venv\Scripts\python.exe
├── ok-ww-automator\
└── ok-wuthering-waves\
```

请将 `OKAutomatorLauncher.exe` 放在 `ok-ww-automator` 或 `ok-ww-automator\dist` 中。启动器会从自身目录向上查找 Automator 项目，并验证上述三个路径；如果目录结构不完整，启动操作将保持禁用状态。

共享虚拟环境必须按照主安装指南安装 `ok-ww-automator` 和上游依赖。该可执行文件会直接调用 `<workspace>\.venv\Scripts\python.exe`，它自身不包含、也不替代自动化运行环境。

## UAC 与进程行为

可执行文件包含 `requireAdministrator` 清单，因此每次启动时 Windows 都会请求 UAC 提权。其子 Python 进程、调度器、游戏及辅助进程都会继承提升后的权限。由于可执行文件未签名，Windows 可能显示“未知发布者”警告。

启动器同一时间只允许一个操作运行。标准输出和错误输出会合并显示在有容量上限的实时日志中。点击 **Stop**，或在操作运行时确认关闭窗口，会终止完整的 Windows 进程树，避免遗留调度器子进程或游戏进程。

每次刷新时都会默认选中所有发现的账号配置。`.env.example` 会被排除，`.env` 显示为 `default`，`CN.env` 等名称会保留原始大小写。账号选择、顺序和模式不会在启动器会话之间保存。

只有恰好选中一个账号时，**Launch Game** 才会启用。它会校验该账号配置中的 `GAME_EXE_PATH`，然后直接启动对应可执行文件；账号多选功能仍保留给 scheduler 任务。游戏启动特意与 Automator 托管任务分离：它不会检测或关闭已经运行的游戏，启动后 launcher 也不会监控、停止或以其他方式管理游戏。按钮使用后会禁用 3 秒，以防快速重复点击造成意外多开。

## 构建

请使用共享虚拟环境中的原生 Windows Python 3.12。安装构建额外依赖，然后在 Automator 项目目录中运行 PowerShell 构建脚本：

```powershell
uv pip install --python ..\.venv\Scripts\python.exe -e ".[build]"
.\windows\build_launcher.ps1
```

脚本使用现有的 `ok-wuthering-waves\icons\icon.ico`，并生成单窗口、单文件可执行程序：

```text
dist\OKAutomatorLauncher.exe
```

两个项目的常规源码更新都不需要重新构建启动器。只有启动器功能或其稳定契约发生变化时才需要重建：`env/*.env` 账号配置、调度器重复的 `--account` 参数，或 `ok_ww_automator.ok_main` / `ok_ww_automator.scheduler` 模块入口。调度器原有的内置上游更新行为保持不变。
