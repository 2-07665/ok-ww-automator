# OK 启动器适配器

`src/ok_ww_automator/ok_launcher.py` 模块充当 automator 与上游 `ok-wuthering-waves` 项目之间的底层桥梁。

它采用延迟加载的方式导入上游运行时。这种设计确保了核心编排器、配置解析器和数据模型可以在不需要繁重的 PySide/GUI 环境或运行中的游戏实例的情况下，立即进行单元测试。

## 核心职责

- **路径管理**: 临时将 `ok-wuthering-waves` 的签出根目录添加到 `sys.path`。
- **上下文切换**: 在 `ok-wuthering-waves` 工作目录的上下文中执行上游的 `ok.OK` 运行时，以便相对路径（如 `configs/`、`logs/` 和 `screenshots/`）能够正确解析到上游目录。
- **无头初始化**: 强制设置 `config["use_gui"] = False`，并验证 `OK(config)` 是否成功创建了无头的 `task_executor`。
- **游戏启动**: 如果首选捕获设备丢失或未连接，则启动 `Wuthering Waves.exe` 客户端。
- **就绪轮询**: 阻塞任务执行，直到确认设备捕获和交互层均已就绪。
- **任务执行**: 提供 `run_onetime_task()` 包装器，用于处理超时、执行器退出事件，并抛出本地化的任务错误字符串。

## 手动 GUI 启动

如果您希望运行标准的 OK 图形界面，但同时注入 automator 的自定义任务，请使用手动入口点：

```powershell
uv run --active python -m ok_ww_automator.ok_main
```

这可以作为 `ok-wuthering-waves` 中 `python main.py` 的直接替代品，它会在内存配置中追加如 `FastFarmEchoTask` 和 `StaminaTask` 等任务，而无需修改上游源代码。