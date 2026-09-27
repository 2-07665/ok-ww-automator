# AGENTS.md

## Project Map

- `scheduler.py`: Windows Task Scheduler entrypoint; discovers accounts, validates configuration, updates the upstream checkout, and dispatches jobs.
- `runners.py`: Daily/stamina orchestration, decisions, retries, persistence, notifications, and healthcheck signaling. Keep it independent of UI implementation details.
- `game_clients.py` and `game_attempt.py`: Boundary between orchestration and the upstream OK runtime. Each game attempt runs in a fresh subprocess.
- `ok_launcher.py`: Loads the sibling `ok-wuthering-waves` checkout and manages its runtime context.
- `models.py` and `time_utils.py`: Pure data and calculations. They must not depend on UI or network libraries.
- `config.py`, `sheets.py`, `waves_api.py`, `notices.py`, and `healthchecks.py`: Configuration and optional external integrations.
- `ok_main.py` and `ok_tasks/`: Manual GUI launcher and automator-owned injectable OK tasks; separate from scheduled orchestration.
- `windows_launcher.py` and `windows/`: Elevated desktop launcher plus its isolated PyInstaller entrypoint, manifest, and build script.
- `docs/`: Detailed behavior and configuration reference.

## Design Rules

1. **Isolate the OK lifecycle.** `ok-script` keeps process-global state and a cwd-based Windows mutex that `ok.quit()` does not fully release. Every retry or separate game attempt must use `SubprocessDailyGameClient` or `SubprocessStaminaGameClient`; never recreate `OkDailyGameClient` or `OkStaminaGameClient` repeatedly in one process. Multi-account scheduler jobs must also remain process-isolated.
2. **Keep boundaries explicit.** Runners own business decisions; game clients and the launcher own scheduled upstream/UI interaction. Direct upstream imports are also allowed in `ok_tasks/`, where they are required for injectable GUI tasks.
3. **Keep upstream checkouts clean.** Make project changes in `ok-ww-automator` only.
4. **Minimize upstream coupling throughout the repository.** Every added upstream package, import, API call, configuration assumption, and compatibility patch must be necessary for a concrete project requirement. Prefer standard-library and automator-owned logic where practical; keep unavoidable OK/WW integration at the existing boundaries. Avoid depending on private implementation details or adding version checks, metadata inspection, or compatibility layers without a demonstrated need. Tests should verify automator behavior without unnecessarily reproducing upstream internals. Do not raise the upstream version requirement merely to simplify local implementation.
5. **Do not patch upstream globally without a demonstrated need.** The tested runtime already handles missing feature/OCR frames; the former global `FindFeature.find_feature` replacement is redundant. Removing it is not a guarantee of compatibility with arbitrary past or future upstream versions.

## Repository and Runtime Assumptions

- `ok-ww-automator`, `ok-wuthering-waves`, and optionally `ok-script` are sibling checkouts under one workspace. `ok_launcher.py` temporarily adds the upstream checkout to `sys.path` and switches `cwd` so its relative `configs/`, `logs/`, and `screenshots/` paths resolve correctly.
- Use the shared parent virtual environment at `../.venv`; do not create `ok-ww-automator/.venv`.
- Prefer `uv run --active ...` when using uv. Plain `uv run` inside this project can create a local environment and rewrite `uv.lock` for the current platform.
- WSL may show widespread sibling-checkout changes caused only by CRLF/LF normalization. Before treating them as user edits, inspect `git status --porcelain=v2 --branch`, `git diff --stat`, and ahead/behind state.
