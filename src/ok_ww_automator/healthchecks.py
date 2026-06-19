"""Healthchecks.io ping integration for scheduled runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from .config import HealthchecksConfig
from .models import RunResult

HEALTHCHECKS_PING_BASE_URL = "https://hc-ping.com"
HEALTHY_COMPLETION_STATUSES = {"success", "skipped"}


class HealthcheckMonitor(Protocol):
    def start(self, result: RunResult) -> None: ...

    def complete(self, result: RunResult) -> None: ...


class UrlOpener(Protocol):
    def __call__(self, request: Request, *, timeout: float) -> object: ...


class NullHealthcheckMonitor:
    def start(self, result: RunResult) -> None:
        return

    def complete(self, result: RunResult) -> None:
        return


@dataclass
class HealthchecksMonitor:
    check_uuid: str
    opener: UrlOpener = urlopen
    timeout: float = 10.0
    base_url: str = HEALTHCHECKS_PING_BASE_URL
    run_id: str = field(default_factory=lambda: str(uuid4()))

    def start(self, result: RunResult) -> None:
        self._ping("start")

    def complete(self, result: RunResult) -> None:
        signal = None if is_healthy_completion(result) else "fail"
        self._ping(signal)

    def _ping(self, signal: str | None) -> None:
        request = Request(self._url(signal), method="GET")
        response = self.opener(request, timeout=self.timeout)
        close = getattr(response, "close", None)
        if callable(close):
            close()

    def _url(self, signal: str | None) -> str:
        suffix = f"/{signal}" if signal else ""
        return f"{self.base_url.rstrip('/')}/{self.check_uuid}{suffix}?{urlencode({'rid': self.run_id})}"


def healthcheck_monitor_from_config(config: HealthchecksConfig, mode: str) -> HealthcheckMonitor:
    if not config.enabled:
        return NullHealthcheckMonitor()
    return HealthchecksMonitor(config.uuid_for_mode(mode))


def is_healthy_completion(result: RunResult) -> bool:
    return result.status.strip().lower() in HEALTHY_COMPLETION_STATUSES
