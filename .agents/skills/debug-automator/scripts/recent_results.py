"""Read compact daily/stamina reports using an account's existing Sheets access."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from ok_ww_automator.config import GoogleSheetsConfig, read_dotenv
from ok_ww_automator.env_discovery import discover_account_envs, select_accounts

READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
RENDER_OPTIONS = {"value_render_option": "UNFORMATTED_VALUE", "date_time_render_option": "SERIAL_NUMBER"}
SHEETS_KEYS = ("GOOGLE_SHEET_ID", "GOOGLE_SERVICE_ACCOUNT_JSON_BASE64", "SHEET_NAME_DAILY", "SHEET_NAME_STAMINA")
SECRET_KEYS = ("GOOGLE_SERVICE_ACCOUNT_JSON_BASE64", "WAVES_TOKEN", "WAVES_DID", "MAILGUN_API_KEY",
               "WXPUSHER_SPT", "HEALTHCHECKS_DAILY_UUID", "HEALTHCHECKS_STAMINA_UUID")
BATCH_SIZE = 50
TEXT_LIMIT = 1000
# Column positions follow RunResult.as_daily_row / as_stamina_row, not user headers.
LAYOUTS = {"daily": ("P", 14, 15), "stamina": ("M", 11, 12)}
FAILURE_STATUSES = {"failure", "needs review"}
KNOWN_STATUSES = FAILURE_STATUSES | {"success", "skipped", "running"}


class ReportError(Exception):
    """Only messages constructed here, never raw API exceptions, reach stdout."""


def configured_secrets(values) -> set[str]:
    secrets = {values[key] for key in SECRET_KEYS if values.get(key)}
    try:
        encoded = "".join(values.get("GOOGLE_SERVICE_ACCOUNT_JSON_BASE64", "").split())
        info = json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
        for key in ("private_key", "private_key_id"):
            if isinstance(info.get(key), str) and info[key]:
                secrets.update((info[key], json.dumps(info[key])[1:-1]))
    except Exception:
        pass  # Authentication reports invalid credentials separately.
    return secrets


def redact(value, secrets) -> str:
    text = "" if value is None else str(value)
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)",
                  "[REDACTED PRIVATE KEY]", text, flags=re.DOTALL)
    text = re.sub(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", r"\1 [REDACTED]", text)
    return re.sub(r"(?i)([?&](?:access_token|token|key|api_key|client_secret|password)=)[^&\s\"']+",
                  r"\1[REDACTED]", text)


def read_error(operation: str, exc: Exception) -> str:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in (401, 403):
        return f"Cannot {operation}: Google denied access; check service-account credentials and spreadsheet sharing."
    if status == 404 or type(exc).__name__ == "WorksheetNotFound":
        return f"Cannot {operation}: spreadsheet or worksheet unavailable; check the profile's sheet settings and sharing."
    if status == 429:
        return f"Cannot {operation}: Google rate limit reached; retry later."
    return f"Cannot {operation}; check network access, Sheets permissions, and profile settings. Raw error omitted."


def open_readonly_spreadsheet(config: GoogleSheetsConfig):
    if not config.spreadsheet_id or not config.service_account_json_base64:
        raise ReportError("Missing GOOGLE_SHEET_ID or GOOGLE_SERVICE_ACCOUNT_JSON_BASE64 in this profile/environment.")
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        raise ReportError("Install ok-ww-automator[sheets] into the shared Python environment.") from None
    try:
        encoded = "".join(config.service_account_json_base64.split())
        info = json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
        credentials = Credentials.from_service_account_info(info, scopes=[READONLY_SCOPE])
    except Exception:
        raise ReportError("Invalid service-account credentials; check GOOGLE_SERVICE_ACCOUNT_JSON_BASE64 locally.") from None
    try:
        client = gspread.authorize(credentials)
        client.set_timeout((10, 30))
        return client.open_by_key(config.spreadsheet_id)
    except Exception as exc:
        raise ReportError(read_error("open spreadsheet", exc)) from None


def timestamp(value) -> dt.datetime | None:
    """Sheets serial dates and our ISO strings represent the writer's local time."""
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if not math.isfinite(value):
                return None
            return dt.datetime(1899, 12, 30) + dt.timedelta(seconds=round(value * 86400))
        if isinstance(value, str) and value.strip():
            parsed = dt.datetime.fromisoformat(value.strip())
            return parsed.replace(tzinfo=None)
    except (ValueError, OverflowError, OSError):
        pass
    return None


def cells(row, count: int):
    return (list(row) + [None] * count)[:count]


def interval(row):
    start, end = (timestamp(value) for value in cells(row, 2))
    return start, end, start is not None and end is not None and start <= end


def matches_date(row, day: dt.date | None) -> bool:
    start, end, valid = interval(row)
    if day is None or not valid:
        return True  # Keep uncertain rows visible instead of inventing a date.
    lower = dt.datetime.combine(day, dt.time())
    return start < lower + dt.timedelta(days=1) and end >= lower


def is_header(row, row_number: int) -> bool:
    first, _, _, status = cells(row, 4)
    return row_number == 1 and (
        str(status).strip().lower() in {"status", "状态"}
        or (status in (None, "") and str(first).strip().lower()
            in {"start", "start time", "started at", "started_at", "开始", "开始时间"})
    )


def summarize(row, row_number: int, mode: str, secrets=()) -> dict:
    _, decision_column, error_column = LAYOUTS[mode]
    values = cells(row, error_column + 1)
    start, end, valid = interval(values)
    truncated = []

    def text(value, field, limit=TEXT_LIMIT):
        rendered = redact(value, secrets)
        if len(rendered) > limit:
            truncated.append(field)
            return rendered[:limit]
        return rendered

    metrics = {}
    names = ["stamina_start", "backup_start", "stamina_used", "stamina_left", "backup_left"]
    if mode == "daily":
        names.extend(("daily_points", "next_daily_stamina", "next_daily_backup", "sign_in", "nightmare"))
    else:
        names.extend(("next_daily_stamina", "next_daily_backup"))
    for index, name in enumerate(names, 4):
        value = values[index]
        metrics[name] = value if isinstance(value, (int, float)) and math.isfinite(value) else text(value, name, 80)
    result = {
        "row": row_number,
        "started_at": start.isoformat(sep=" ") if start else None,
        "ended_at": end.isoformat(sep=" ") if end else None,
        "timestamps_valid": valid,
        "status": text(values[3], "status", 80).strip().lower(),
        "metrics": metrics,
        "decision": text(values[decision_column], "decision"),
        "error": text(values[error_column], "error"),
        "truncated_fields": truncated,
    }
    if not valid:
        result["raw_timestamps"] = [text(value, "timestamps", 80) for value in values[:2]]
    return result


def read_reports(worksheet, *, mode: str, day: dt.date | None, limit: int, max_scan_rows: int, failures: bool,
                 secrets=()) -> dict:
    report = {"results": [], "rows_read": 0, "invalid_timestamp_rows": 0, "changed_rows": 0,
              "unknown_status_rows": 0, "incomplete": False, "warnings": []}
    try:
        index = worksheet.get("A:D", **RENDER_OPTIONS)
        occupied = [(number, cells(row, 4)) for number, row in enumerate(index, 1)
                    if any(value not in (None, "") for value in row) and not is_header(row, number)]
        report["indexed_rows"] = len(occupied)
        report["invalid_timestamp_rows"] = sum(not interval(row)[2] for _, row in occupied)
        candidates = [(number, row) for number, row in occupied if matches_date(row, day)]
        def recency(item):
            start, end, valid = interval(item[1])
            return (valid, end if valid else dt.datetime.min, start if valid else dt.datetime.min, item[0])
        candidates.sort(key=recency, reverse=True)
        report["candidate_rows"] = len(candidates)
    except Exception as exc:
        report.update(error=read_error("read timestamp/status index", exc), incomplete=True)
        return report
    selected = candidates[:max_scan_rows]
    cursor = 0
    while cursor < len(selected) and len(report["results"]) < limit:
        batch_size = BATCH_SIZE if failures else min(BATCH_SIZE, limit - len(report["results"]))
        batch = selected[cursor:cursor + batch_size]
        ranges = [f"A{number}:{LAYOUTS[mode][0]}{number}" for number, _ in batch]
        try:
            fetched = worksheet.batch_get(ranges, **RENDER_OPTIONS)
            if len(fetched) != len(batch):
                raise ValueError("incomplete batch response")
            for (number, indexed), rows in zip(batch, fetched):
                row = rows[0] if rows else []
                report["rows_read"] += 1
                if cells(row, 4) != indexed:
                    report["changed_rows"] += 1
                if not row or not matches_date(row, day):
                    continue
                result = summarize(row, number, mode, secrets)
                if result["status"] not in KNOWN_STATUSES:
                    report["unknown_status_rows"] += 1
                if not failures or result["status"] in FAILURE_STATUSES:
                    if len(report["results"]) < limit:
                        report["results"].append(result)
        except Exception as exc:
            report.update(error=read_error("read result rows", exc), incomplete=True)
            break
        cursor += len(batch)
    if len(report["results"]) < limit and len(candidates) > max_scan_rows and cursor >= len(selected):
        report["incomplete"] = True
        report["warnings"].append("Full-row scan budget exhausted; increase --max-scan-rows to inspect older candidates.")
    if report["invalid_timestamp_rows"]:
        report["incomplete"] = True
        report["warnings"].append("Some indexed rows have missing/invalid timestamps; they remain candidates but cannot be matched to a date with certainty.")
    if report["changed_rows"]:
        report["incomplete"] = True
        report["warnings"].append("Rows changed between index and detail reads; date/status filters use the detail read. Rerun for a consistent snapshot.")
    if report["unknown_status_rows"]:
        report["incomplete"] = True
        report["warnings"].append("Unknown statuses were found; --failures only includes failure and needs review.")
    return report


def collect_reports(project_root: Path, *, accounts=None, mode="all", day=None, limit=5, max_scan_rows=200,
                    failures=False, env=None, opener=None) -> dict:
    environment = os.environ if env is None else env
    opener = opener or open_readonly_spreadsheet
    try:
        discovered = discover_account_envs(project_root / "env")
        selected = select_accounts(discovered, accounts)
    except Exception:
        raise ReportError("Cannot select accounts; check the env directory, duplicate account names, and --account values.") from None
    if not selected:
        raise ReportError("No account profiles found under the project's env directory.")
    profiles, unreadable, secrets = {}, [], configured_secrets(environment)
    for account in discovered:
        try:
            raw = read_dotenv(account.path)
            secrets.update(configured_secrets(raw))
            values = {key: environment.get(key, raw.get(key, "")).strip() for key in SHEETS_KEYS}
            profiles[account.account_id] = GoogleSheetsConfig(
                spreadsheet_id=values["GOOGLE_SHEET_ID"] or None,
                service_account_json_base64=values["GOOGLE_SERVICE_ACCOUNT_JSON_BASE64"] or None,
                daily_runs_sheet=values["SHEET_NAME_DAILY"] or "DailyRuns",
                stamina_runs_sheet=values["SHEET_NAME_STAMINA"] or "StaminaRuns",
            )
        except Exception:
            unreadable.append(account.account_id)
    destinations = {}
    for account, config in profiles.items():
        if config.spreadsheet_id:
            for task in LAYOUTS:
                title = getattr(config, f"{task}_runs_sheet")
                destinations.setdefault((config.spreadsheet_id, title), []).append(f"{account}/{task}")
    output = {"date": day.isoformat() if day else None, "failures_only": failures,
              "limit_per_worksheet": limit, "max_scan_rows_per_worksheet": max_scan_rows,
              "order": "end/start timestamps descending, row number as tie-break; invalid timestamps last",
              "timestamp_basis": "writer's local time; stored timestamps lack UTC offsets",
              "account_provenance": "profile destination mapping; result rows contain no account identifier",
              "environment_overrides": [key for key in SHEETS_KEYS if key in environment],
              "unreadable_profiles": unreadable, "reports": []}
    for account in selected:
        config = profiles.get(account.account_id)
        try:
            if config is None:
                raise ReportError("Cannot read this profile; check its dotenv syntax and file access.")
            spreadsheet = opener(config)
            open_error = None
        except Exception as exc:
            open_error = str(exc) if isinstance(exc, ReportError) else read_error("open spreadsheet", exc)
        for task in LAYOUTS if mode == "all" else (mode,):
            title = getattr(config, f"{task}_runs_sheet") if config else None
            report = {"account": account.account_id, "mode": task, "worksheet": title,
                      "shared_destination_with": [name for name in destinations.get((config.spreadsheet_id, title), [])
                                                  if name != f"{account.account_id}/{task}"] if config else []}
            if open_error:
                report.update(results=[], error=open_error, incomplete=True)
            else:
                try:
                    worksheet = spreadsheet.worksheet(title)
                    report.update(read_reports(worksheet, mode=task, day=day, limit=limit,
                                               max_scan_rows=max_scan_rows, failures=failures, secrets=secrets))
                except Exception as exc:
                    report.update(results=[], error=read_error("open worksheet", exc), incomplete=True)
            output["reports"].append(report)
    return output


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
        if parsed > 0:
            return parsed
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("must be a positive integer")


def requested_date(value: str) -> dt.date:
    if value == "today":
        return dt.date.today()
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("use YYYY-MM-DD or today (machine-local date)") from None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        "Reads the narrow A:D timestamp/status index across history, then bounded detail rows; "
        "never downloads the full wide log. Date matching uses local start/end overlap, including midnight. "
        "Unknown dates stay flagged candidates. Profile env values are overridden by process environment "
        "as in the scheduler; output lists override names and shared destinations. No sheet writes or notices."))
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--account", action="append", help="Profile name; repeat to select/order accounts. Default: all discovered.")
    parser.add_argument("--mode", choices=("daily", "stamina", "all"), default="all")
    parser.add_argument("--date", type=requested_date, help="YYYY-MM-DD or today; omit for most recent rows.")
    parser.add_argument("--limit", type=positive_int, default=5, help="Maximum results per account/worksheet (default: 5).")
    parser.add_argument("--max-scan-rows", type=positive_int, default=200, help="Full-row budget per account/worksheet (default: 200).")
    parser.add_argument("--failures", action="store_true", help="Only failure and needs review; without this, include all statuses.")
    args = parser.parse_args(argv)
    try:
        output = collect_reports(args.project_root.resolve(), accounts=args.account, mode=args.mode, day=args.date,
                                 limit=args.limit, max_scan_rows=args.max_scan_rows, failures=args.failures)
    except ReportError as exc:
        output = {"error": str(exc), "reports": []}
    print(json.dumps(output, ensure_ascii=True, indent=2, allow_nan=False))
    return int("error" in output or bool(output.get("unreadable_profiles"))
               or any(item.get("incomplete") for item in output["reports"]))


if __name__ == "__main__":
    raise SystemExit(main())
