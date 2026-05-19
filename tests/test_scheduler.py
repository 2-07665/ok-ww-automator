from pathlib import Path
import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ok_ww_automator.env_discovery import AccountEnv
from ok_ww_automator.scheduler import SchedulerJob, build_scheduler_plan, main, resolve_modes, run_job, run_jobs


class SchedulerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp_dir.name).resolve()
        self.env_dir = self.tmp / "env"
        self.env_dir.mkdir()
        (self.env_dir / "cn.env").touch()
        (self.env_dir / "global.env").touch()

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def test_resolve_modes(self) -> None:
        self.assertEqual(resolve_modes("daily"), ("daily",))
        self.assertEqual(resolve_modes("stamina"), ("stamina",))

    def test_build_scheduler_plan_uses_all_discovered_accounts(self) -> None:
        plan = build_scheduler_plan(
            project_root=self.tmp,
            env_dir=self.env_dir,
            selected_accounts=None,
            mode="daily",
            skip_update=False,
            ww_root=self.tmp / "ok-wuthering-waves",
        )

        self.assertEqual([account.account_id for account in plan.accounts], ["cn", "global"])
        self.assertEqual([(job.account.account_id, job.mode) for job in plan.jobs], [("cn", "daily"), ("global", "daily")])
        self.assertTrue(any("uv pip install" in command for command in plan.update_commands))

    def test_build_scheduler_plan_filters_accounts(self) -> None:
        plan = build_scheduler_plan(
            project_root=self.tmp,
            env_dir=self.env_dir,
            selected_accounts=["global"],
            mode="stamina",
            skip_update=True,
            ww_root=self.tmp / "ok-wuthering-waves",
        )

        self.assertEqual([account.account_id for account in plan.accounts], ["global"])
        self.assertEqual([(job.account.account_id, job.mode) for job in plan.jobs], [("global", "stamina")])
        self.assertEqual(plan.update_commands, ())

    def test_main_dry_run_returns_success(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            code = main(
                [
                    "--project-root",
                    str(self.tmp),
                    "--env-dir",
                    "env",
                    "--ww-root",
                    str(self.tmp / "ok-wuthering-waves"),
                    "--mode",
                    "daily",
                    "--dry-run",
                ]
            )

        self.assertEqual(code, 0)

    def test_main_stamina_non_dry_runs_stamina_dispatcher(self) -> None:
        with (
            contextlib.redirect_stdout(io.StringIO()),
            patch("ok_ww_automator.scheduler.run_commands") as run_commands,
            patch("ok_ww_automator.scheduler.run_mode") as run_mode,
        ):
            code = main(
                [
                    "--project-root",
                    str(self.tmp),
                    "--env-dir",
                    "env",
                    "--ww-root",
                    str(self.tmp / "ok-wuthering-waves"),
                    "--mode",
                    "stamina",
                    "--account",
                    "cn",
                    "--skip-update",
                ]
            )

        self.assertEqual(code, 0)
        run_commands.assert_not_called()
        self.assertEqual(run_mode.call_count, 1)
        self.assertEqual(run_mode.call_args.args[0], "stamina")

    def test_main_daily_non_dry_runs_daily_dispatcher(self) -> None:
        with (
            contextlib.redirect_stdout(io.StringIO()),
            patch("ok_ww_automator.scheduler.run_commands") as run_commands,
            patch("ok_ww_automator.scheduler.run_mode") as run_mode,
        ):
            code = main(
                [
                    "--project-root",
                    str(self.tmp),
                    "--env-dir",
                    "env",
                    "--ww-root",
                    str(self.tmp / "ok-wuthering-waves"),
                    "--mode",
                    "daily",
                    "--account",
                    "cn",
                    "--skip-update",
                ]
            )

        self.assertEqual(code, 0)
        run_commands.assert_not_called()
        self.assertEqual(run_mode.call_count, 1)
        self.assertEqual(run_mode.call_args.args[0], "daily")
        self.assertEqual(run_mode.call_args.args[1].app_config.env_path, self.env_dir / "cn.env")

    def test_main_multi_account_runs_each_job_in_subprocess(self) -> None:
        with (
            contextlib.redirect_stdout(io.StringIO()),
            patch("ok_ww_automator.scheduler.run_commands") as run_commands,
            patch("ok_ww_automator.scheduler.run_mode") as run_mode,
            patch("ok_ww_automator.scheduler.subprocess.run") as subprocess_run,
        ):
            code = main(
                [
                    "--project-root",
                    str(self.tmp),
                    "--env-dir",
                    "env",
                    "--ww-root",
                    str(self.tmp / "ok-wuthering-waves"),
                    "--mode",
                    "daily",
                    "--skip-update",
                ]
            )

        self.assertEqual(code, 0)
        run_commands.assert_not_called()
        run_mode.assert_not_called()
        self.assertEqual(subprocess_run.call_count, 2)
        first_command = subprocess_run.call_args_list[0].args[0]
        second_command = subprocess_run.call_args_list[1].args[0]
        self.assertIn("--account", first_command)
        self.assertEqual(first_command[first_command.index("--account") + 1], "cn")
        self.assertEqual(second_command[second_command.index("--account") + 1], "global")
        self.assertIn("--skip-update", first_command)
        self.assertEqual(subprocess_run.call_args_list[0].kwargs["env"]["ENV_FILE"], str(self.env_dir / "cn.env"))

    def test_run_job_raises_when_runner_returns_failure(self) -> None:
        job = SchedulerJob(account=AccountEnv("cn", self.env_dir / "cn.env"), mode="daily")

        with (
            patch("ok_ww_automator.scheduler.validate_job", return_value=object()),
            patch("ok_ww_automator.scheduler.run_mode") as run_mode,
        ):
            run_mode.return_value.status = "failure"
            run_mode.return_value.error = "boom"
            with self.assertRaisesRegex(RuntimeError, "cn daily task failed: boom"):
                run_job(job, project_root=self.tmp, ww_root=self.tmp / "ok-wuthering-waves")

    def test_run_jobs_continues_after_subprocess_failure_and_raises_summary(self) -> None:
        jobs = (
            SchedulerJob(account=AccountEnv("cn", self.env_dir / "cn.env"), mode="daily"),
            SchedulerJob(account=AccountEnv("global", self.env_dir / "global.env"), mode="daily"),
        )

        with patch("ok_ww_automator.scheduler.run_job_subprocess") as run_subprocess:
            run_subprocess.side_effect = [subprocess.CalledProcessError(7, ["cmd"]), None]
            with self.assertRaisesRegex(RuntimeError, "cn/daily: exited 7"):
                run_jobs(
                    jobs,
                    project_root=self.tmp,
                    env_dir=self.env_dir,
                    ww_root=self.tmp / "ok-wuthering-waves",
                    ww_remote="origin",
                    ww_branch="master",
                )

        self.assertEqual(run_subprocess.call_count, 2)


if __name__ == "__main__":
    unittest.main()
