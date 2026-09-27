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
- `--mode weekly`
- `--mode stamina-weekly`

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
- `windows/weekly_task.xml`: disabled by default; configure its weekdays/time and enable after import.

### How to use:

1. Open **Task Scheduler**.
2. Click **Import Task...** in the Actions pane.
3. Select one of the XML files.
4. **Important:** Edit the imported task. Under **Actions**, set the shared Python executable and working directory to your local paths (templates use `D:\game\ok-ww`). Select the logged-in user, highest privileges, and run only while that user is logged in. Enable the trigger.

## Weekly Garden

**Windows Task Scheduler controls when to invoke the runner.** Each account then filters weekly execution by its `WEEKLY_RUN_DAYS` in Beijing time. Import `windows/weekly_task.xml`, edit its trigger (the template only gives daily 05:00 system-local time as an example), and enable it. The command is `python -m ok_ww_automator.scheduler --mode weekly`; `--account cn` limits the account and `--skip-update` skips upstream updates.

Each account configures its allowed run days and failure notification day in its own env:

```dotenv
WEEKLY_RUN_DAYS=1,3,5
WEEKLY_NOTICE_DAY=5
```

Values `1` through `7` mean Monday through Sunday. `WEEKLY_RUN_DAYS` uses Beijing calendar days; omitted or blank allows every day. `WEEKLY_NOTICE_DAY` defaults to `7`. Neither setting creates or changes Windows triggers.

- Each invocation runs upstream `GardenTask` only on an allowed day and if this week has not already succeeded. Attempts are capped at the smaller of `RETRY_MAX_ATTEMPTS` and 2 (at most one retry), with the existing retry delay and a fresh game subprocess for each attempt. Schedule one invocation per day; no daily attempt counter or duplicate-trigger limit is persisted.
- Weeks reset Monday at 04:00 Beijing time. An error-free Garden finish, or the current task's `info_get("Log")` matching `乐园任务完成, 已达到上限`, records success. Completion info overrides error fields or waiting exceptions; errors remain in the output for diagnosis. Only the current subprocess's task info is read, never historical log files. Later scheduled runs skip without updating upstream or starting the game.
- The notice day is a Beijing calendar day; Monday starts at the new week's 04:00 reset. On or after this day, an allowed run day attempts Garden before reporting failure; an excluded day checks the weekly success record directly and notifies if incomplete. Update failures count too. Later invocations on allowed days can still retry the game.
- Notification requires `NOTICE_ENABLED=true`, `wxpusher` in `NOTICE_CHANNEL`, and a nonempty `WXPUSHER_SPT`. Successful delivery is recorded once per week; failed delivery can retry on later invocations. Weekly runs do not use success notices, Sheets, Waves API, Mailgun, or Healthchecks.
- **Notifications also require an invocation.** Schedule at least one trigger on or after the notice day. There is no background polling or notification timer. Recorded unfinished weeks can be reported on the next invocation after reset; weeks with no invocation have no record to report.
- Records under `.state/weekly/` identify accounts by absolute env path. Concurrent requests for the same account skip. Records are ignored by Git; deleting them or renaming env files loses local deduplication.

The launcher's **Weekly Garden** uses `--mode weekly --run-now`. Manual runs ignore allowed run days and execute even after weekly success. Manual success records completion; a failed manual rerun preserves prior success and does not falsely report that week as incomplete. Upstream Garden may itself return immediately if it detects completion. Weekly runs clean up the game process afterwards, without dailies, stamina farming, or PC shutdown.

## Stamina → Weekly Garden → Shutdown

For the 19:00 task, replace `--mode stamina` with `--mode stamina-weekly`:

```powershell
python -m ok_ww_automator.scheduler --mode stamina-weekly
```

Alternatively import `windows/stamina_weekly_task.xml`, configure its paths/time and enable it instead of the old stamina task. Do not run both triggers together. Standalone `stamina` and `weekly` modes remain available.

All accounts finish stamina, including their Healthchecks completion, logs and notices, before any account starts weekly work. Invoke the combined mode daily: all accounts clear stamina daily, while each account runs Garden only on its own `WEEKLY_RUN_DAYS`. Weekly work skips accounts already successful this week; the combined entry does not force a manual rerun. This prevents one account's Garden from delaying another account's stamina heartbeat. Upstream updates still run once before stamina, with no second update before weekly work.

Each stamina runner's existing `shutdown_after_stamina` setting remains authoritative. Shutdown requests are recorded in a temporary file and handled once by the outer scheduler after all weekly jobs. Any selected account requesting shutdown triggers that final shutdown; no requests means no shutdown. Failed or skipped stamina runs still proceed to weekly work. Weekly failures, timeouts and exceptions do not bypass final shutdown or change already-completed stamina Healthchecks results.

Each account's weekly work shares a **40-minute execution budget per invocation** across updates (standalone weekly mode), game startup, Garden execution, retry delays and game-child teardown. Garden itself still has a 30-minute per-attempt limit. Waiting for the child process is also bounded, covering hung native startup/teardown. Timeout terminates the process tree and cleans up the game before recording failure and applying notice-day rules. Forced cleanup and notification can take additional time. The combined template removes the old two-hour Windows limit so it cannot interrupt multi-account cleanup/shutdown; stamina keeps its existing timeout behavior.

The launcher's **Stamina + Weekly** option uses this same entry and honors the sheet's shutdown setting. Standalone **Weekly Garden** remains the forced manual option.
