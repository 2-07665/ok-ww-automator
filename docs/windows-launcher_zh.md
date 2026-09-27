# OK Automator Launcher（Windows）

`OK Automator Launcher` 是现有 Automator 公共入口的轻量级提权桌面前端。它从 `env/*.env` 中发现账号配置，可启动常规 OK GUI 或单个所选账号的游戏，并按界面中的显示顺序为选定账号运行 Daily、Stamina 或 Weekly 调度。它不会安装、修复、激活或更新 Python 环境。

第一页面的 **周常乐园** 可一键启动游戏并运行 Garden：本周已成功也会执行；成功后更新本周记录，重跑失败则保留此前成功记录。周次按北京时间周一 04:00 划分。定时运行与失败通知设置见 [周常乐园调度](scheduler_zh.md#周常乐园)。添加此入口需要重新构建启动器 EXE。

第一页面也提供 **体力 + 周常**：先完成所有账号的体力与 Healthchecks，再执行尚未完成的周常，最后统一处理原体力配置的关机请求。单独周常和组合模式的跳过规则不同，详见 [组合调度](scheduler_zh.md#体力--周常--关机)。

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

## 下载 Release

打开仓库的 [Releases](https://github.com/2-07665/ok-ww-automator/releases)，从所需版本的 **Assets** 下载 `OKAutomatorLauncher.exe`，放到 `ok-ww-automator\dist` 中。Release 附件不使用 Actions 临时产物的保留期限。

[Release Windows launcher](https://github.com/2-07665/ok-ww-automator/actions/workflows/build-launcher.yml) 仅在推送 `v` 开头的 tag 时构建，普通分支推送和 PR 不触发。它使用 Windows x64、Python 3.12 和 `uv.lock` 中锁定的 `launcher`、`build` 依赖，执行现有启动器测试及 GUI 初始化检查，然后调用本地同一份构建脚本。上游只读取固定提交中的图标，不安装或运行 ok-script、游戏任务及 OCR 依赖。构建成功后自动创建对应 tag 的 Release，生成发布说明并附上 EXE。

需要发布时，先提交要发布的代码和工作流，再创建、推送一个新版本 tag。例如：

```powershell
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

将示例版本号替换为本次的新版本号。CI 构建的是 tag 指向的提交，下载后配合该版本源码使用。请由工作流创建 Release，无需提前在网页上创建同名 Release；构建失败可在 Actions 中重试，已经发布的版本有改动时使用新 tag。

下载 EXE 可以省去本机构建及 PowerShell 执行策略设置，但仍需按安装指南准备共享 Python 环境、两个仓库和任务配置。此产物是启动器，不包含完整自动化运行环境；CI 的 GUI 检查也不代表真实游戏任务已通过验证。

## 本地构建

如果需要自行构建，请先将两个项目放在上面的同级目录中，并安装 `uv`。从 Automator 项目目录执行以下命令；创建环境的第一条命令仅用于共享 `.venv` 尚不存在的首次安装：

```powershell
uv venv --python 3.12 ..\.venv
uv pip install --python ..\.venv\Scripts\python.exe -e ".[launcher,build]"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\windows\build_launcher.ps1
```

最后一条命令只对本次 PowerShell 进程设置执行策略。构建脚本本身不会创建虚拟环境或安装依赖；只有 clone 项目还不能直接构建。请先关闭正在运行的启动器，以便覆盖旧 EXE。

脚本使用现有的 `ok-wuthering-waves\icons\icon.ico`，临时收窄构建进程的 `PATH` 以避免打包其他工具的不兼容 DLL，中间文件位于 `build\launcher`，生成单窗口、单文件可执行程序：

```text
dist\OKAutomatorLauncher.exe
```

两个项目的常规源码更新都不需要重新构建启动器。只有启动器功能或其稳定契约发生变化时才需要重建：`env/*.env` 账号配置、调度器重复的 `--account` 参数，或 `ok_ww_automator.ok_main` / `ok_ww_automator.scheduler` 模块入口。调度器原有的内置上游更新行为保持不变。
