# Running tasks

[简体中文](operations_zh.md) · [Setup](../README_en.md) · [Configuration](config.md) · [Maintenance](maintenance.md)

## Scheduling and accounts

Run `python -m ok_ww_automator.scheduler --mode MODE` using the shared Python 3.12 environment. Modes are `daily`, `stamina`, `weekly` and `stamina-weekly`. Without `--account`, every discovered profile runs; repeated `--account` values select accounts in that order. Account jobs run sequentially, with process isolation for upstream global state.

The normal update step fetches OK-WW, merges `origin/master` with `--ff-only`, and installs its `requirements.txt` into the running interpreter. Diverged history or conflicting local changes stop the update. `--skip-update` skips this step; `--ww-root`, `--ww-remote` and `--ww-branch` select another checkout/ref. It does not update the Automator or a sibling ok-script source checkout.

Import the appropriate `windows/*_task.xml` in Windows Task Scheduler. Set the Python executable, working directory, logged-in user, highest privileges and desired trigger. The weekly and combined templates start disabled. Enable one appropriate stamina trigger, not both stamina templates.

Windows triggers use system-local time. Stamina predictions use `DAILY_HOUR`/`DAILY_MINUTE` in Beijing time (UTC+8); these settings do not create Windows triggers. Weekly rules also use Beijing time. Reports use local timestamps. Keep the game desktop accessible during runs.

## Daily and stamina

Daily reads the sheet, consumes a skip-once flag if requested, optionally performs community sign-in through Waves API, and executes upstream DailyTask. It then reads live stamina and daily points, writes a result and sends configured notices. An ended battle pass is treated as optional work; other task errors remain visible.

Stamina checks Waves API first, falling back to a separate game/OCR attempt if unavailable. It predicts regeneration until the next daily run and skips farming if no burn is needed. Planning assumes a 240 current / 480 backup cap, one current point per six minutes and one backup point per twelve minutes after current stamina fills. Tacet costs 60; forgery/simulation costs 40. These are estimates, and upstream farming controls the actual amount consumed.

If a Config read fails, current behavior uses default settings and records the read error in the decision text. Defaults enable daily/stamina, select Tacet #1 and disable shutdown. Missing credentials still prevent construction of the Sheets client. Result-log or notification delivery failures are recorded where possible; check the local output if the remote log is unavailable.

Final states are `success`, `skipped`, `needs review` and `failure`. Healthchecks treats success/skipped as healthy and needs-review/failure as failed. Mailgun/WxPusher receive final reports; `NOTICE_SKIP_SUCCESS` suppresses only success reports. API credentials and notification setup are in [configuration](config.md).

Each attempt gets a fresh game subprocess. The whole child is limited to 40 minutes for daily, 20 for stamina farming, and 15 for a stamina read, including launch and teardown. Task execution itself has a 30-minute daily or 10-minute stamina limit. `RETRY_MAX_ATTEMPTS` and `RETRY_DELAY_SECONDS` govern runner retries.

Game attempts close known Wuthering Waves processes before launch and after completion. They override upstream **Exit After Task** so post-run OCR completes before cleanup. Sheet shutdown flags remain authoritative, including skipped/failed runs. For multiple accounts, shutdown is deferred until all selected jobs finish; one request is enough for final shutdown.

## Weekly Garden

Weekly mode does not use Sheets, Waves API, Mailgun or Healthchecks. Configure each env profile:

```dotenv
WEEKLY_RUN_DAYS=1,3,5
WEEKLY_NOTICE_DAY=5
NOTICE_ENABLED=true
NOTICE_CHANNEL=wxpusher
WXPUSHER_SPT=...
```

Weekdays are 1=Monday through 7=Sunday; blank run days means every day. Weeks reset Monday at 04:00 Beijing time. A scheduled invocation runs only on an allowed day and skips weeks already marked successful, including the update step. Upstream completion is an error-free finish or the current Garden task's exact completion message. At most two attempts run, bounded by the configured retry count and one shared 40-minute budget for updates, game work and retry delays. Forced cleanup and notification may take extra time.

On or after the notice day, an incomplete week triggers a WxPusher failure notice. Allowed days try Garden first; excluded days can still send a notice. Delivery is recorded once per week, and failed delivery can retry. Notifications require an invocation: schedule a trigger on or after the notice day. A previously recorded unfinished week can be reported after reset; an unobserved week has no record.

Local state lives in `.state/weekly/`, keyed by absolute env path. Renaming profiles or deleting state loses deduplication. Concurrent weekly requests for the same profile skip while its lock is held.

`--mode weekly --run-now`, also used by the launcher's **Weekly Garden**, ignores run-day and success skips. Manual success updates the record; manual failure preserves an earlier success. Standalone weekly never requests PC shutdown.

`--mode stamina-weekly` finishes every account's stamina job, logs, notices and Healthchecks before any weekly job starts. It then runs unfinished, allowed weekly jobs and finally honors stamina shutdown requests. A failed stamina account does not prevent later jobs. Updates run once before stamina. The combined template has no two-hour Windows cutoff; avoid overlapping invocations.

## Launcher and extra tasks

Download the launcher from [Releases](https://github.com/2-07665/ok-ww-automator/releases), place it in the Automator root or `dist/`, and keep the shared `.venv` and OK-WW checkout present. It requests administrator rights. One managed operation runs at a time; **Stop** terminates its process tree. Output is saved in `logs/launcher-*.log`.

**Launch Game** reads exactly one selected profile and starts its executable directly, with a three-second button cooldown. It is separate from managed jobs: it neither closes existing games nor tracks/stops that directly launched game.

**OK GUI** runs `ok_ww_automator.ok_main`, adding three tasks in memory without patching upstream:

| Task | Prerequisite and behavior |
| --- | --- |
| Fixed-position echo farming | Prepare a solo Cartethyia at the intended fixed boss position. Counts completed fights, including waiting/pickup time in the displayed rate. Missing-boss detection stops with an error. |
| Five-to-one echo merge | Chinese game UI; merges unlocked echoes. Retries navigation before submission, but stops if a submitted merge's outcome is uncertain. Verify the inventory before restarting. |
| Echo OCR | Chinese echo equipment/upgrade page. Sends valid substats periodically to UDP `127.0.0.1:9999` by default; interval and port are task settings. Empty/invalid OCR leaves the receiver's previous result intact. |

**Auto Farm** uses the already-open game and the same fixed-position farming task. Set a stop time in system-local `HH:MM`; a past time means tomorrow. At the deadline it stops farming and schedules PC shutdown after five seconds. A task error stops the operation without requesting shutdown. Statistics are displayed locally; these custom tasks currently do not append to the legacy `5to1` worksheet.

Build/release instructions and upstream diagnostics are in [maintenance](maintenance.md).
