from pathlib import Path
import json
import subprocess
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ok_ww_automator.config import AppConfig
from ok_ww_automator.models import SheetRunConfig
from ok_ww_automator.processes import run_with_timeout
from ok_ww_automator.game_clients import (
    AUTO_FARM_NIGHTMARE_NEST,
    DAILY_ADDITIONAL_TASKS,
    NIGHTMARE_FARM_SELECTION,
    NIGHTMARE_PURIFICATION,
    OkStaminaGameClient,
    OkWeeklyGameClient,
    SubprocessDailyGameClient,
    SubprocessStaminaGameClient,
    SubprocessWeeklyGameClient,
    WINDOWS_ACCESS_VIOLATION_EXIT_CODE,
    apply_daily_task_config,
    normalize_daily_task_error,
    read_live_daily_points,
    simulation_material_value,
    stamina_burn_unit,
)


class FakeDailyTask:
    def __init__(self) -> None:
        self.config = {}
        self.support_tasks = ["Tacet", "Forgery", "Simulation"]


class FakeNightmareTask:
    def __init__(self) -> None:
        self.config = {}


class FakeDailyPointsTask:
    def __init__(self, points=0, *, open_exc: Exception | None = None) -> None:
        if isinstance(points, list):
            self.points_by_attempt = points.copy()
        else:
            self.points_by_attempt = [points]
        self.open_exc = open_exc
        self.current_points = 0
        self.open_count = 0
        self.ensure_count = 0

    def ensure_main(self, **kwargs) -> None:
        self.ensure_count += 1

    def open_daily(self) -> None:
        self.open_count += 1
        if self.open_exc is not None:
            raise self.open_exc
        if self.points_by_attempt:
            self.current_points = self.points_by_attempt.pop(0)

    def info_get(self, key, default=None):
        if key == "total daily points":
            return self.current_points
        return default


class FakeDeviceManager:
    def __init__(self) -> None:
        self.stop_count = 0

    def stop_hwnd(self) -> None:
        self.stop_count += 1


class FakeOkRuntime:
    def __init__(self) -> None:
        self.device_manager = FakeDeviceManager()
        self.quit_count = 0

    def quit(self) -> None:
        self.quit_count += 1


class RaisingDeviceManager(FakeDeviceManager):
    def stop_hwnd(self) -> None:
        super().stop_hwnd()
        raise RuntimeError("stop failed")


class RaisingOkRuntime(FakeOkRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.device_manager = RaisingDeviceManager()

    def quit(self) -> None:
        super().quit()
        raise RuntimeError("quit failed")


class FakeLauncherOptions:
    ww_root = Path("/")
    game_exe_path = None


class FakeLauncher:
    def __init__(self):
        self.options = FakeLauncherOptions()
        self.start_count = 0

    def start_ok_and_game(self):
        self.start_count += 1
        return FakeOkRuntime()


class GameClientsTest(unittest.TestCase):
    def test_weekly_completion_info_overrides_errors_only_with_exact_marker(self):
        garden_module = ModuleType("src.task.GardenTask")
        garden_module.GardenTask = type("GardenTask", (), {})
        cases = [
            ("乐园任务完成, 已达到上限", "optional reward failed", True),
            ("乐园任务完成, 已达到上限", TimeoutError("executor timeout"), True),
            ("乐园任务完成, 已达到上限", "", True),
            ("garden running", "", True),
            ("garden running", "garden failed", False),
            ("尚未完成", "garden failed", False),
            (None, "garden failed", False),
            (None, TimeoutError("executor timeout"), None),
        ]
        for log, error, expected in cases:
            with self.subTest(log=log, error=error):
                task = Mock()
                task.info_get.side_effect = {"Log": log}.get
                runtime = Mock()
                runtime.task_executor.get_task_by_class.return_value = task
                launcher = Mock()
                launcher.start_ok_and_game.return_value = runtime
                with (
                    patch.dict(sys.modules, {"src.task.GardenTask": garden_module}),
                    patch("ok_ww_automator.game_clients.ww_runtime_context"),
                    patch("ok_ww_automator.game_clients.run_onetime_task") as run,
                    patch("ok_ww_automator.game_clients.close_ok_runtime") as close,
                    patch("ok_ww_automator.game_clients.kill_game_processes") as kill,
                ):
                    if isinstance(error, Exception):
                        run.side_effect = error
                    else:
                        run.return_value = error
                    if expected is None:
                        with self.assertRaises(TimeoutError):
                            OkWeeklyGameClient(launcher).run_weekly()
                    else:
                        outcome = OkWeeklyGameClient(launcher).run_weekly()
                        self.assertEqual(outcome.completed, expected)
                        self.assertEqual(outcome.task_error, str(error) if error else None)
                    close.assert_called_once_with(runtime)
                    kill.assert_called_once()

    def test_battle_pass_ended_is_not_a_daily_task_error(self) -> None:
        self.assertIsNone(
            normalize_daily_task_error("Daily Task: can not battle pass, maybe ended")
        )

    def test_other_daily_task_errors_are_preserved(self) -> None:
        self.assertEqual(
            normalize_daily_task_error("Daily Task: NightmareNestTask Failed"),
            "Daily Task: NightmareNestTask Failed",
        )

    def test_apply_daily_task_config_maps_sheet_values(self) -> None:
        task = FakeDailyTask()
        nightmare_task = FakeNightmareTask()
        config = SheetRunConfig(
            which_to_farm="凝素领域",
            tacet_serial=3,
            forgery_serial=2,
            simulation_material="武器经验",
            run_nightmare=True,
            farm_nightmare_purification=True,
            farm_tacet_discord_nest=False,
        )

        apply_daily_task_config(config, task, nightmare_task)

        self.assertEqual(task.config["Which to Farm"], "Forgery")
        self.assertEqual(task.config["Which Tacet Suppression to Farm"], 3)
        self.assertEqual(task.config["Which Forgery Challenge to Farm"], 2)
        self.assertEqual(task.config["Material Selection"], "Weapon EXP")
        self.assertTrue(task.config["Farm Nightmare Nest for Daily Echo"])
        self.assertEqual(task.config[DAILY_ADDITIONAL_TASKS], [AUTO_FARM_NIGHTMARE_NEST])
        self.assertNotIn("Check Weekly Garden", task.config[DAILY_ADDITIONAL_TASKS])
        self.assertEqual(nightmare_task.config[NIGHTMARE_FARM_SELECTION], [NIGHTMARE_PURIFICATION])

    def test_apply_daily_task_config_disables_all_additional_tasks(self) -> None:
        task = FakeDailyTask()
        nightmare_task = FakeNightmareTask()

        apply_daily_task_config(SheetRunConfig(run_nightmare=False), task, nightmare_task)

        self.assertEqual(task.config[DAILY_ADDITIONAL_TASKS], [])

    def test_apply_daily_task_config_treats_enabled_nightmare_without_targets_as_disabled(self) -> None:
        task = FakeDailyTask()
        nightmare_task = FakeNightmareTask()
        config = SheetRunConfig(
            run_nightmare=True,
            farm_nightmare_purification=False,
            farm_tacet_discord_nest=False,
        )

        apply_daily_task_config(config, task, nightmare_task)

        self.assertEqual(task.config[DAILY_ADDITIONAL_TASKS], [])
        self.assertFalse(task.config["Farm Nightmare Nest for Daily Echo"])
        self.assertEqual(nightmare_task.config[NIGHTMARE_FARM_SELECTION], [])

    def test_apply_daily_task_config_disables_daily_echo_nightmare_without_targets(self) -> None:
        task = FakeDailyTask()
        nightmare_task = FakeNightmareTask()
        config = SheetRunConfig(
            run_nightmare=False,
            farm_nightmare_purification=False,
            farm_tacet_discord_nest=False,
        )

        apply_daily_task_config(config, task, nightmare_task)

        self.assertFalse(task.config["Farm Nightmare Nest for Daily Echo"])
        self.assertEqual(nightmare_task.config[NIGHTMARE_FARM_SELECTION], [])

    def test_unknown_simulation_material_defaults_to_shell_credit(self) -> None:
        self.assertEqual(simulation_material_value("unknown"), "Shell Credit")

    def test_stamina_burn_unit_depends_on_farm_type(self) -> None:
        self.assertEqual(stamina_burn_unit(SheetRunConfig(which_to_farm="无音区")), 60)
        self.assertEqual(stamina_burn_unit(SheetRunConfig(which_to_farm="凝素领域")), 40)

    def test_read_live_daily_points_returns_first_reading(self) -> None:
        task = FakeDailyPointsTask([0, 100])

        points = read_live_daily_points(task, retries=3, retry_sleep=0)

        self.assertEqual(points, 0)
        self.assertEqual(task.open_count, 1)

    def test_read_live_daily_points_retries_until_first_valid_reading(self) -> None:
        task = FakeDailyPointsTask(["bad", 80, 100])

        points = read_live_daily_points(task, retries=3, retry_sleep=0)

        self.assertEqual(points, 80)
        self.assertEqual(task.open_count, 2)

    def test_read_live_daily_points_returns_none_when_all_reads_fail(self) -> None:
        task = FakeDailyPointsTask(open_exc=RuntimeError("daily page failed"))

        points = read_live_daily_points(task, retries=3, retry_sleep=0)

        self.assertIsNone(points)
        self.assertEqual(task.open_count, 3)


class OkStaminaGameClientTest(unittest.TestCase):
    def test_close_stops_game(self) -> None:
        client = OkStaminaGameClient(launcher=FakeLauncher())
        ok = FakeOkRuntime()
        client.ok = ok

        client.close(SheetRunConfig())

        self.assertEqual(ok.device_manager.stop_count, 1)
        self.assertEqual(ok.quit_count, 1)

    def test_close_resets_cached_runtime(self) -> None:
        client = OkStaminaGameClient(launcher=FakeLauncher())
        ok = FakeOkRuntime()
        client.ok = ok

        client.close(SheetRunConfig())

        self.assertIsNone(client.ok)
        self.assertIsNone(client.stamina_task)

    def test_close_does_not_kill_processes_when_game_was_never_touched(self) -> None:
        client = OkStaminaGameClient(launcher=FakeLauncher())

        with patch("ok_ww_automator.game_clients.kill_game_processes") as kill_processes:
            client.close(SheetRunConfig())

        kill_processes.assert_not_called()

    def test_close_kills_processes_after_launch_attempt(self) -> None:
        client = OkStaminaGameClient(launcher=FakeLauncher())
        client.launch_attempted = True

        with patch("ok_ww_automator.game_clients.kill_game_processes") as kill_processes:
            client.close(SheetRunConfig())

        kill_processes.assert_called_once_with()
        self.assertFalse(client.launch_attempted)

    def test_close_still_kills_processes_when_ok_cleanup_raises(self) -> None:
        client = OkStaminaGameClient(launcher=FakeLauncher())
        ok = RaisingOkRuntime()
        client.ok = ok
        client.launch_attempted = True

        with patch("ok_ww_automator.game_clients.kill_game_processes") as kill_processes:
            client.close(SheetRunConfig())

        self.assertEqual(ok.device_manager.stop_count, 1)
        self.assertEqual(ok.quit_count, 1)
        kill_processes.assert_called_once_with()

    def test_failed_launch_is_cleaned_up_by_close(self) -> None:
        class FailingLauncher(FakeLauncher):
            def start_ok_and_game(self):
                self.start_count += 1
                raise RuntimeError("launch failed")

        client = OkStaminaGameClient(launcher=FailingLauncher())

        with self.assertRaisesRegex(RuntimeError, "launch failed"):
            client._get_stamina_task()

        self.assertTrue(client.launch_attempted)
        with patch("ok_ww_automator.game_clients.kill_game_processes") as kill_processes:
            client.close(SheetRunConfig())

        kill_processes.assert_called_once_with()


class SubprocessGameClientTest(unittest.TestCase):
    def test_weekly_timeout_cleans_up_game_and_propagates(self):
        client = SubprocessWeeklyGameClient(AppConfig(Path("/project"), Path("/project/env/cn.env")), ww_root=Path("/ww"))
        with (
            patch("ok_ww_automator.game_clients.run_with_timeout", side_effect=subprocess.TimeoutExpired("game", 10)),
            patch("ok_ww_automator.game_clients.kill_game_processes") as cleanup,
        ):
            with self.assertRaises(subprocess.TimeoutExpired):
                client.run_weekly(timeout=10)
        cleanup.assert_called_once()

    def test_timeout_terminates_process_tree_before_waiting_for_exit(self):
        process = Mock(pid=123)
        process.wait.side_effect = [subprocess.TimeoutExpired("game", 10), 1]
        process.poll.return_value = 1
        with patch("ok_ww_automator.processes.os.name", "nt"), patch("ok_ww_automator.processes.subprocess.Popen", return_value=process), patch("ok_ww_automator.processes.subprocess.run") as kill:
            with self.assertRaises(subprocess.TimeoutExpired):
                run_with_timeout(["game"], timeout=10)
        self.assertEqual(kill.call_args.args[0], ["taskkill", "/PID", "123", "/T", "/F"])
        self.assertEqual(kill.call_args.kwargs["timeout"], 15)
        process.wait.assert_called_with(timeout=5)

    def test_weekly_child_requires_explicit_completion(self):
        config = AppConfig(Path("/project"), Path("/project/env/cn.env"))
        client = SubprocessWeeklyGameClient(config, ww_root=Path("/ww"))
        for payload, expected in [({}, False), ({"completed": True, "task_error": None}, True)]:
            def fake_run(command, env, timeout):
                self.assertEqual(timeout, 40 * 60)
                self.assertEqual(command[command.index("--mode") + 1], "weekly")
                self.assertEqual(env["ENV_FILE"], str(config.env_path))
                Path(command[command.index("--output") + 1]).write_text(json.dumps(payload), encoding="utf-8")
                return subprocess.CompletedProcess(command, 0)
            with self.subTest(payload=payload), patch("ok_ww_automator.game_clients.run_with_timeout", side_effect=fake_run):
                self.assertEqual(client.run_weekly().completed, expected)

    def test_daily_attempt_runs_in_child_process_and_returns_outcome(self) -> None:
        app_config = AppConfig(
            project_root=Path("/project"),
            env_path=Path("/project/env/cn.env"),
            game_exe_path=Path("/game/Wuthering Waves.exe"),
        )
        sheet_config = SheetRunConfig(which_to_farm="模拟领域")

        def fake_run(command, env, check):
            input_path = Path(command[command.index("--input") + 1])
            output_path = Path(command[command.index("--output") + 1])
            payload = json.loads(input_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["sheet_config"]["which_to_farm"], "模拟领域")
            self.assertEqual(env["ENV_FILE"], str(app_config.env_path))
            self.assertFalse(check)
            output_path.write_text(json.dumps({"daily_points": 100}), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0)

        with patch("ok_ww_automator.game_clients.subprocess.run", side_effect=fake_run) as run:
            outcome = SubprocessDailyGameClient(app_config, ww_root=Path("/ww")).run_daily(sheet_config)

        self.assertEqual(outcome.daily_points, 100)
        command = run.call_args.args[0]
        self.assertIn("ok_ww_automator.game_attempt", command)
        self.assertEqual(command[command.index("--mode") + 1], "daily")
        self.assertEqual(command[command.index("--operation") + 1], "run")

    def test_stamina_attempt_reads_tuple_from_child_process(self) -> None:
        app_config = AppConfig(
            project_root=Path("/project"),
            env_path=Path("/project/env/cn.env"),
            game_exe_path=Path("/game/Wuthering Waves.exe"),
        )

        def fake_run(command, env, check):
            output_path = Path(command[command.index("--output") + 1])
            output_path.write_text(json.dumps({"stamina": 70, "backup_stamina": 10}), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0)

        with patch("ok_ww_automator.game_clients.subprocess.run", side_effect=fake_run):
            stamina = SubprocessStaminaGameClient(app_config, ww_root=Path("/ww")).read_stamina(SheetRunConfig())

        self.assertEqual(stamina, (70, 10))

    def test_child_process_error_is_raised_with_payload_message(self) -> None:
        app_config = AppConfig(
            project_root=Path("/project"),
            env_path=Path("/project/env/cn.env"),
            game_exe_path=Path("/game/Wuthering Waves.exe"),
        )

        def fake_run(command, env, check):
            output_path = Path(command[command.index("--output") + 1])
            output_path.write_text(json.dumps({"error": "RuntimeError: child failed"}), encoding="utf-8")
            return subprocess.CompletedProcess(command, 1)

        with patch("ok_ww_automator.game_clients.subprocess.run", side_effect=fake_run):
            with self.assertRaisesRegex(RuntimeError, "child failed"):
                SubprocessDailyGameClient(app_config, ww_root=Path("/ww")).run_daily(SheetRunConfig())

    def test_native_teardown_crash_after_stamina_result_is_accepted(self) -> None:
        app_config = AppConfig(
            project_root=Path("/project"),
            env_path=Path("/project/env/cn.env"),
            game_exe_path=Path("/game/Wuthering Waves.exe"),
        )

        def fake_run(command, env, check):
            output_path = Path(command[command.index("--output") + 1])
            output_path.write_text(
                json.dumps({"stamina_left": 14, "backup_stamina_left": 7, "task_error": None}),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, WINDOWS_ACCESS_VIOLATION_EXIT_CODE)

        with patch("ok_ww_automator.game_clients.subprocess.run", side_effect=fake_run):
            outcome = SubprocessStaminaGameClient(app_config, ww_root=Path("/ww")).run_stamina(SheetRunConfig())

        self.assertEqual(outcome.stamina_left, 14)
        self.assertEqual(outcome.backup_stamina_left, 7)
        self.assertIsNone(outcome.task_error)

    def test_native_teardown_crash_without_result_still_fails(self) -> None:
        app_config = AppConfig(
            project_root=Path("/project"),
            env_path=Path("/project/env/cn.env"),
            game_exe_path=Path("/game/Wuthering Waves.exe"),
        )

        def fake_run(command, env, check):
            return subprocess.CompletedProcess(command, WINDOWS_ACCESS_VIOLATION_EXIT_CODE)

        with patch("ok_ww_automator.game_clients.subprocess.run", side_effect=fake_run):
            with self.assertRaisesRegex(RuntimeError, "Game attempt subprocess exited 3221225477"):
                SubprocessStaminaGameClient(app_config, ww_root=Path("/ww")).run_stamina(SheetRunConfig())


if __name__ == "__main__":
    unittest.main()
