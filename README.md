# ok-ww-automator

[English](README_en.md) | 简体中文

鸣潮日常任务自动化 CLI 辅助工具，并额外提供可注入的自定义 OK 任务，基于 [ok-script](https://github.com/ok-script/ok-script) 和 [ok-wuthering-waves](https://github.com/ok-script/ok-wuthering-waves) 构建。

本项目的自动化能力提供基于 Google Sheets 的远程配置、多账号隔离、精确的体力消耗计算以及稳健的错误通知。除此之外，本项目还提供一组独立的自定义 OK 任务，可注入到常规 OK GUI 中使用。

## 特性

- **解耦的编排逻辑**: 将调度、重试逻辑和体力计算与底层的游戏交互彻底分离。
- **可注入的自定义任务**: 提供一组独立于自动化流程的额外 OK 任务，可注入到常规 OK GUI 中运行。
- **远程配置**: 从 Google Sheets 读取任务设置，允许您在不触碰主机的情况下更新日常任务配置。
- **多账号支持**: 自动发现 `env/` 目录下的环境文件，并在独立的 Python 子进程中隔离运行每个账号。
- **智能体力管理**: 优先使用 Waves API (或 OCR 后备) 预测体力溢出情况，仅在需要时才启动游戏。
- **消息通知**: 通过 Mailgun 或 WxPusher 发送详细的执行日志。

## 安装指南

### 1. 环境与依赖

请为 `ok-ww-automator` 和 `ok-wuthering-waves` 使用同一个父级虚拟环境。在两个项目的父目录中执行：

```powershell
uv venv .venv
.\.venv\Scripts\Activate.ps1

# 安装 automator 及其所有可选集成
cd .\ok-ww-automator
uv pip install -e ".[sheets,waves,notice]"

# 安装上游游戏项目的依赖
cd ..\ok-wuthering-waves
uv pip install -r requirements.txt
```

### 2. 环境配置

复制示例环境文件以创建您的默认账号配置：

```powershell
cd D:\dev\game\ok-ww\ok-ww-automator
cp env\.env.example env\.env
```

打开 `env\.env` 并填写所需的变量：
- `GAME_EXE_PATH`: `Wuthering Waves.exe` 的路径。
- `GOOGLE_SHEET_ID`: 您的 Google Spreadsheet ID。
- `GOOGLE_SERVICE_ACCOUNT_JSON_BASE64`: Base64 编码的 Google 服务账号 JSON。
- Waves API 和通知配置（可选）。

*注意：您可以在 `env/` 目录中创建多个文件（例如 `cn.env`, `global.env`）来进行多账号调度。*

### 3. Google Sheets 设置

创建一个包含以下工作表的 Google 表格：
- `Config`: 成对的标签/值配置 (具体标签请参阅 `docs/sheets_zh.md`)。
- `DailyRuns`: 日常任务结果日志。
- `StaminaRuns`: 体力消耗结果日志。
- `5to1`: 声骸五合一及速刷结果日志。

### 4. Windows 任务计划程序

我们提供了 XML 预设，以便轻松将自动化任务导入到 Windows 任务计划程序中。

1. 打开 **任务计划程序 (Task Scheduler)**。
2. 点击操作窗格中的 **导入任务... (Import Task...)**。
3. 导入 `windows/daily_task.xml` 和 `windows/stamina_task.xml`。
4. **重要提示**: 编辑导入的任务。在 **操作 (Actions)** 选项卡下，确认 **程序或脚本 (Command)** (`.venv\Scripts\python.exe` 的路径) 和 **起始于 (Working Directory)** 与您的本地环境匹配。

## 手动使用

如果想启动带有 automator 额外任务注入的常规 OK GUI：

```powershell
uv run --active python -m ok_ww_automator.ok_main
```

手动运行调度器（空跑测试）：

```powershell
uv run --active python -m ok_ww_automator.scheduler --mode daily --dry-run
```

## Windows 提权启动器

可选的单文件 `OK Automator Launcher` 提供常规 OK GUI 启动、为单个所选账号直接启动游戏，以及按顺序执行的多账号 Daily/Stamina 任务，并带有内嵌日志和完整进程树停止功能。只有恰好选中一个账号时，**Launch Game** 才会启用；它会读取该账号的 `GAME_EXE_PATH` 并直接启动。它不会检测、关闭或管理已有及新启动的游戏进程，按钮还带有 3 秒冷却时间，以防误操作造成连续多开。多选功能仍用于 scheduler 任务。可直接从 [Releases](https://github.com/2-07665/ok-ww-automator/releases) 下载 `OKAutomatorLauncher.exe`，无需本地构建。需要发布新版本时，推送 `v` 开头的版本 tag，CI 会自动构建并创建 Release；普通代码推送不触发构建。

如需本地构建，先按安装指南准备共享 Python 3.12 环境和同级上游仓库，再在 `ok-ww-automator` 目录执行：

```powershell
uv pip install --python ..\.venv\Scripts\python.exe -e ".[launcher,build]"
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\build_launcher.ps1
```

构建过程会使用现有的上游 OK 图标，并生成：

```text
dist\OKAutomatorLauncher.exe
```

请将可执行文件保留在 `ok-ww-automator\dist` 中，或复制到 `ok-ww-automator` 根目录。运行时必须保留同级的 `..\.venv\Scripts\python.exe` 和 `..\ok-wuthering-waves` 项目。每次启动该可执行文件时，Windows 都会通过 UAC 请求管理员权限。

Automator 或上游项目的常规源码更新不需要重新构建启动器。只有启动器功能或其已记录的外部契约发生变化时才需要重建。行为和兼容性详情请参阅 [Windows 启动器指南](docs/windows-launcher_zh.md)。
