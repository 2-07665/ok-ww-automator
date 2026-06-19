# Runtime Configuration

`ok-ww-automator` loads runtime configuration from the process environment, supplemented by an optional `.env` file. If a variable exists in both, the process environment takes precedence.

## Environment File Resolution

By default, the application looks for `env/.env` relative to the project root. 
You can override this by setting the `ENV_FILE` environment variable. Providing a bare filename (e.g., `ENV_FILE=cn.env`) will resolve to `env/cn.env`. This keeps the Windows Task Scheduler commands concise.

Use `env/.env.example` as a template for new accounts.

## Integration Flags and Secrets

The configuration module is designed to fail lazily. Secrets and credentials are only validated when an optional feature is actually executed.

- **Game Execution**: `GAME_EXE_PATH` is required before launching the game adapter.
- **Google Sheets**: `GOOGLE_SHEET_ID` and `GOOGLE_SERVICE_ACCOUNT_JSON_BASE64` are required to read or append to sheets. Requires the `[sheets]` install extra.
- **Waves API**: `WAVES_ROLE_ID`, `WAVES_TOKEN`, and `WAVES_DID` are required if `WAVES_API_ENABLED=true`. Requires the `[waves]` install extra.
- **Notices**: `NOTICE_CHANNEL` specific secrets (like `MAILGUN_API_KEY` or `WXPUSHER_SPT`) are required if `NOTICE_ENABLED=true`. Requires the `[notice]` install extra.
- **Healthchecks.io**: `HEALTHCHECKS_DAILY_UUID` and `HEALTHCHECKS_STAMINA_UUID` are required if `HEALTHCHECKS_ENABLED=true`.

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `ENV_FILE` | `env/.env` | Path to the dotenv file. |
| `GAME_EXE_PATH` | *unset* | Absolute path to `Wuthering Waves.exe`. |
| `DAILY_HOUR` | `5` | Assumed daily task run hour (0-23, UTC+8). Used for stamina calculations. |
| `DAILY_MINUTE` | `0` | Assumed daily task run minute (0-59). |
| `GOOGLE_SHEET_ID` | *unset* | Target Google Spreadsheet ID. |
| `GOOGLE_SERVICE_ACCOUNT_JSON_BASE64` | *unset* | Base64 encoded Service Account JSON credentials. |
| `SHEET_NAME_CONFIG` | `Config` | Name of the configuration worksheet. |
| `SHEET_NAME_DAILY` | `DailyRuns` | Name of the daily results log worksheet. |
| `SHEET_NAME_STAMINA` | `StaminaRuns` | Name of the stamina results log worksheet. |
| `SHEET_NAME_FASTFARM` | `5to1` | Name of the fast-farm results log worksheet. |
| `WAVES_API_ENABLED` | `false` | Enable Kuro/Waves API for fast stamina checks. |
| `WAVES_ROLE_ID` | *unset* | Waves API role ID. |
| `WAVES_TOKEN` | *unset* | Waves API token. |
| `WAVES_DID` | *unset* | Waves API device ID. |
| `RETRY_MAX_ATTEMPTS` | `2` | Maximum game launch attempts before failing. |
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

*(Note: Boolean variables accept `true`, `1`, `yes`, `on`, `是` and their negative counterparts.)*
