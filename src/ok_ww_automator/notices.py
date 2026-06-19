"""Notice delivery for final runner results."""

from __future__ import annotations

from dataclasses import dataclass
import html
from importlib.resources import files
import re
from typing import Any, Mapping, Protocol

from .config import NoticeConfig
from .models import RunResult, SheetRunConfig, bool_label, safe_str, success_label

WXPUSHER_SIMPLE_PUSH_URL = "https://wxpusher.zjiecode.com/api/send/message/simple-push"
NO_NOTICE_STATUSES = {"running", ""}
STATUS_STYLES: dict[str, tuple[str, str]] = {
    "success": ("成功", "#22c55e"),
    "failure": ("失败", "#ef4444"),
    "skipped": ("跳过", "#9ca3af"),
    "needs review": ("需复查", "#f59e0b"),
    "running": ("运行中", "#3b82f6"),
}
PLACEHOLDER_PATTERN = re.compile(r"{{\s*([A-Za-z0-9_]+)\s*}}")


class NoticeError(RuntimeError):
    """Raised when a configured notice channel cannot be sent."""


class HttpResponse(Protocol):
    def raise_for_status(self) -> None: ...

    def json(self) -> Mapping[str, Any]: ...


class HttpSession(Protocol):
    def post(self, url: str, **kwargs: Any) -> HttpResponse: ...


class NoticeClient(Protocol):
    def notify(self, result: RunResult, sheet_config: SheetRunConfig) -> None: ...


@dataclass(frozen=True)
class NoticeMessage:
    subject: str
    text: str
    html: str


class NullNoticeClient:
    def notify(self, result: RunResult, sheet_config: SheetRunConfig) -> None:
        return


class CompositeNoticeClient:
    def __init__(self, clients: list[NoticeClient]) -> None:
        self.clients = clients

    def notify(self, result: RunResult, sheet_config: SheetRunConfig) -> None:
        if not should_notify(result):
            return
        errors = []
        for client in self.clients:
            try:
                client.notify(result, sheet_config)
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            raise NoticeError("; ".join(errors))


class MailgunNoticeClient:
    def __init__(self, config: NoticeConfig, *, session: HttpSession | None = None) -> None:
        config.require_channel_credentials("mailgun")
        self.config = config
        self.session = session or new_requests_session()

    def notify(self, result: RunResult, sheet_config: SheetRunConfig) -> None:
        message = build_notice_message(result, sheet_config, account_id=self.config.account_id)
        domain = self.config.mailgun_domain or ""
        response = self.session.post(
            f"https://api.mailgun.net/v3/{domain}/messages",
            auth=("api", self.config.mailgun_api_key),
            data={
                "from": f"OK-WW任务助手 <postmaster@{domain}>",
                "to": self.config.mailgun_recipient,
                "subject": message.subject,
                "text": message.text,
                "html": message.html,
            },
            timeout=15,
        )
        response.raise_for_status()


class WxPusherNoticeClient:
    def __init__(self, config: NoticeConfig, *, session: HttpSession | None = None) -> None:
        config.require_channel_credentials("wxpusher")
        self.config = config
        self.session = session or new_requests_session()

    def notify(self, result: RunResult, sheet_config: SheetRunConfig) -> None:
        message = build_notice_message(result, sheet_config, account_id=self.config.account_id)
        response = self.session.post(
            WXPUSHER_SIMPLE_PUSH_URL,
            json={
                "content": message.html,
                "summary": message.subject,
                "contentType": 2,
                "spt": self.config.wxpusher_spt,
            },
            timeout=15,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("code") != 1000:
            raise NoticeError(f"WxPusher send failed: {body}")


def notice_client_from_config(config: NoticeConfig) -> NoticeClient:
    if not config.enabled:
        return NullNoticeClient()
    clients: list[NoticeClient] = []
    for channel in config.channels:
        if channel == "mailgun":
            clients.append(MailgunNoticeClient(config))
        elif channel == "wxpusher":
            clients.append(WxPusherNoticeClient(config))
        else:
            raise NoticeError(f"Unsupported notice channel: {channel}")
    return CompositeNoticeClient(clients)


def should_notify(result: RunResult, *, skip_success: bool = False) -> bool:
    normalized_status = result.status.strip().lower()
    if normalized_status in NO_NOTICE_STATUSES:
        return False
    if skip_success and normalized_status == "success":
        return False
    return True


def build_notice_message(
    result: RunResult,
    sheet_config: SheetRunConfig,
    *,
    account_id: str | None = None,
) -> NoticeMessage:
    derived = result.derive()
    account_prefix = f"[{account_id}] " if account_id else ""
    task_label = "日常" if result.task_type == "daily" else "体力"
    subject = f"{account_prefix}{derived.end_time:%m-%d} 鸣潮{task_label}任务 · {status_label(result.status)}"
    variables = build_template_variables(result, sheet_config, account_prefix=account_prefix, derived=derived)
    lines = text_summary_lines(result, sheet_config, variables, task_label=task_label)
    text = "\n".join(lines)
    html_text = render_html_template(template_name_for(result), variables)
    return NoticeMessage(subject=subject, text=text, html=html_text)


def build_template_variables(
    result: RunResult,
    sheet_config: SheetRunConfig,
    *,
    account_prefix: str,
    derived,
) -> dict[str, Any]:
    task_label = "日常任务" if result.task_type == "daily" else "体力任务"
    label, color = status_info(result.status)
    decision = derived.decision
    error = derived.error
    variables: dict[str, Any] = {
        "title": f"{account_prefix}{task_label} · {label}",
        "status_color": color,
        "started_at": derived.started_at_text,
        "ended_at": derived.ended_at_text,
        "duration": derived.duration_text,
        "stamina_start": safe_str(result.stamina_start),
        "backup_start": safe_str(result.backup_stamina_start),
        "stamina_left": safe_str(result.stamina_left),
        "backup_stamina": safe_str(result.backup_stamina_left),
        "next_daily_stamina": derived.next_daily_stamina,
        "next_daily_backup_stamina": derived.next_daily_backup_stamina,
        "stamina_used": safe_str(result.stamina_used),
        "notes_display": display_block("x" if derived.notes_visible else ""),
        "decision_display": display_row(decision),
        "error_display": display_row(error),
        "decision": decision,
        "error": error,
        **farm_snapshot(sheet_config),
    }
    if result.task_type == "daily":
        daily_complete_label = ""
        if result.daily_points is not None:
            daily_complete_label = "是" if result.daily_points >= 100 else "否"
        variables.update(
            {
                "daily_points": safe_str(result.daily_points),
                "daily_complete_label": daily_complete_label,
                "sign_in_label": success_label(result.sign_in_success),
                "run_daily": bool_label(sheet_config.run_daily),
                "run_nightmare": bool_label(result.run_nightmare),
            }
        )
    else:
        variables.update({"run_stamina": bool_label(sheet_config.run_stamina)})
    return variables


def text_summary_lines(
    result: RunResult,
    sheet_config: SheetRunConfig,
    variables: Mapping[str, Any],
    *,
    task_label: str,
) -> list[str]:
    lines = [
        safe_str(variables.get("title", f"{task_label}任务报告")),
        f"开始: {safe_str(variables.get('started_at'))}",
        f"结束: {safe_str(variables.get('ended_at'))}",
        f"耗时: {safe_str(variables.get('duration'))}",
    ]
    if result.stamina_start is not None:
        lines.append(f"体力: {result.stamina_start} -> {safe_str(result.stamina_left)}")
    if result.backup_stamina_start is not None:
        lines.append(f"结晶单质: {result.backup_stamina_start} -> {safe_str(result.backup_stamina_left)}")
    if result.stamina_used is not None:
        lines.append(f"消耗: {result.stamina_used}")
    if result.daily_points is not None:
        lines.append(f"活跃度: {result.daily_points}")
    if result.sign_in_success is not None:
        lines.append(f"签到: {success_label(result.sign_in_success)}")
    if result.task_type == "daily":
        lines.append(f"梦魇: {bool_label(result.run_nightmare)}")
    lines.extend(farm_lines(sheet_config))
    if decision := safe_str(variables.get("decision")):
        lines.append(f"决策: {decision}")
    if error := safe_str(variables.get("error")):
        lines.append(f"错误: {error}")
    return lines


def render_html_template(template_name: str, variables: Mapping[str, Any]) -> str:
    template = files("ok_ww_automator").joinpath("notice_templates", template_name).read_text(encoding="utf-8")

    def replace(match: re.Match[str]) -> str:
        return html.escape(safe_str(variables.get(match.group(1))))

    return PLACEHOLDER_PATTERN.sub(replace, template)


def template_name_for(result: RunResult) -> str:
    return "daily_task.html" if result.task_type == "daily" else "stamina_task.html"


def status_info(status: str) -> tuple[str, str]:
    return STATUS_STYLES.get(status.strip().lower(), (status, "#3b82f6"))


def status_label(status: str) -> str:
    label, _ = status_info(status)
    return label


def display_block(value: str) -> str:
    return "block" if value else "none"


def display_row(value: str) -> str:
    return "table-row" if value else "none"


def farm_snapshot(sheet_config: SheetRunConfig) -> dict[str, str]:
    which = safe_str(sheet_config.which_to_farm).strip()
    if which == "无音区":
        detail1_label = "无音区"
        detail1_value = safe_str(sheet_config.tacet_name)
        detail2_label = "套装"
        detail2_value = " / ".join(value for value in [sheet_config.tacet_set1, sheet_config.tacet_set2] if value)
    elif which == "凝素领域":
        detail1_label = "凝素领域"
        if sheet_config.forgery_name and sheet_config.forgery_version:
            detail1_value = f"{sheet_config.forgery_name} ({sheet_config.forgery_version})"
        else:
            detail1_value = safe_str(sheet_config.forgery_name or sheet_config.forgery_version)
        detail2_label = "武器类型"
        detail2_value = safe_str(sheet_config.forgery_weapon_type)
    elif which == "模拟领域":
        detail1_label = "模拟领域"
        detail1_value = safe_str(sheet_config.simulation_material)
        detail2_label = ""
        detail2_value = ""
    else:
        detail1_label = "任务配置"
        detail1_value = ""
        detail2_label = ""
        detail2_value = ""
    return {
        "which_to_farm": which,
        "farm_detail1_label": detail1_label,
        "farm_detail1_value": detail1_value,
        "farm_detail2_label": detail2_label,
        "farm_detail2_value": detail2_value,
        "farm_detail2_row_display": display_row("x" if detail2_label and detail2_value else ""),
    }


def farm_lines(sheet_config: SheetRunConfig) -> list[str]:
    which = safe_str(sheet_config.which_to_farm)
    lines = [f"刷取: {which}"] if which else []
    if which == "无音区":
        if sheet_config.tacet_name:
            lines.append(f"无音区: {sheet_config.tacet_name}")
        sets = " / ".join(value for value in [sheet_config.tacet_set1, sheet_config.tacet_set2] if value)
        if sets:
            lines.append(f"套装: {sets}")
    elif which == "凝素领域":
        if sheet_config.forgery_name:
            lines.append(f"凝素领域: {sheet_config.forgery_name}")
        if sheet_config.forgery_weapon_type:
            lines.append(f"武器类型: {sheet_config.forgery_weapon_type}")
    elif which == "模拟领域" and sheet_config.simulation_material:
        lines.append(f"模拟领域: {sheet_config.simulation_material}")
    return lines


def new_requests_session() -> HttpSession:
    try:
        import requests
    except ImportError as exc:
        raise NoticeError("Install ok-ww-automator[notice] to send notices") from exc
    return requests.Session()
