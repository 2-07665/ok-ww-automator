# ok-ww-automator

[English](README_en.md) | 简体中文

通过 [OK-WW](https://github.com/ok-oldking/ok-wuthering-waves) 执行鸣潮日常、体力和周常乐园。每个账号使用独立的 env 文件，日常和体力设置从 Google Sheets 读取。Windows 启动器还提供固定位置声骸速刷，以及带额外任务的上游 OK 界面。

## 安装

使用 Windows、Python 3.12，并先在 OK-WW 中配置好游戏。两个仓库共用父目录下的虚拟环境：

```text
workspace/
  .venv/Scripts/python.exe
  ok-ww-automator/
  ok-wuthering-waves/
  ok-script/                  # 维护时可选的源码仓库
```

克隆两个项目后，在父目录执行：

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -e "./ok-ww-automator[sheets,waves,notice,launcher]"
uv pip install --python .venv/Scripts/python.exe -r ./ok-wuthering-waves/requirements.txt
cd ok-ww-automator
Copy-Item env/.env.example env/cn.env
```

编辑 `env/cn.env`，填写 `GAME_EXE_PATH`；日常和体力任务还需要 Google Sheets 凭据。将表格以编辑权限共享给服务账号，创建 `Config`、`DailyRuns`、`StaminaRuns` 工作表，按[表格说明](docs/sheets_zh.md)填写配置。环境变量和可选集成见[配置说明](docs/config_zh.md)。

每个 `env/*.env` 文件代表一个账号：`cn.env` 对应 `cn`，`.env` 对应 `default`。这些文件选择游戏路径和凭据，不会在同一个游戏安装中自动切换登录账号。

## 使用

在 `ok-ww-automator` 目录中，先检查账号和更新计划：

```powershell
../.venv/Scripts/python.exe -m ok_ww_automator.scheduler --mode daily --dry-run
../.venv/Scripts/python.exe -m ok_ww_automator.scheduler --mode daily --account cn
```

`--dry-run` 只打印计划，不验证凭据或连接服务。实际调度默认以快进合并更新 OK-WW，并把其依赖安装到当前 Python 环境；`--skip-update` 可保留当前版本。每次游戏尝试会重启游戏，并在独立进程中执行。

| 操作 | 接在 `../.venv/Scripts/python.exe -m` 后的命令 |
| --- | --- |
| 日常任务 | `ok_ww_automator.scheduler --mode daily` |
| 额外体力任务 | `ok_ww_automator.scheduler --mode stamina` |
| 按本周状态执行乐园 | `ok_ww_automator.scheduler --mode weekly` |
| 所有账号体力完成后执行未完成周常 | `ok_ww_automator.scheduler --mode stamina-weekly` |
| 带额外任务的 OK 界面 | `ok_ww_automator.ok_main` |
| 使用已打开的游戏速刷，到系统本地 03:00 后关机 | `ok_ww_automator.auto_farm --stop-time 03:00` |

可重复指定 `--account cn --account global` 来选择账号及顺序。定时执行时导入 `windows/` 下的 XML 模板，先修改路径、登录用户和触发时间。周常、关机、时区及自定义任务前置条件见[运行说明](docs/operations_zh.md)。

## 启动器与维护

从 [Releases](https://github.com/2-07665/ok-ww-automator/releases) 下载 `OKAutomatorLauncher.exe`，放入 Automator 根目录或 `dist/`。它会请求管理员权限，并使用上面的共享 Python 环境。界面包括速刷、日常/体力/周常、OK 工具和本地日志；直接启动游戏时只能选择一个账号。

接受上游更新前，按[维护指南](docs/maintenance.md)运行 doctor 并检查兼容性。指南同时说明测试、Codex 更新技能、本地启动器构建和 tag 发布。使用已激活环境时请加 `uv run --active`，避免普通 `uv run` 在项目内创建另一个 `.venv`。
