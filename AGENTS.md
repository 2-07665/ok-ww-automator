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

## Development & Testing

Always verify changes by running the full test suite from the project root:

```powershell
# Run all unit tests
python -m unittest discover -s tests

# Check for compilation/syntax errors
python -m compileall -q src tests main.py
```

*Note: Use the virtual environment's Python (`.venv\Scripts\python.exe`) when running these commands.*

## Future Work

- **Orchestration Refinement**: Consolidate the boilerplate in `DailyRunner` and `StaminaRunner` (e.g., common `run()` wrapper/context manager).
- **Dynamic Config**: Refactor `SheetRunConfig` to use field metadata for Sheets labels, removing the manual mapping in `sheets.py`.
- **Healthchecks**: Add external monitoring/healthchecks for missed or stuck scheduled runs.
