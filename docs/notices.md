# Notifications

The `src/ok_ww_automator/notices.py` module dispatches formatted execution reports after a runner completes all retry attempts.

## Notification Triggers

By default, notifications are dispatched for all final task states (e.g., `success`, `failure`, `needs review`, `skipped`). Intermediate `running` states do not trigger a notice.

Set `NOTICE_SKIP_SUCCESS=true` to suppress notifications when the final task result is `success`. Other final states still trigger notifications.

## Healthchecks.io

Set `HEALTHCHECKS_ENABLED=true` and provide both `HEALTHCHECKS_DAILY_UUID` and `HEALTHCHECKS_STAMINA_UUID` to monitor scheduled runs with Healthchecks.io. The runner pings `https://hc-ping.com/<uuid>/start` when a run starts, then pings `https://hc-ping.com/<uuid>` for healthy completions (`success` or `skipped`) and `https://hc-ping.com/<uuid>/fail` for `failure` or `needs review`. Each run uses a Healthchecks `rid` query parameter so start and completion pings are matched.

## Supported Channels

You can enable notifications using the following environment variables:

```powershell
NOTICE_ENABLED=true
NOTICE_CHANNEL=mailgun,wxpusher
```

### Mailgun

Sends an HTML-formatted email via the Mailgun API.

Requires:
- `MAILGUN_API_KEY`
- `MAILGUN_DOMAIN`
- `MAILGUN_RECIPIENT`

### WxPusher

Sends a rich-text notification to WeChat via the WxPusher simple-push API.

Requires:
- `WXPUSHER_SPT`

## Templating

The notification module uses lightweight, dependency-free HTML templating located in `src/ok_ww_automator/notice_templates/`. These templates use inline CSS and provide responsive layouts optimized for mobile devices.
