# Notifications

The `src/ok_ww_automator/notices.py` module dispatches formatted execution reports after a runner completes all retry attempts.

## Notification Triggers

By default, notifications are dispatched for all final task states (e.g., `success`, `failure`, `needs review`, `skipped`). Intermediate `running` states do not trigger a notice.

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