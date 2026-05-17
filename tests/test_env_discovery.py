from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ok_ww_automator.env_discovery import account_id_from_env_path, discover_account_envs, select_accounts


class EnvDiscoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp_dir.name).resolve()

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def test_account_id_from_env_path(self) -> None:
        self.assertEqual(account_id_from_env_path(Path(".env")), "default")
        self.assertEqual(account_id_from_env_path(Path("cn.env")), "cn")

    def test_discover_account_envs_ignores_example_only(self) -> None:
        env_dir = self.tmp / "env"
        env_dir.mkdir()
        (env_dir / ".env.example").touch()
        (env_dir / ".env").touch()
        (env_dir / "cn.env").touch()
        (env_dir / "global.env").touch()

        accounts = discover_account_envs(env_dir)

        self.assertEqual([account.account_id for account in accounts], ["default", "cn", "global"])

    def test_select_accounts_preserves_requested_order(self) -> None:
        env_dir = self.tmp / "env"
        env_dir.mkdir()
        (env_dir / "cn.env").touch()
        (env_dir / "global.env").touch()
        accounts = discover_account_envs(env_dir)

        selected = select_accounts(accounts, ["global", "cn"])

        self.assertEqual([account.account_id for account in selected], ["global", "cn"])

    def test_select_accounts_rejects_unknown_account(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown account env"):
            select_accounts([], ["cn"])


if __name__ == "__main__":
    unittest.main()
