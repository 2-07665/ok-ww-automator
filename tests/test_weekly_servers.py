import datetime as dt
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from ok_ww_automator.config import (
    AppConfig, ConfigError, GAME_SERVER_TIMEZONES, NoticeConfig, RetryConfig,
    WeeklyRunConfig, load_config,
)
from ok_ww_automator.game_clients import WeeklyGameOutcome
from ok_ww_automator.weekly import WeeklyRunner, week_start, weekly_notice_start


class WeeklyServersTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.config = AppConfig(
            self.root, self.root / "account.env", game_server="US",
            retry=RetryConfig(1, 0),
            notice=NoticeConfig(enabled=True, channels=("wxpusher",), wxpusher_spt="test"),
        )
        self.game = Mock()
        self.game.run_weekly.return_value = WeeklyGameOutcome(completed=True)
        self.prepare = Mock()
        notice_patch = patch("ok_ww_automator.weekly.WxPusherNoticeClient")
        self.notice = notice_patch.start().return_value
        self.addCleanup(notice_patch.stop)

    def run_at(self, stamp, config=None):
        current = dt.datetime.fromisoformat(stamp)
        return WeeklyRunner(config or self.config, self.game, clock=lambda: current,
                            prepare=self.prepare).run()

    def test_config_normalizes_and_validates_server_without_guessing_from_filename(self):
        for server in GAME_SERVER_TIMEZONES:
            config = load_config(project_root=self.root, env={"GAME_SERVER": f" {server.lower()} "})
            self.assertEqual(config.require_game_server(), server)
        for invalid in ("America/New_York", "UTC-5", "unknown"):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ConfigError, "GAME_SERVER"):
                load_config(project_root=self.root, env={"GAME_SERVER": invalid})
        profile = self.root / "US.env"
        profile.write_text("GAME_SERVER=CN\n", encoding="utf-8")
        self.assertEqual(load_config(project_root=self.root, env={}, env_file=profile).game_server, "CN")
        self.assertEqual(load_config(project_root=self.root, env={"GAME_SERVER": "US"},
                                     env_file=profile).game_server, "US")
        for missing in (None, "", "  "):
            env = {} if missing is None else {"GAME_SERVER": missing}
            config = load_config(project_root=self.root, env=env)
            # Nonweekly configuration can still load without a server.
            with self.assertRaisesRegex(ConfigError, "Missing GAME_SERVER"):
                self.run_at("2026-09-28T10:00:00+00:00", config)
        self.assertFalse((self.root / ".state").exists())
        self.prepare.assert_not_called()
        self.game.run_weekly.assert_not_called()

    def test_every_server_reset_boundary_and_notice_threshold(self):
        resets = {
            "CN": "2026-09-27T20:00:00+00:00", "ASIA": "2026-09-27T20:00:00+00:00",
            "SEA": "2026-09-27T20:00:00+00:00", "HMT": "2026-09-27T20:00:00+00:00",
            "US": "2026-09-28T09:00:00+00:00", "EU": "2026-09-28T03:00:00+00:00",
        }
        for server, value in resets.items():
            with self.subTest(server=server):
                reset = dt.datetime.fromisoformat(value)
                zone = GAME_SERVER_TIMEZONES[server]
                start = week_start(reset, zone)
                self.assertEqual(start, reset)
                self.assertEqual(start.date().isoformat(), "2026-09-28")
                self.assertEqual(week_start(reset - dt.timedelta(microseconds=1), zone),
                                 reset - dt.timedelta(days=7))
                self.assertEqual(week_start(reset + dt.timedelta(seconds=1), zone), reset)
                self.assertEqual(weekly_notice_start(start, 1), reset)
                self.assertEqual(weekly_notice_start(start, 6),
                                 dt.datetime(2026, 10, 3, tzinfo=zone))

    def test_us_sunday_success_does_not_skip_new_week_and_records_utc_completion(self):
        self.assertEqual(self.run_at("2026-09-27T17:00:00-04:00").status, "success")
        self.assertEqual(self.run_at("2026-09-28T04:59:59-04:00").status, "skipped")
        self.assertEqual(self.run_at("2026-09-28T05:00:00-04:00").status, "success")
        self.assertEqual(self.run_at("2026-09-28T17:00:00-04:00").status, "skipped")
        self.assertEqual(self.game.run_weekly.call_count, 2)
        with closing(sqlite3.connect(next((self.root / ".state" / "weekly").glob("*.sqlite3")))) as db:
            rows = db.execute("SELECT server, week, success, completed_at FROM weeks ORDER BY week").fetchall()
        self.assertEqual(rows, [
            ("US", "2026-09-21T09:00:00+00:00", 1, "2026-09-27T21:00:00+00:00"),
            ("US", "2026-09-28T09:00:00+00:00", 1, "2026-09-28T09:00:00+00:00"),
        ])

    def test_us_reset_is_fixed_in_utc_in_summer_and_winter(self):
        for local_reset in ("2026-09-28T05:00:00-04:00", "2026-12-07T04:00:00-05:00"):
            with self.subTest(local_reset=local_reset):
                reset = dt.datetime.fromisoformat(local_reset)
                self.assertEqual(week_start(reset, GAME_SERVER_TIMEZONES["US"]), reset)
                self.assertEqual(reset.astimezone(dt.timezone.utc).hour, 9)
                self.assertEqual(week_start(reset.astimezone(GAME_SERVER_TIMEZONES["CN"]),
                                            GAME_SERVER_TIMEZONES["US"]), reset)

    def test_run_days_use_server_calendar(self):
        config = replace(self.config, weekly_run=WeeklyRunConfig(run_days=(1,)))
        # Sunday 17:00 EDT is already Monday in CN, but still Sunday on US.
        self.assertEqual(self.run_at("2026-09-27T17:00:00-04:00", config).status, "failure")
        self.game.run_weekly.assert_not_called()
        self.assertEqual(self.run_at("2026-09-28T17:00:00-04:00", config).status, "success")

    def test_saturday_notices_on_daily_5pm_edt_triggers(self):
        self.game.run_weekly.return_value = WeeklyGameOutcome(task_error="failed")
        configs = [replace(self.config, game_server=server, env_path=self.root / f"{server}.env",
                           weekly_run=WeeklyRunConfig(notice_day=6)) for server in ("CN", "US")]
        for config in configs:
            self.run_at("2026-10-02T17:00:00-04:00", config)
        self.notice.notify.assert_called_once()
        friday_notice = self.notice.notify.call_args.args[0]
        self.assertIn("（CN）", friday_notice.decision)
        self.assertIn("2026-10-03T00:00:00+08:00", friday_notice.decision)
        for config in configs:
            self.run_at("2026-10-03T17:00:00-04:00", config)
        self.assertEqual(self.notice.notify.call_count, 2)
        saturday_notice = self.notice.notify.call_args.args[0]
        self.assertIn("（US）", saturday_notice.decision)
        self.assertIn("2026-10-03T00:00:00-05:00", saturday_notice.decision)

    def test_preparation_or_game_crossing_us_reset_never_credits_either_week(self):
        for phase in ("prepare", "game"):
            with self.subTest(phase=phase):
                config = replace(self.config, env_path=self.root / f"{phase}.env")
                current = dt.datetime.fromisoformat("2026-09-28T04:59:00-04:00")
                def cross_reset(*args, **kwargs):
                    nonlocal current
                    current += dt.timedelta(minutes=2)
                    return WeeklyGameOutcome(completed=True)
                self.prepare.reset_mock(side_effect=True)
                self.game.reset_mock(side_effect=True)
                if phase == "prepare":
                    self.prepare.side_effect = cross_reset
                else:
                    self.game.run_weekly.side_effect = cross_reset
                result = WeeklyRunner(config, self.game, clock=lambda: current, prepare=self.prepare).run()
                self.assertEqual(result.status, "failure")
                self.assertIn("US 服务器周一 04:00", result.error)
                if phase == "prepare":
                    self.game.run_weekly.assert_not_called()
                self.prepare.side_effect = None
                self.game.run_weekly.side_effect = None
                self.assertEqual(self.run_at("2026-09-28T05:02:00-04:00", config).status, "success")

    def test_same_profile_different_servers_do_not_share_success_or_pending_notices(self):
        # CN and ASIA have the same reset instant, but distinct completion state.
        for server in ("CN", "ASIA"):
            config = replace(self.config, game_server=server)
            self.assertEqual(self.run_at("2026-09-28T10:00:00+00:00", config).status, "success")
        us = self.config
        self.game.run_weekly.return_value = WeeklyGameOutcome(task_error="failed")
        self.run_at("2026-09-28T10:00:00+00:00", us)
        self.game.run_weekly.return_value = WeeklyGameOutcome(completed=True)
        self.run_at("2026-10-05T10:00:00+00:00", replace(self.config, game_server="CN"))
        self.notice.notify.assert_not_called()
        self.run_at("2026-10-05T10:00:00+00:00", us)
        self.notice.notify.assert_called_once()
        self.assertIn("2026-09-28", self.notice.notify.call_args.args[0].decision)
        self.assertIn("（US）", self.notice.notify.call_args.args[0].decision)
