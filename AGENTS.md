# Agent Guidelines

Use this file for durable project constraints. Keep feature plans and completed work in issues or release notes, not here.

## Project Map

- `scheduler.py`: Windows Task Scheduler entrypoint; discovers accounts, validates configuration, updates the upstream checkout, and dispatches jobs.
- `runners.py`: Daily/stamina orchestration, decisions, retries, persistence, notifications, and healthcheck signaling. Keep it independent of UI implementation details.
- `game_clients.py` and `game_attempt.py`: Boundary between orchestration and the upstream OK runtime. Each game attempt runs in a fresh subprocess.
- `ok_launcher.py`: Loads the sibling `ok-wuthering-waves` checkout, manages its runtime context, and applies narrowly scoped compatibility patches.
- `models.py` and `time_utils.py`: Pure data and calculations. They must not depend on UI or network libraries.
- `config.py`, `sheets.py`, `waves_api.py`, `notices.py`, and `healthchecks.py`: Configuration and optional external integrations.
- `ok_main.py` and `ok_tasks/`: Manual GUI launcher and automator-owned injectable OK tasks; separate from scheduled orchestration.
- `windows_launcher.py` and `windows/`: Elevated desktop launcher plus its isolated PyInstaller entrypoint, manifest, and build script.
- `docs/`: Detailed behavior and configuration reference.

## Non-Negotiable Design Rules

1. **Isolate the OK lifecycle.** `ok-script` keeps process-global state and a cwd-based Windows mutex that `ok.quit()` does not fully release. Every retry or separate game attempt must use `SubprocessDailyGameClient` or `SubprocessStaminaGameClient`; never recreate `OkDailyGameClient` or `OkStaminaGameClient` repeatedly in one process. Multi-account scheduler jobs must also remain process-isolated.
2. **Keep boundaries explicit.** Runners own business decisions; game clients and the launcher own scheduled upstream/UI interaction. Direct upstream imports are also allowed in `ok_tasks/`, where they are required for injectable GUI tasks.
3. **Keep upstream checkouts clean.** Make project changes in `ok-ww-automator`. Do not add a `custom/` package or other project files to `ok-wuthering-waves` unless the user explicitly requests an upstream change.
4. **Load optional integrations lazily.** Core imports and unit tests must not require `gspread`, `requests`, credentials, or network access.
5. **Do not write live state into Sheets configuration.** Game state belongs in result-log worksheets. The intentional exception is clearing a `skip_*_once` control after it is consumed.
6. **Keep runners stateless across attempts.** Accumulate per-run data in `RunResult`, not mutable runner state carried between attempts.
7. **Treat runtime patches as fragile.** `ok_launcher.install_runtime_safety_patches()` guards missing capture frames by patching `ok.task.task.FindFeature.find_feature`. Re-check it whenever upstream task, frame, or feature APIs change.

## Repository and Runtime Assumptions

- `ok-ww-automator`, `ok-wuthering-waves`, and optionally `ok-script` are sibling checkouts under one workspace. `ok_launcher.py` temporarily adds the upstream checkout to `sys.path` and switches `cwd` so its relative `configs/`, `logs/`, and `screenshots/` paths resolve correctly.
- Use the shared parent virtual environment at `../.venv`; do not create `ok-ww-automator/.venv`.
- Prefer `uv run --active ...` when using uv. Plain `uv run` inside this project can create a local environment and rewrite `uv.lock` for the current platform.
- Runtime configuration comes from the process environment plus an optional dotenv file. Account files live in `env/`; a bare `ENV_FILE` such as `cn.env` resolves to `env/cn.env`.
- `GAME_EXE_PATH` must point to `Wuthering Waves.exe`, not `Client-Win64-Shipping.exe`.
- Scheduled automation targets Windows Task Scheduler. Imported XML tasks must use the parent `.venv` Python executable and the parent workspace as their working directory.
- WSL may show widespread sibling-checkout changes caused only by CRLF/LF normalization. Before treating them as user edits, inspect `git status --porcelain=v2 --branch`, `git diff --stat`, and ahead/behind state.

## Log-Driven Bug Fixes

When investigating `../ok-wuthering-waves/logs/ok-script.log`:

1. Pull `../ok-script` and `../ok-wuthering-waves` first. If either checkout has local changes or cannot be updated, preserve it, report the limitation, and continue with the available state.
2. Start with `tail -n 200`; do not dump the whole log. Search with `rg -n` for the relevant timestamp/task plus `ERROR`, `WARNING`, `Traceback`, `exception`, `timeout`, `stuck`, `TaskExecutor`, `StartController`, and `DeviceManager`.
3. Correlate the first failure, retry/restart transitions, and final repeated symptom. Heartbeats matter mainly where expected progress stops.
4. Prefer fixes in this repository for scheduler, launcher, environment, retry, process, or task-selection problems. Change upstream only when explicitly requested and supported by the evidence.
5. Add focused regression tests under `tests/`, and cite only the key timestamps or log lines in the handoff.
6. Do not modify logs, screenshots, runtime configuration, `uv.lock`, or upstream source as incidental cleanup.
