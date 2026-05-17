# Scheduler Entrypoint

The `src/ok_ww_automator/scheduler.py` module is the single intended entrypoint for Windows Task Scheduler. 

Its primary job is to discover configured accounts, update the upstream repositories, and safely spawn execution processes for each account.

## Subprocess Isolation

When a run contains more than one account job, the scheduler spawns each account in an isolated child Python process. This is a critical design requirement because `ok-script` retains process-global states and named Windows mutexes. Constructing a second `OK` runtime in the same Python process will result in deadlocks during game readiness checks.

## Discovery and Modes

The scheduler treats every `.env` file in the `env/` folder (except `.env.example`) as a distinct, runnable account profile. 

The account ID is derived from the filename:
- `env/cn.env` -> Account ID: `cn`
- `env/global.env` -> Account ID: `global`
- `env/.env` -> Account ID: `default`

The scheduler requires an explicit mode and does not combine tasks automatically. Schedule the daily login and the extra stamina login as separate triggers:
- `--mode daily`
- `--mode stamina`

## Example Usage

Run the daily task for all discovered accounts:
```powershell
uv run --active python -m ok_ww_automator.scheduler --mode daily
```

Dry-run to verify the plan without launching the game:
```powershell
uv run --active python -m ok_ww_automator.scheduler --mode daily --dry-run
```

Run a specific account:
```powershell
uv run --active python -m ok_ww_automator.scheduler --mode daily --account cn
```

## Windows Task Scheduler Presets

XML presets are provided in the `windows/` folder to simplify setup:

- `windows/daily_task.xml`
- `windows/stamina_task.xml`

### How to use:

1. Open **Task Scheduler**.
2. Click **Import Task...** in the Actions pane.
3. Select one of the XML files.
4. **Important:** Edit the imported task. Under the **Actions** tab, update the **Command** (Python executable) and **Working Directory** paths to match your local setup. The presets default to `D:\dev\game\ok-ww`.