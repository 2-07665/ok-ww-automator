"""Runtime configuration for ok-ww-automator.

This module intentionally has no third-party dependencies. It is imported by
every other module, including failure paths where optional integrations may not
be installed yet.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

ENV_FILE_ENV = "ENV_FILE"
DEFAULT_ENV_PATH = Path("env") / ".env"

TRUE_VALUES = {"true", "1", "yes", "y", "是", "on"}
FALSE_VALUES = {"false", "0", "no", "n", "否", "off"}


class ConfigError(RuntimeError):
    """Raised when required configuration is unavailable or invalid."""


@dataclass(frozen=True)
class DailyRunTimeConfig:
    hour: int = 5
    minute: int = 0


@dataclass(frozen=True)
class GoogleSheetsConfig:
    spreadsheet_id: str | None = None
    service_account_json_base64: str | None = None
    config_sheet: str = "Config"
    daily_runs_sheet: str = "DailyRuns"
    stamina_runs_sheet: str = "StaminaRuns"
    fast_farm_runs_sheet: str = "5to1"

    def require_credentials(self) -> None:
        missing = []
        if not self.spreadsheet_id:
            missing.append("GOOGLE_SHEET_ID")
        if not self.service_account_json_base64:
            missing.append("GOOGLE_SERVICE_ACCOUNT_JSON_BASE64")
        if missing:
            raise ConfigError(f"Missing Google Sheets config: {', '.join(missing)}")


@dataclass(frozen=True)
class WavesApiConfig:
    enabled: bool = False
    role_id: str | None = None
    token: str | None = None
    did: str | None = None

    def require_credentials(self) -> None:
        missing = []
        if not self.role_id:
            missing.append("WAVES_ROLE_ID")
        if not self.token:
            missing.append("WAVES_TOKEN")
        if not self.did:
            missing.append("WAVES_DID")
        if missing:
            raise ConfigError(f"Missing Waves API config: {', '.join(missing)}")


@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int = 2
    delay_seconds: float = 30.0


@dataclass(frozen=True)
class NoticeConfig:
    enabled: bool = False
    channels: tuple[str, ...] = ()
    account_id: str | None = None
    mailgun_api_key: str | None = None
    mailgun_domain: str | None = None
    mailgun_recipient: str | None = None
    wxpusher_spt: str | None = None

    def require_channel_credentials(self, channel: str) -> None:
        normalized = normalize_notice_channel(channel)
        if normalized == "mailgun":
            missing = []
            if not self.mailgun_api_key:
                missing.append("MAILGUN_API_KEY")
            if not self.mailgun_domain:
                missing.append("MAILGUN_DOMAIN")
            if not self.mailgun_recipient:
                missing.append("MAILGUN_RECIPIENT")
            if missing:
                raise ConfigError(f"Missing Mailgun config: {', '.join(missing)}")
            return
        if normalized == "wxpusher":
            if not self.wxpusher_spt:
                raise ConfigError("Missing WxPusher config: WXPUSHER_SPT")
            return
        raise ConfigError(f"Unsupported notice channel: {channel}")


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    env_path: Path
    game_exe_path: Path | None = None
    daily_run_time: DailyRunTimeConfig = field(default_factory=DailyRunTimeConfig)
    google_sheets: GoogleSheetsConfig = field(default_factory=GoogleSheetsConfig)
    waves_api: WavesApiConfig = field(default_factory=WavesApiConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    notice: NoticeConfig = field(default_factory=NoticeConfig)

    def require_game_exe_path(self) -> Path:
        if self.game_exe_path is None:
            raise ConfigError("Missing game config: GAME_EXE_PATH")
        return self.game_exe_path


def load_config(
    *,
    env: Mapping[str, str] | None = None,
    project_root: Path | None = None,
    env_file: str | Path | None = None,
) -> AppConfig:
    """Load runtime config from process env plus an optional dotenv file.

    Values already present in `env` win over dotenv values. This mirrors the
    common dotenv convention and lets scheduled tasks override a shared file.
    """

    root = (project_root or Path.cwd()).resolve()
    process_env = dict(os.environ if env is None else env)
    resolved_env_path = resolve_env_path(root, process_env, env_file)
    dotenv_values = read_dotenv(resolved_env_path)
    values = {**dotenv_values, **process_env}

    return AppConfig(
        project_root=root,
        env_path=resolved_env_path,
        game_exe_path=_path_or_none(values.get("GAME_EXE_PATH")),
        daily_run_time=DailyRunTimeConfig(
            hour=_int_value(values, "DAILY_HOUR", 5, minimum=0, maximum=23),
            minute=_int_value(values, "DAILY_MINUTE", 0, minimum=0, maximum=59),
        ),
        google_sheets=GoogleSheetsConfig(
            spreadsheet_id=_blank_to_none(values.get("GOOGLE_SHEET_ID")),
            service_account_json_base64=_blank_to_none(values.get("GOOGLE_SERVICE_ACCOUNT_JSON_BASE64")),
            config_sheet=_str_value(values, "SHEET_NAME_CONFIG", "Config"),
            daily_runs_sheet=_str_value(values, "SHEET_NAME_DAILY", "DailyRuns"),
            stamina_runs_sheet=_str_value(values, "SHEET_NAME_STAMINA", "StaminaRuns"),
            fast_farm_runs_sheet=_str_value(values, "SHEET_NAME_FASTFARM", "5to1"),
        ),
        waves_api=WavesApiConfig(
            enabled=_bool_value(values, "WAVES_API_ENABLED", False),
            role_id=_blank_to_none(values.get("WAVES_ROLE_ID")),
            token=_blank_to_none(values.get("WAVES_TOKEN")),
            did=_blank_to_none(values.get("WAVES_DID")),
        ),
        retry=RetryConfig(
            max_attempts=_int_value(values, "RETRY_MAX_ATTEMPTS", 2, minimum=1, maximum=10),
            delay_seconds=_float_value(values, "RETRY_DELAY_SECONDS", 30.0, minimum=0.0, maximum=3600.0),
        ),
        notice=NoticeConfig(
            enabled=_bool_value(values, "NOTICE_ENABLED", False),
            channels=parse_notice_channels(values.get("NOTICE_CHANNEL")),
            account_id=_blank_to_none(values.get("NOTICE_ACCOUNT_ID")),
            mailgun_api_key=_blank_to_none(values.get("MAILGUN_API_KEY")),
            mailgun_domain=_blank_to_none(values.get("MAILGUN_DOMAIN")),
            mailgun_recipient=_blank_to_none(values.get("MAILGUN_RECIPIENT")),
            wxpusher_spt=_blank_to_none(values.get("WXPUSHER_SPT")),
        ),
    )


def resolve_env_path(
    project_root: Path,
    env: Mapping[str, str],
    env_file: str | Path | None = None,
) -> Path:
    raw_value = env_file if env_file is not None else env.get(ENV_FILE_ENV)
    if raw_value is None or str(raw_value).strip() == "":
        return project_root / DEFAULT_ENV_PATH

    raw_path = Path(str(raw_value).replace("\\", "/")).expanduser()
    if raw_path.is_absolute():
        return raw_path

    candidates = [
        project_root / raw_path,
        project_root / "env" / raw_path,
    ]
    if raw_path.parent == Path("."):
        candidates.insert(0, project_root / "env" / raw_path.name)
    return next((candidate for candidate in candidates if candidate.exists()), candidates[0])


def read_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        if "=" not in line:
            raise ConfigError(f"Invalid dotenv line {line_number} in {path}: missing '='")
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise ConfigError(f"Invalid dotenv line {line_number} in {path}: missing key")
        values[key] = _unquote_dotenv_value(raw_value.strip())
    return values


def parse_bool(raw: str | bool | None, *, default: bool = False) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    normalized = raw.strip().lower()
    if normalized == "":
        return default
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ConfigError(f"Invalid boolean value: {raw!r}")


def parse_notice_channels(raw: str | None) -> tuple[str, ...]:
    channels: list[str] = []
    for value in _csv_values(raw):
        normalized = normalize_notice_channel(value)
        if normalized is None:
            raise ConfigError(f"Unsupported notice channel: {value}")
        if normalized not in channels:
            channels.append(normalized)
    return tuple(channels)


def normalize_notice_channel(channel: str) -> str | None:
    aliases = {
        "mailgun": "mailgun",
        "mail": "mailgun",
        "email": "mailgun",
        "wx": "wxpusher",
        "wxpusher": "wxpusher",
    }
    return aliases.get(channel.strip().lower())


def _unquote_dotenv_value(raw: str) -> str:
    if len(raw) < 2:
        return raw
    quote = raw[0]
    if quote not in {"'", '"'} or raw[-1] != quote:
        return raw
    value = raw[1:-1]
    if quote == '"':
        value = value.encode("utf-8").decode("unicode_escape")
    return value


def _bool_value(values: Mapping[str, str], name: str, default: bool) -> bool:
    return parse_bool(values.get(name), default=default)


def _int_value(
    values: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = values.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    return value


def _float_value(
    values: Mapping[str, str],
    name: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    raw = values.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number") from exc
    if value < minimum or value > maximum:
        raise ConfigError(f"{name} must be between {minimum:g} and {maximum:g}")
    return value


def _str_value(values: Mapping[str, str], name: str, default: str) -> str:
    value = _blank_to_none(values.get(name))
    return value if value is not None else default


def _path_or_none(raw: str | None) -> Path | None:
    value = _blank_to_none(raw)
    if value is None:
        return None
    return Path(value)


def _blank_to_none(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def _csv_values(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]
