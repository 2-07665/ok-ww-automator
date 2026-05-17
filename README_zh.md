# ok-ww-automator

鸣潮日常任务自动化 CLI 辅助工具，基于 [ok-script](https://github.com/ok-script/ok-script) 和 [ok-wuthering-waves](https://github.com/ok-script/ok-wuthering-waves) 构建。

本项目旨在通过提供基于 Google Sheets 的远程配置、多账号隔离、精确的体力消耗计算以及稳健的错误通知来编排游戏自动化。

## 特性

- **解耦的编排逻辑**: 将调度、重试逻辑和体力计算与底层的游戏交互彻底分离。
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