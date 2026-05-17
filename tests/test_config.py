from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ok_ww_automator.config import (
    ConfigError,
    load_config,
    parse_bool,
    parse_notice_channels,
    read_dotenv,
    resolve_env_path,
)


class ConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp_dir.name).resolve()

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def test_load_config_uses_safe_defaults(self) -> None:
        config = load_config(env={}, project_root=self.tmp)

        self.assertEqual(config.project_root, self.tmp)
        self.assertEqual(config.env_path, self.tmp / "env" / ".env")
        self.assertIsNone(config.game_exe_path)
        self.assertEqual(config.daily_run_time.hour, 5)
        self.assertEqual(config.daily_run_time.minute, 0)
        self.assertEqual(config.google_sheets.config_sheet, "Config")
        self.assertEqual(config.google_sheets.daily_runs_sheet, "DailyRuns")
        self.assertEqual(config.google_sheets.stamina_runs_sheet, "StaminaRuns")
        self.assertEqual(config.google_sheets.fast_farm_runs_sheet, "5to1")
        self.assertFalse(config.waves_api.enabled)
        self.assertFalse(config.notice.enabled)
        self.assertEqual(config.notice.channels, ())

    def test_load_config_reads_dotenv_and_keeps_env_override(self) -> None:
        env_dir = self.tmp / "env"
        env_dir.mkdir()
        dotenv = env_dir / ".env"
        dotenv.write_text(
            "\n".join(
                [
                    "GAME_EXE_PATH='D:\\Games\\Wuthering Waves\\Wuthering Waves.exe'",
                    "DAILY_HOUR=6",
                    "DAILY_MINUTE=30",
                    "RETRY_MAX_ATTEMPTS=3",
                    "RETRY_DELAY_SECONDS=1.5",
                    "WAVES_API_ENABLED=true",
                    "NOTICE_CHANNEL=mailgun,wx,mailgun",
                    "NOTICE_ACCOUNT_ID=global",
                    "SHEET_NAME_FASTFARM=FastFarmRuns",
                ]
            ),
            encoding="utf-8",
        )

        config = load_config(env={"DAILY_HOUR": "7"}, project_root=self.tmp)

        self.assertEqual(config.game_exe_path, Path("D:\\Games\\Wuthering Waves\\Wuthering Waves.exe"))
        self.assertEqual(config.daily_run_time.hour, 7)
        self.assertEqual(config.daily_run_time.minute, 30)
        self.assertEqual(config.retry.max_attempts, 3)
        self.assertEqual(config.retry.delay_seconds, 1.5)
        self.assertTrue(config.waves_api.enabled)
        self.assertEqual(config.notice.channels, ("mailgun", "wxpusher"))
        self.assertEqual(config.notice.account_id, "global")
        self.assertEqual(config.google_sheets.fast_farm_runs_sheet, "FastFarmRuns")

    def test_env_file_resolution_prefers_env_folder_for_bare_filename(self) -> None:
        env_dir = self.tmp / "env"
        env_dir.mkdir()
        env_file = env_dir / "account.env"
        env_file.touch()

        resolved = resolve_env_path(self.tmp, {"ENV_FILE": "account.env"})

        self.assertEqual(resolved, env_file)

    def test_env_file_resolution_supports_windows_style_paths(self) -> None:
        resolved = resolve_env_path(self.tmp, {"ENV_FILE": "env\\account.env"})

        self.assertEqual(resolved, self.tmp / "env" / "account.env")

    def test_parse_bool_accepts_legacy_values(self) -> None:
        self.assertTrue(parse_bool("yes"))
        self.assertTrue(parse_bool("是"))
        self.assertFalse(parse_bool("off", default=True))
        self.assertTrue(parse_bool("", default=True))

    def test_parse_bool_rejects_unknown_values(self) -> None:
        with self.assertRaisesRegex(ConfigError, "Invalid boolean"):
            parse_bool("sometimes")

    def test_parse_notice_channels_normalizes_and_deduplicates(self) -> None:
        self.assertEqual(parse_notice_channels("email, wx, mailgun"), ("mailgun", "wxpusher"))

    def test_parse_notice_channels_rejects_unknown_values(self) -> None:
        with self.assertRaisesRegex(ConfigError, "Unsupported notice channel"):
            parse_notice_channels("sms")

    def test_read_dotenv_supports_export_and_quotes(self) -> None:
        dotenv = self.tmp / ".env"
        dotenv.write_text(
            "\n".join(
                [
                    "# ignored",
                    "export PLAIN=value",
                    "SINGLE='quoted value'",
                    'DOUBLE="line\\nvalue"',
                ]
            ),
            encoding="utf-8",
        )

        self.assertEqual(
            read_dotenv(dotenv),
            {
                "PLAIN": "value",
                "SINGLE": "quoted value",
                "DOUBLE": "line\nvalue",
            },
        )

    def test_require_methods_fail_lazily(self) -> None:
        config = load_config(env={}, project_root=self.tmp)

        with self.assertRaisesRegex(ConfigError, "GAME_EXE_PATH"):
            config.require_game_exe_path()
        with self.assertRaisesRegex(ConfigError, "GOOGLE_SHEET_ID"):
            config.google_sheets.require_credentials()
        with self.assertRaisesRegex(ConfigError, "WAVES_ROLE_ID"):
            config.waves_api.require_credentials()
        with self.assertRaisesRegex(ConfigError, "MAILGUN_API_KEY"):
            config.notice.require_channel_credentials("mailgun")


if __name__ == "__main__":
    unittest.main()
