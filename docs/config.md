# Account configuration

[简体中文](config_zh.md) · [Operations](operations.md)

Copy `env/.env.example` for each account. The scheduler discovers `env/*.env`, excluding the example. `.env` becomes account `default`; other filenames lose the `.env` suffix. Process environment variables override file values, so avoid globally setting account-specific credentials for multi-account jobs.

Standalone configuration and Sheets CLI default to `env/.env`; `ENV_FILE=cn.env` resolves to `env/cn.env`. Select scheduler profiles with `--account cn`. Values preserve Unicode; shell variables are not expanded. Double-quoted values decode escapes such as `\n`, `\r` and `\t`. For Windows paths use single quotes, an unquoted value, or forward slashes (for example `GAME_EXE_PATH='D:\new\tools\Game.exe'`).

Daily/stamina require Sheets credentials, and game attempts require `GAME_EXE_PATH`. Weekly requires `GAME_SERVER`, the game and optional WxPusher configuration. Waves API, notifications and Healthchecks require their credentials when enabled; Healthchecks requires both daily and stamina UUIDs.

## Environment variables

| Variable | Default | Description |
| --- | --- | --- |
| `ENV_FILE` | `env/.env` | Path to the dotenv file. |
| `GAME_SERVER` | *unset* | Required for weekly mode: `CN`, `US`, `EU`, `ASIA`, `SEA`, `HMT` (case-insensitive). Set per account; never inferred from filenames. |
| `GAME_EXE_PATH` | *unset* | Absolute path to `Wuthering Waves.exe`. |
| `DAILY_HOUR` | `5` | Assumed daily task run hour (0-23, UTC+8). Used for stamina calculations. |
| `DAILY_MINUTE` | `0` | Assumed daily task run minute (0-59). |
| `WEEKLY_RUN_DAYS` | `1,2,3,4,5,6,7` | Allowed server calendar weekdays per account, e.g. `1,3,5`. Omitted/blank allows every day. Manual weekly runs ignore this filter. |
| `WEEKLY_NOTICE_DAY` | `7` | Weekly failure notice day in server time, 1=Monday through 7=Sunday. An invocation on/after this day notifies if the week is incomplete, including excluded run days. |
| `GOOGLE_SHEET_ID` | *unset* | Target Google Spreadsheet ID. |
| `GOOGLE_SERVICE_ACCOUNT_JSON_BASE64` | *unset* | Base64 encoded Service Account JSON credentials. |
| `SHEET_NAME_CONFIG` | `Config` | Name of the configuration worksheet. |
| `SHEET_NAME_DAILY` | `DailyRuns` | Name of the daily results log worksheet. |
| `SHEET_NAME_STAMINA` | `StaminaRuns` | Name of the stamina results log worksheet. |
| `SHEET_NAME_FASTFARM` | `5to1` | Legacy farming-result writer worksheet; current farm/merge tasks do not append automatically. |
| `WAVES_API_ENABLED` | `false` | Enable Kuro/Waves API for fast stamina checks. |
| `WAVES_ROLE_ID` | *unset* | Waves API role ID. |
| `WAVES_TOKEN` | *unset* | Waves API token. |
| `WAVES_DID` | *unset* | Waves API device ID. |
| `RETRY_MAX_ATTEMPTS` | `2` | Runner attempt limit (at least 1); weekly additionally caps at 2 attempts and a total budget. |
| `RETRY_DELAY_SECONDS` | `30` | Wait time between game launch retries. |
| `NOTICE_ENABLED` | `false` | Enable post-run notifications. |
| `NOTICE_CHANNEL` | *unset* | Comma-separated list of channels (`mailgun`, `wxpusher`). |
| `NOTICE_ACCOUNT_ID` | *unset* | Display label prefixed to notice subjects. |
| `NOTICE_SKIP_SUCCESS` | `false` | Suppress notifications when the final task result is `success`. |
| `MAILGUN_API_KEY` | *unset* | Mailgun API key. |
| `MAILGUN_DOMAIN` | *unset* | Mailgun sending domain. |
| `MAILGUN_RECIPIENT` | *unset* | Target email address for notices. |
| `WXPUSHER_SPT` | *unset* | WxPusher simple-push token. |
| `HEALTHCHECKS_ENABLED` | `false` | Enable Healthchecks.io pings for scheduled runs. |
| `HEALTHCHECKS_DAILY_UUID` | *unset* | Healthchecks.io check UUID for the daily task. |
| `HEALTHCHECKS_STAMINA_UUID` | *unset* | Healthchecks.io check UUID for the stamina task. |


Booleans accept `true/false`, `1/0`, `yes/no`, `on/off`, `是/否`, with case-insensitive English values.

`DAILY_HOUR`/`DAILY_MINUTE` only set the Beijing-time prediction target; Windows triggers use system-local time. Weeks reset Monday 04:00 on the configured server clock. See [weekly operations](operations.md#weekly-garden) for run-day and notice-day behavior.
