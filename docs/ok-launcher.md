# OK Launcher Adapter

The `src/ok_ww_automator/ok_launcher.py` module serves as the low-level bridge between the automator and the upstream `ok-wuthering-waves` project. 

It imports the upstream runtime lazily. This design ensures that core orchestrators, configuration parsers, and data models can be unit-tested instantly without requiring a heavy PySide/GUI environment or a running game instance.

## Core Responsibilities

- **Path Management**: Temporarily adds the `ok-wuthering-waves` checkout root to `sys.path`.
- **Context Switching**: Executes the upstream `ok.OK` runtime within the context of the `ok-wuthering-waves` working directory so that relative paths (like `configs/`, `logs/`, and `screenshots/`) resolve correctly to the upstream directory.
- **Headless Initialization**: Forces `config["use_gui"] = False` and validates that `OK(config)` creates a headless `task_executor`.
- **Game Launch**: Starts the `Wuthering Waves.exe` client if the preferred capture device is missing or disconnected.
- **Readiness Polling**: Blocks task execution until device capture and interaction layers are confirmed ready.
- **Task Execution**: Provides the `run_onetime_task()` wrapper, which handles timeouts, executor-exit events, and surfaces localized task error strings.

## Manual GUI Launch

If you wish to run the standard OK graphical interface but with the automator's custom tasks injected, use the manual entrypoint:

```powershell
uv run --active python -m ok_ww_automator.ok_main
```

This acts as a drop-in replacement for `python main.py` in `ok-wuthering-waves`, appending tasks like `FastFarmEchoTask` and `FiveToOneTask` to the in-memory configuration without modifying the upstream source.
