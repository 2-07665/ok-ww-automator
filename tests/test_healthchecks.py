import datetime as dt
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ok_ww_automator.config import HealthchecksConfig
from ok_ww_automator.healthchecks import (
    HealthchecksMonitor,
    NullHealthcheckMonitor,
    healthcheck_monitor_from_config,
    is_healthy_completion,
)
from ok_ww_automator.models import RunResult
from ok_ww_automator.time_utils import BEIJING_TZ


class FakeResponse:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeOpener:
    def __init__(self) -> None:
        self.calls = []
        self.responses = []

    def __call__(self, request, *, timeout):
        response = FakeResponse()
        self.calls.append((request.full_url, request.get_method(), timeout))
        self.responses.append(response)
        return response


class HealthchecksTest(unittest.TestCase):
    def test_monitor_pings_start_and_success_with_run_id(self) -> None:
        opener = FakeOpener()
        monitor = HealthchecksMonitor(
            "123e4567-e89b-12d3-a456-426614174000",
            opener=opener,
            run_id="123e4567-e89b-12d3-a456-426614174999",
        )
        base = dt.datetime(2026, 5, 16, 5, 0, tzinfo=BEIJING_TZ)
        result = RunResult("daily", base, base, "success")

        monitor.start(result)
        monitor.complete(result)

        self.assertEqual(
            opener.calls,
            [
                (
                    "https://hc-ping.com/123e4567-e89b-12d3-a456-426614174000/start"
                    "?rid=123e4567-e89b-12d3-a456-426614174999",
                    "GET",
                    10.0,
                ),
                (
                    "https://hc-ping.com/123e4567-e89b-12d3-a456-426614174000"
                    "?rid=123e4567-e89b-12d3-a456-426614174999",
                    "GET",
                    10.0,
                ),
            ],
        )
        self.assertTrue(all(response.closed for response in opener.responses))

    def test_monitor_pings_failure_for_needs_review(self) -> None:
        opener = FakeOpener()
        monitor = HealthchecksMonitor(
            "123e4567-e89b-12d3-a456-426614174000",
            opener=opener,
            run_id="123e4567-e89b-12d3-a456-426614174999",
        )
        base = dt.datetime(2026, 5, 16, 5, 0, tzinfo=BEIJING_TZ)

        monitor.complete(RunResult("daily", base, base, "needs review"))

        self.assertEqual(
            opener.calls[0][0],
            "https://hc-ping.com/123e4567-e89b-12d3-a456-426614174000/fail"
            "?rid=123e4567-e89b-12d3-a456-426614174999",
        )

    def test_skipped_is_healthy_completion(self) -> None:
        base = dt.datetime(2026, 5, 16, 5, 0, tzinfo=BEIJING_TZ)

        self.assertTrue(is_healthy_completion(RunResult("stamina", base, base, "skipped")))
        self.assertFalse(is_healthy_completion(RunResult("stamina", base, base, "failure")))

    def test_factory_returns_null_when_disabled(self) -> None:
        monitor = healthcheck_monitor_from_config(HealthchecksConfig(enabled=False), "daily")

        self.assertIsInstance(monitor, NullHealthcheckMonitor)


if __name__ == "__main__":
    unittest.main()
