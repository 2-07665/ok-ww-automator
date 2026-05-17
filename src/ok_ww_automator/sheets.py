"""Google Sheets config and run-result storage."""

from __future__ import annotations

import argparse
import base64
from dataclasses import asdict
import json
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any, Protocol

from .config import GoogleSheetsConfig, load_config, parse_bool
from .models import FastFarmResult, RunResult, SheetRunConfig

VALUE_INPUT_USER_ENTERED = "USER_ENTERED"
DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class SheetsError(RuntimeError):
    """Raised when Sheets data cannot be read, parsed, or written."""


class Worksheet(Protocol):
    def get_all_values(self) -> list[list[Any]]: ...

    def update(self, values: list[list[Any]], range_name: str, **kwargs: Any) -> Any: ...

    def append_row(self, values: list[Any], **kwargs: Any) -> Any: ...


class Spreadsheet(Protocol):
    def worksheet(self, title: str) -> Worksheet: ...


@dataclass(frozen=True)
class ConfigEntry:
    label: str
    value: str
    row: int
    label_col: int
    value_col: int

    @property
    def value_a1(self) -> str:
        return f"{column_to_a1(self.value_col)}{self.row}"


@dataclass(frozen=True)
class ParsedConfigSheet:
    entries: dict[str, ConfigEntry]

    def get(self, label: str) -> str | None:
        entry = self.entries.get(label)
        return entry.value if entry is not None else None

    def require_entry(self, label: str) -> ConfigEntry:
        entry = self.entries.get(label)
        if entry is None:
            raise SheetsError(f"Config label not found: {label}")
        return entry


@dataclass(frozen=True)
class ConfigField:
    field_name: str
    label: str
    value_type: type


CONFIG_FIELDS: tuple[ConfigField, ...] = (
    ConfigField("run_daily", "日常任务", bool),
    ConfigField("skip_daily_once", "日常跳过一次", bool),
    ConfigField("shutdown_after_daily", "日常后关机", bool),
    ConfigField("run_stamina", "体力任务", bool),
    ConfigField("skip_stamina_once", "体力跳过一次", bool),
    ConfigField("shutdown_after_stamina", "体力后关机", bool),
    ConfigField("which_to_farm", "刷什么", str),
    ConfigField("tacet_name", "无音区设置", str),
    ConfigField("tacet_serial", "无音区序号", int),
    ConfigField("tacet_set1", "无音区套装1", str),
    ConfigField("tacet_set2", "无音区套装2", str),
    ConfigField("forgery_name", "凝素领域设置", str),
    ConfigField("forgery_serial", "凝素领域序号", int),
    ConfigField("forgery_weapon_type", "凝素领域武器类型", str),
    ConfigField("forgery_version", "凝素领域版本", str),
    ConfigField("simulation_material", "模拟领域设置", str),
    ConfigField("run_nightmare", "梦魇祓除", bool),
)

LABEL_BY_FIELD = {field.field_name: field.label for field in CONFIG_FIELDS}


class ConfigSheetParser:
    """Parse pairwise label/value config sheets."""

    def parse(self, rows: list[list[Any]]) -> ParsedConfigSheet:
        entries: dict[str, ConfigEntry] = {}
        for row_index, row in enumerate(rows, start=1):
            for label_col in range(1, len(row) + 1, 2):
                label = _cell_text(row[label_col - 1])
                if not label:
                    continue
                value_col = label_col + 1
                value = _cell_text(row[value_col - 1]) if value_col <= len(row) else ""
                if label in entries:
                    raise SheetsError(f"Duplicate config label: {label}")
                entries[label] = ConfigEntry(
                    label=label,
                    value=value,
                    row=row_index,
                    label_col=label_col,
                    value_col=value_col,
                )
        return ParsedConfigSheet(entries)

    def to_run_config(self, parsed: ParsedConfigSheet) -> SheetRunConfig:
        values: dict[str, Any] = {}
        defaults = SheetRunConfig()

        for field in CONFIG_FIELDS:
            raw_value = parsed.get(field.label)
            if raw_value is None or raw_value.strip() == "":
                continue
            values[field.field_name] = _parse_field_value(field, raw_value)

        return SheetRunConfig(
            run_daily=values.get("run_daily", defaults.run_daily),
            skip_daily_once=values.get("skip_daily_once", defaults.skip_daily_once),
            shutdown_after_daily=values.get("shutdown_after_daily", defaults.shutdown_after_daily),
            run_nightmare=values.get("run_nightmare", defaults.run_nightmare),
            run_stamina=values.get("run_stamina", defaults.run_stamina),
            skip_stamina_once=values.get("skip_stamina_once", defaults.skip_stamina_once),
            shutdown_after_stamina=values.get("shutdown_after_stamina", defaults.shutdown_after_stamina),
            which_to_farm=values.get("which_to_farm", defaults.which_to_farm),
            tacet_serial=values.get("tacet_serial", defaults.tacet_serial),
            tacet_name=values.get("tacet_name", defaults.tacet_name),
            tacet_set1=values.get("tacet_set1", defaults.tacet_set1),
            tacet_set2=values.get("tacet_set2", defaults.tacet_set2),
            forgery_serial=values.get("forgery_serial", defaults.forgery_serial),
            forgery_name=values.get("forgery_name", defaults.forgery_name),
            forgery_weapon_type=values.get("forgery_weapon_type", defaults.forgery_weapon_type),
            forgery_version=values.get("forgery_version", defaults.forgery_version),
            simulation_material=values.get("simulation_material", defaults.simulation_material),
        )


class GoogleSheetsStore:
    def __init__(self, config: GoogleSheetsConfig, *, spreadsheet: Spreadsheet | None = None):
        self.config = config
        self._spreadsheet = spreadsheet
        self.parser = ConfigSheetParser()

    @classmethod
    def from_config(cls, config: GoogleSheetsConfig) -> "GoogleSheetsStore":
        config.require_credentials()
        return cls(config)

    @property
    def spreadsheet(self) -> Spreadsheet:
        if self._spreadsheet is None:
            self._spreadsheet = _open_spreadsheet(self.config)
        return self._spreadsheet

    def fetch_run_config(self) -> SheetRunConfig:
        parsed = self.fetch_parsed_config()
        return self.parser.to_run_config(parsed)

    def fetch_run_config_or_default(self) -> tuple[SheetRunConfig, str | None]:
        try:
            return self.fetch_run_config(), None
        except Exception as exc:
            return SheetRunConfig(), str(exc)

    def fetch_parsed_config(self) -> ParsedConfigSheet:
        rows = self._worksheet(self.config.config_sheet).get_all_values()
        return self.parser.parse(rows)

    def clear_skip_once(self, task_type: str) -> bool:
        normalized = task_type.strip().lower()
        if normalized == "daily":
            label = LABEL_BY_FIELD["skip_daily_once"]
        elif normalized == "stamina":
            label = LABEL_BY_FIELD["skip_stamina_once"]
        else:
            raise SheetsError(f"Unsupported task type for skip-once clearing: {task_type}")

        parsed = self.fetch_parsed_config()
        entry = parsed.require_entry(label)
        self._worksheet(self.config.config_sheet).update(
            [["FALSE"]],
            entry.value_a1,
            value_input_option=VALUE_INPUT_USER_ENTERED,
        )
        return True

    def append_daily_result(self, result: RunResult) -> None:
        self._worksheet(self.config.daily_runs_sheet).append_row(
            result.as_daily_row(),
            value_input_option=VALUE_INPUT_USER_ENTERED,
        )

    def append_stamina_result(self, result: RunResult) -> None:
        self._worksheet(self.config.stamina_runs_sheet).append_row(
            result.as_stamina_row(),
            value_input_option=VALUE_INPUT_USER_ENTERED,
        )

    def append_fast_farm_result(self, result: FastFarmResult) -> None:
        self._worksheet(self.config.fast_farm_runs_sheet).append_row(
            result.as_row(),
            value_input_option=VALUE_INPUT_USER_ENTERED,
        )

    def _worksheet(self, title: str) -> Worksheet:
        try:
            return self.spreadsheet.worksheet(title)
        except Exception as exc:
            raise SheetsError(f"Unable to open worksheet {title!r}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        project_root = Path(args.project_root).resolve() if args.project_root else DEFAULT_PROJECT_ROOT
        app_config = load_config(project_root=project_root, env_file=args.env_file)
        store = GoogleSheetsStore.from_config(app_config.google_sheets)
        parsed = store.fetch_parsed_config()
        run_config = store.parser.to_run_config(parsed)
        print(json.dumps(asdict(run_config), ensure_ascii=False, indent=2))
        if args.show_cells:
            print("\nConfig cells:")
            for label in sorted(parsed.entries):
                entry = parsed.entries[label]
                print(f"{label}: {entry.value!r} ({entry.value_a1})")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect Google Sheets configuration.")
    parser.add_argument("--project-root", default=None, help="Automator project root. Defaults to this package checkout.")
    parser.add_argument("--env-file", default=None, help="Env file path or name, such as cn.env.")
    parser.add_argument("--show-cells", action="store_true", help="Also print discovered label value cells.")
    return parser.parse_args(argv)


def column_to_a1(column: int) -> str:
    if column <= 0:
        raise ValueError("column must be positive")
    letters = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _parse_field_value(field: ConfigField, raw_value: str) -> Any:
    try:
        if field.value_type is bool:
            return parse_bool(raw_value)
        if field.value_type is int:
            return int(raw_value)
        return raw_value.strip()
    except Exception as exc:
        raise SheetsError(f"Invalid value for {field.label}: {raw_value!r}") from exc


def _open_spreadsheet(config: GoogleSheetsConfig) -> Spreadsheet:
    config.require_credentials()
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as exc:
        raise SheetsError("Install ok-ww-automator[sheets] to use Google Sheets") from exc

    info = json.loads(base64.b64decode(config.service_account_json_base64 or "").decode("utf-8"))
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials = Credentials.from_service_account_info(info, scopes=scopes)
    client = gspread.authorize(credentials)
    return client.open_by_key(config.spreadsheet_id)


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


if __name__ == "__main__":
    raise SystemExit(main())
