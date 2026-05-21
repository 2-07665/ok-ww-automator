# AI Agent Guidelines

This document provides strictly enforced instructions and strategic context for AI coding assistants working on the `ok-ww-automator` project.

## Architecture & Module Overview

The project is structured to enforce a strict boundary between high-level orchestration and low-level game interaction. For detailed module behaviors, refer to the [docs/](./docs/) directory.

1. **Data Models ([docs/models.md](./docs/models.md))**: Pure Python dataclasses representing state. **Rule**: Zero dependencies on UI libraries or network clients.
2. **Scheduler ([docs/scheduler.md](./docs/scheduler.md))**: The entrypoint for automated runs. **Rule**: Must spawn child processes for each account run to avoid `ok-script` global state deadlocks.
3. **Runners ([docs/runners.md](./docs/runners.md))**: Business logic (fetching configs, decision trees, calculating burn). **Rule**: Runners must remain agnostic to UI implementation details.
4. **Game Clients ([docs/runners.md](./docs/runners.md#architectural-boundary))**: The adapter layer. This is the **only** place where `ok-script` or `ok-wuthering-waves` modules are manipulated.
5. **Launcher ([docs/ok-launcher.md](./docs/ok-launcher.md))**: Manages `sys.path` injection and `cwd` switching for the upstream repo.
6. **Integrations**: Optional features for [Google Sheets](./docs/sheets.md), [Waves API](./docs/waves-api.md), and [Notifications](./docs/notices.md).

## Core Design Principles

1. **Subprocess Isolation**: Always isolate the `ok.OK()` lifecycle to a single subprocess when dealing with multiple accounts.
2. **Lazy Integration**: Optional integrations (e.g., `gspread`, `requests`) must be imported lazily. This ensures core tests execute instantly without network or heavy dependencies.
3. **One-Way Configuration**: Live game state (e.g., current stamina) is **never** written back to the Google Sheets `Config` worksheet. It is only appended to log worksheets.
4. **Stateless Runners**: Runners should not maintain internal state across multiple game attempts; use `models.RunResult` to accumulate outcome data.
5. **Upstream Purity**: Treat `ok-wuthering-waves` as a clean upstream checkout. Do not add files to it or require a `custom/` package inside it.

## Project Assumptions

1. **Repository Layout**: `ok-ww-automator` and `ok-wuthering-waves` are sibling checkouts under one parent workspace, commonly `D:\dev\game\ok-ww`. The automator may also reference `ok-script`, but changes for this project should stay in `ok-ww-automator` unless the user explicitly asks otherwise.
2. **Shared Virtual Environment**: Use one parent virtual environment for both `ok-ww-automator` and `ok-wuthering-waves`: `<workspace>/.venv`. Do not create or use `ok-ww-automator/.venv`. When running commands from this repo, prefer the shared interpreter directly, for example `../.venv/Scripts/python.exe -m unittest discover -s tests` on Windows or `../.venv/bin/python -m unittest discover -s tests` on POSIX.
3. **uv Usage**: Avoid plain `uv run` from inside `ok-ww-automator`; it can create a local project `.venv` and rewrite `uv.lock` for the current platform. If using uv, use the already-active shared environment (`uv run --active ...`) or install into the parent environment intentionally.
4. **Windows Runtime Target**: The scheduled automation is designed for Windows Task Scheduler. Imported task XML files must point to the parent `.venv` Python executable and use the parent workspace as the working directory.
5. **Account Profiles**: Runtime configuration is loaded from process environment plus an optional dotenv file. Account files live in `env/`; bare `ENV_FILE` values like `cn.env` resolve to `env/cn.env`.
6. **Game Path**: `GAME_EXE_PATH` is required before launching the game adapter and must point to `Wuthering Waves.exe`, not the `Client-Win64-Shipping.exe` binary.
7. **Upstream Context**: `ok_launcher.py` temporarily adds the `ok-wuthering-waves` checkout to `sys.path` and temporarily switches `cwd` so upstream relative paths such as `configs/`, `logs/`, and `screenshots/` resolve inside `ok-wuthering-waves`.
8. **Scheduler Entrypoint**: `src/ok_ww_automator/scheduler.py` is the intended Windows Task Scheduler entrypoint. Multi-account runs must spawn isolated Python child processes because `ok-script` keeps process-global state and named Windows mutexes.

## Log-Driven Bug Fix Workflow

The user will frequently provide or refresh `ok-wuthering-waves/logs/ok-script.log` and ask for bugs to be fixed from the log evidence. These logs can be very large.

1. **Update Upstream First**: At the start of a bug fix, run `git pull` in sibling checkouts `../ok-script` and `../ok-wuthering-waves` so the investigation accounts for upstream changes that may have broken or fixed the workflow. If either checkout has local changes or pull fails, report that and continue from the available state without overwriting user work.
2. **Sample, Then Search**: Do not dump the whole log. Start with `tail -n 200 ../ok-wuthering-waves/logs/ok-script.log` from `ok-ww-automator`, then use targeted `rg -n` searches for timestamps, task names, `ERROR`, `WARNING`, `Traceback`, `exception`, `timeout`, `stuck`, `TaskExecutor`, `StartController`, `DeviceManager`, and mode-specific terms such as `stamina`, `daily`, or the task name in question.
3. **Correlate Timeline**: Identify the first failure, later retries/restarts, and the last repeated symptom. Repeated heartbeat lines are usually less important than the transition where expected lines stop appearing.
4. **Prefer Adapter Fixes**: When the log points to scheduler, launcher, retry, environment, process, or task-selection behavior, fix `ok-ww-automator` first. Only modify `ok-wuthering-waves` or `ok-script` if the user explicitly asks and the root cause is clearly in upstream code.
5. **Keep Evidence Tight**: In the response, cite the key log lines or timestamps and explain why they imply the fix. Avoid pasting long tracebacks unless the user asks.
6. **Add Regression Coverage**: Add or update focused unit tests that reproduce the logged failure mode with fakes/mocks. Keep tests in `ok-ww-automator/tests` unless the touched code is elsewhere.
7. **Protect Runtime Artifacts**: Do not create `ok-ww-automator/.venv`, do not let `uv.lock` drift while investigating, and do not edit upstream logs/configs/screenshots as part of a fix unless the user asks.

## Development & Testing

Always verify changes by running the full test suite from the project root:

```powershell
# Run all unit tests
..\.venv\Scripts\python.exe -m unittest discover -s tests

# Check for compilation/syntax errors
..\.venv\Scripts\python.exe -m compileall -q src tests main.py
```

*Note: On POSIX, use `../.venv/bin/python`.*

## Future Work

- **Orchestration Refinement**: Consolidate the boilerplate in `DailyRunner` and `StaminaRunner` (e.g., common `run()` wrapper/context manager).
- **Dynamic Config**: Refactor `SheetRunConfig` to use field metadata for Sheets labels, removing the manual mapping in `sheets.py`.
- **Healthchecks**: Add external monitoring/healthchecks for missed or stuck scheduled runs.
