# ok-ww-automator

English | [简体中文](README.md)

CLI automation helpers for Wuthering Waves daily routines, with additional injectable custom OK tasks, built on top of [ok-script](https://github.com/ok-script/ok-script) and [ok-wuthering-waves](https://github.com/ok-script/ok-wuthering-waves).

The automation workflow provides remote configuration via Google Sheets, multi-account isolation, precise stamina burn calculations, and robust failure notifications. In addition, this project provides a separate set of custom OK tasks that can be injected into the regular OK GUI.

## Features

- **Decoupled Orchestration**: Separates scheduling, retry logic, and stamina calculation from the low-level game interaction.
- **Injectable Custom Tasks**: Provides a separate set of extra OK tasks, independent from the automation workflow, that can be injected into the regular OK GUI.
- **Remote Configuration**: Reads task settings from a Google Sheet, allowing you to update your daily routines without touching the host machine.
- **Multi-Account Support**: Discovers environment files in the `env/` directory and isolates each account run in its own Python subprocess.
- **Smart Stamina Management**: Predicts stamina overflow using the Waves API (or OCR fallback) to only launch the game when necessary.
- **Notices**: Sends detailed execution logs via Mailgun or WxPusher.

## Setup Guide

### 1. Environment and Dependencies

Use a single parent virtual environment for both `ok-ww-automator` and `ok-wuthering-waves`. From the parent directory of both projects:

```powershell
uv venv .venv
.\.venv\Scripts\Activate.ps1

# Install automator with all optional integrations
cd .\ok-ww-automator
uv pip install -e ".[sheets,waves,notice]"

# Install upstream game dependencies
cd ..\ok-wuthering-waves
uv pip install -r requirements.txt
```

### 2. Configuration

Copy the example environment file to create your default account configuration:

```powershell
cd D:\dev\game\ok-ww\ok-ww-automator
cp env\.env.example env\.env
```

Open `env\.env` and fill in the required variables:
- `GAME_EXE_PATH`: Path to `Wuthering Waves.exe`.
- `GOOGLE_SHEET_ID`: Your Google Spreadsheet ID.
- `GOOGLE_SERVICE_ACCOUNT_JSON_BASE64`: Base64 encoded Google Service Account JSON.
- Waves API and Notice configurations (optional).

*Note: You can create multiple files (e.g., `cn.env`, `global.env`) in the `env/` directory for multi-account scheduling.*

### 3. Google Sheets Setup

Create a Google Spreadsheet with the following worksheets:
- `Config`: Pairwise label/value configuration (see `docs/sheets.md` for exact labels).
- `DailyRuns`: Log for daily task results.
- `StaminaRuns`: Log for stamina burn results.
- `5to1`: Log for echo fast-farm results.

### 4. Windows Task Scheduler

XML presets are provided to easily import the automated tasks into Windows Task Scheduler.

1. Open **Task Scheduler**.
2. Click **Import Task...** in the Actions pane.
3. Import `windows/daily_task.xml` and `windows/stamina_task.xml`.
4. **Important**: Edit the imported tasks. Under the **Actions** tab, verify the **Command** (path to `.venv\Scripts\python.exe`) and **Working Directory** match your local environment.

## Manual Usage

To launch the normal OK GUI with the extra automator tasks injected:

```powershell
uv run --active python -m ok_ww_automator.ok_main
```

To run the scheduler manually (dry-run):

```powershell
uv run --active python -m ok_ww_automator.scheduler --mode daily --dry-run
```
