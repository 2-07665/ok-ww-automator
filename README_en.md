# ok-ww-automator

English | [简体中文](README.md)

Run Wuthering Waves daily, stamina and weekly Garden tasks through [OK-WW](https://github.com/ok-oldking/ok-wuthering-waves). Each account has an env profile; daily and stamina settings come from Google Sheets. A Windows launcher also exposes fixed-position echo farming and the upstream OK interface with extra tasks.

## Install

Use Windows and Python 3.12, with the game already configured in OK-WW. Keep the checkouts and one shared virtual environment together:

```text
workspace/
  .venv/Scripts/python.exe
  ok-ww-automator/
  ok-wuthering-waves/
  ok-script/                  # optional source checkout for maintenance
```

From the workspace directory, with both projects cloned:

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -e "./ok-ww-automator[sheets,waves,notice,launcher]"
uv pip install --python .venv/Scripts/python.exe -r ./ok-wuthering-waves/requirements.txt
cd ok-ww-automator
Copy-Item env/.env.example env/cn.env
```

Edit `env/cn.env`: set `GAME_EXE_PATH` and, for daily/stamina jobs, the Google Sheets credentials. Share the spreadsheet with the service account as an editor and create `Config`, `DailyRuns` and `StaminaRuns`. Fill the [Config labels](docs/sheets.md); env secrets and optional integrations are listed in [configuration](docs/config.md).

Additional `env/*.env` files become separate accounts. `cn.env` means account `cn`; `.env` means `default`. Profiles select executables and credentials; they do not implement account switching inside a shared game installation.

## Run

From `ok-ww-automator`, inspect account selection and update commands first:

```powershell
../.venv/Scripts/python.exe -m ok_ww_automator.scheduler --mode daily --dry-run
../.venv/Scripts/python.exe -m ok_ww_automator.scheduler --mode daily --account cn
```

`--dry-run` prints a plan without validating credentials or contacting services. Live scheduled jobs normally update OK-WW with a fast-forward merge and install its requirements into the current interpreter. Use `--skip-update` to retain the installed version. Game attempts restart the game and run in isolated processes.

| Action | Command after `../.venv/Scripts/python.exe -m` |
| --- | --- |
| Daily tasks | `ok_ww_automator.scheduler --mode daily` |
| Extra stamina run | `ok_ww_automator.scheduler --mode stamina` |
| Weekly Garden, respecting weekly state | `ok_ww_automator.scheduler --mode weekly` |
| All stamina jobs, then unfinished weekly jobs | `ok_ww_automator.scheduler --mode stamina-weekly` |
| OK interface with extra tasks | `ok_ww_automator.ok_main` |
| Farm the already-open game, then shut down at local 03:00 | `ok_ww_automator.auto_farm --stop-time 03:00` |

Use repeated `--account cn --account global` options to select and order accounts. Schedule commands using the XML templates under `windows/`, after editing their paths, logged-in user and trigger times. See [operations](docs/operations.md) for weekly rules, shutdown, timezones and custom-task prerequisites.

## Desktop launcher and maintenance

Download `OKAutomatorLauncher.exe` from [Releases](https://github.com/2-07665/ok-ww-automator/releases) and place it in the Automator root or `dist/`. It requests administrator rights and uses the shared Python environment above. Its pages cover farming, daily/stamina/weekly jobs, OK tools and local logs. Direct game launch requires exactly one selected profile.

Before accepting an upstream update, run the [doctor and compatibility workflow](docs/maintenance.md). That guide also covers tests, the Codex update skill, local launcher builds and tagged releases. For activated environments, use `uv run --active`; plain `uv run` can create an unintended project-local `.venv`.
