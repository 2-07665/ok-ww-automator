from __future__ import annotations

from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ok_ww_automator.env_discovery import AccountEnv, discover_account_envs
from ok_ww_automator.windows_launcher import (
    CREATE_NO_WINDOW,
    DEFAULT_WINDOW_SIZE,
    GAME_LAUNCH_COOLDOWN_MS,
    GameLaunch,
    LauncherConfigurationError,
    LauncherPaths,
    MINIMUM_ACCOUNT_TABLE_HEIGHT,
    MINIMUM_LOG_HEIGHT,
    MINIMUM_WINDOW_SIZE,
    ManagedProcess,
    build_game_launch,
    build_ok_gui_command,
    build_scheduler_command,
    discover_launcher_paths,
    find_automator_root,
    launch_game,
    selected_account_ids,
)


class BlockingStdout:
    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.entered = threading.Event()
        self.release = threading.Event()

    def __iter__(self):
        self.entered.set()
        self.release.wait(timeout=2)
        yield from self.lines


class FakeProcess:
    def __init__(self, *, lines: list[str] | None = None, returncode: int = 0, pid: int = 4321) -> None:
        self.stdout = BlockingStdout(lines or [])
        self.returncode = returncode
        self.pid = pid
        self.terminated = False

    def wait(self) -> int:
        return self.returncode

    def poll(self) -> int | None:
        return self.returncode if self.stdout.release.is_set() else None

    def terminate(self) -> None:
        self.terminated = True
        self.stdout.release.set()


def wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached before timeout")


class LauncherDiscoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp_dir.name).resolve()
        self.automator = self.workspace / "ok-ww-automator"
        (self.automator / "src" / "ok_ww_automator").mkdir(parents=True)
        (self.automator / "env").mkdir()
        (self.automator / "dist").mkdir()
        (self.automator / "pyproject.toml").touch()
        (self.automator / "src" / "ok_ww_automator" / "scheduler.py").touch()
        (self.workspace / "ok-wuthering-waves").mkdir()
        (self.workspace / ".venv" / "Scripts").mkdir(parents=True)
        (self.workspace / ".venv" / "Scripts" / "python.exe").touch()

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    def test_finds_project_from_executable_in_repository_root(self) -> None:
        executable = self.automator / "OKAutomatorLauncher.exe"
        self.assertEqual(find_automator_root(executable), self.automator)
        self.assertEqual(discover_launcher_paths(executable).workspace_root, self.workspace)

    def test_finds_project_from_executable_in_dist(self) -> None:
        executable = self.automator / "dist" / "OKAutomatorLauncher.exe"
        paths = discover_launcher_paths(executable)
        self.assertEqual(paths.automator_root, self.automator)
        self.assertEqual(paths.python_exe, self.workspace / ".venv" / "Scripts" / "python.exe")

    def test_rejects_incomplete_sibling_layout(self) -> None:
        (self.workspace / ".venv" / "Scripts" / "python.exe").unlink()
        with self.assertRaisesRegex(LauncherConfigurationError, "Missing shared Python interpreter"):
            discover_launcher_paths(self.automator / "dist" / "OKAutomatorLauncher.exe")

    def test_account_discovery_preserves_case_and_default_name(self) -> None:
        (self.automator / "env" / ".env.example").touch()
        (self.automator / "env" / ".env").touch()
        (self.automator / "env" / "CN.env").touch()
        (self.automator / "env" / "US.env").touch()

        accounts = discover_account_envs(self.automator / "env")

        self.assertEqual([account.account_id for account in accounts], ["default", "CN", "US"])

    def test_game_launch_uses_the_selected_account_path(self) -> None:
        cn_game = self.workspace / "CN" / "Wuthering Waves.exe"
        us_game = self.workspace / "US" / "Wuthering Waves.exe"
        cn_game.parent.mkdir()
        us_game.parent.mkdir()
        cn_game.touch()
        us_game.touch()
        cn_env = self.automator / "env" / "CN.env"
        us_env = self.automator / "env" / "US.env"
        cn_env.write_text(f'GAME_EXE_PATH="{cn_game.as_posix()}"\n', encoding="utf-8")
        us_env.write_text(f'GAME_EXE_PATH="{us_game.as_posix()}"\n', encoding="utf-8")
        accounts = [AccountEnv("US", us_env), AccountEnv("CN", cn_env)]

        launch = build_game_launch(accounts, ["CN"])

        self.assertEqual(launch, GameLaunch("CN", cn_game.resolve()))

    def test_game_launch_requires_exactly_one_account(self) -> None:
        accounts = [AccountEnv("US", Path("US.env")), AccountEnv("CN", Path("CN.env"))]
        with self.assertRaisesRegex(ValueError, "Select exactly one account"):
            build_game_launch(accounts, ["US", "CN"])

    def test_game_launches_require_a_configured_existing_executable(self) -> None:
        missing_env = self.automator / "env" / "missing.env"
        missing_env.touch()
        with self.assertRaisesRegex(ValueError, "Account missing: GAME_EXE_PATH is missing"):
            build_game_launch([AccountEnv("missing", missing_env)], ["missing"])

        invalid_env = self.automator / "env" / "invalid.env"
        invalid_env.write_text("GAME_EXE_PATH=C:/missing/game.exe\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Account invalid: game executable not found"):
            build_game_launch([AccountEnv("invalid", invalid_env)], ["invalid"])


class LauncherCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        workspace = Path("C:/workspace")
        self.paths = LauncherPaths(
            workspace_root=workspace,
            automator_root=workspace / "ok-ww-automator",
            upstream_root=workspace / "ok-wuthering-waves",
            python_exe=workspace / ".venv" / "Scripts" / "python.exe",
        )

    def test_builds_ok_gui_command(self) -> None:
        self.assertEqual(
            build_ok_gui_command(self.paths),
            [
                str(self.paths.python_exe),
                "-m",
                "ok_ww_automator.ok_main",
                "--ww-root",
                str(self.paths.upstream_root),
            ],
        )

    def test_builds_scheduler_command_with_ordered_repeated_accounts_and_updates(self) -> None:
        command = build_scheduler_command(self.paths, "stamina", ["US", "CN"])

        self.assertEqual(
            command,
            [
                str(self.paths.python_exe),
                "-m",
                "ok_ww_automator.scheduler",
                "--project-root",
                str(self.paths.automator_root),
                "--ww-root",
                str(self.paths.upstream_root),
                "--mode",
                "stamina",
                "--account",
                "US",
                "--account",
                "CN",
            ],
        )
        self.assertNotIn("--skip-update", command)

    def test_selection_validation_uses_display_order(self) -> None:
        accounts = [AccountEnv("US", Path("US.env")), AccountEnv("CN", Path("CN.env"))]
        self.assertEqual(selected_account_ids(accounts, ["CN", "US"]), ["US", "CN"])
        with self.assertRaisesRegex(ValueError, "Select at least one"):
            selected_account_ids(accounts, [])
        with self.assertRaisesRegex(ValueError, "Unknown account env: us"):
            selected_account_ids(accounts, ["us"])

    def test_build_inputs_require_uac_admin_and_windowed_one_file_output(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        build_script = (project_root / "windows" / "build_launcher.ps1").read_text(encoding="utf-8")
        manifest = (project_root / "windows" / "launcher.manifest").read_text(encoding="utf-8")

        self.assertIn('"--onefile"', build_script)
        self.assertIn('"--windowed"', build_script)
        self.assertIn('"--uac-admin"', build_script)
        self.assertIn('level="requireAdministrator"', manifest)

    def test_default_layout_reserves_space_for_accounts_and_log(self) -> None:
        self.assertGreaterEqual(DEFAULT_WINDOW_SIZE[0], 1_100)
        self.assertGreaterEqual(DEFAULT_WINDOW_SIZE[1], 850)
        self.assertGreaterEqual(MINIMUM_WINDOW_SIZE[0], 900)
        self.assertGreaterEqual(MINIMUM_ACCOUNT_TABLE_HEIGHT, 180)
        self.assertGreaterEqual(MINIMUM_LOG_HEIGHT, 240)
        self.assertEqual(GAME_LAUNCH_COOLDOWN_MS, 3_000)

    def test_launch_game_starts_executable_without_managing_it(self) -> None:
        popen = Mock()
        launch = GameLaunch("US", Path("C:/Games/US/Wuthering Waves.exe"))

        launch_game(launch, popen=popen, platform_name="nt")

        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0], [str(launch.executable)])
        self.assertEqual(popen.call_args.kwargs["cwd"], str(launch.executable.parent))
        self.assertIs(popen.call_args.kwargs["stdout"], __import__("subprocess").DEVNULL)
        self.assertIs(popen.call_args.kwargs["stderr"], __import__("subprocess").DEVNULL)
        self.assertFalse(popen.call_args.kwargs["shell"])
        self.assertEqual(popen.call_args.kwargs["creationflags"], CREATE_NO_WINDOW)

    def test_launch_game_does_not_leak_pyinstaller_dll_path_to_game(self) -> None:
        popen = Mock()
        dll_directory_setter = Mock()
        launch = GameLaunch("US", Path("C:/Games/US/Wuthering Waves.exe"))

        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "_MEIPASS", "C:/Temp/_MEI123", create=True),
        ):
            launch_game(
                launch,
                popen=popen,
                platform_name="nt",
                dll_directory_setter=dll_directory_setter,
            )

        self.assertEqual(dll_directory_setter.call_args_list, [call(None), call("C:/Temp/_MEI123")])
        popen.assert_called_once()

    def test_launch_game_restores_pyinstaller_dll_path_after_spawn_failure(self) -> None:
        dll_directory_setter = Mock()
        launch = GameLaunch("US", Path("C:/Games/US/Wuthering Waves.exe"))

        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "_MEIPASS", "C:/Temp/_MEI123", create=True),
            self.assertRaisesRegex(OSError, "failed"),
        ):
            launch_game(
                launch,
                popen=Mock(side_effect=OSError("failed")),
                platform_name="nt",
                dll_directory_setter=dll_directory_setter,
            )

        self.assertEqual(dll_directory_setter.call_args_list, [call(None), call("C:/Temp/_MEI123")])


class ManagedProcessTest(unittest.TestCase):
    def test_state_output_queue_action_lock_and_success(self) -> None:
        child = FakeProcess(lines=["one\n", "two\n"])
        popen = Mock(return_value=child)
        manager = ManagedProcess(popen=popen, platform_name="nt")

        manager.start("Daily scheduler", ["python.exe", "-m", "module"], cwd=Path("C:/workspace"))
        self.assertTrue(child.stdout.entered.wait(timeout=1))
        self.assertEqual(manager.state, "running")
        with self.assertRaisesRegex(RuntimeError, "already active"):
            manager.start("Other", ["other.exe"], cwd=Path("C:/workspace"))

        child.stdout.release.set()
        wait_until(lambda: manager.state == "idle")
        events = []
        while True:
            try:
                events.append(manager.events.get_nowait())
            except queue.Empty:
                break

        self.assertEqual([event.text for event in events if event.kind == "output"], ["one\n", "two\n"])
        self.assertEqual(events[-1].text, "completed")
        self.assertEqual(events[-1].returncode, 0)
        kwargs = popen.call_args.kwargs
        self.assertIs(kwargs["stderr"], __import__("subprocess").STDOUT)
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["creationflags"], CREATE_NO_WINDOW)
        self.assertEqual(kwargs["env"]["PYTHONUNBUFFERED"], "1")

    def test_failure_is_reported(self) -> None:
        child = FakeProcess(returncode=7)
        manager = ManagedProcess(popen=Mock(return_value=child), platform_name="nt")
        manager.start("OK GUI", ["python.exe"], cwd=Path("C:/workspace"))
        child.stdout.release.set()
        wait_until(lambda: manager.state == "idle")

        events = []
        while not manager.events.empty():
            events.append(manager.events.get_nowait())
        self.assertEqual(events[-1].text, "failed")
        self.assertEqual(events[-1].returncode, 7)

    def test_stop_terminates_complete_windows_process_tree(self) -> None:
        child = FakeProcess(pid=9876)
        popen = Mock(return_value=child)
        taskkill_result = Mock(returncode=0)
        run = Mock(return_value=taskkill_result)
        manager = ManagedProcess(popen=popen, run=run, platform_name="nt")
        manager.start("Daily scheduler", ["python.exe"], cwd=Path("C:/workspace"))
        self.assertTrue(child.stdout.entered.wait(timeout=1))

        self.assertTrue(manager.stop())
        self.assertEqual(manager.state, "stopping")
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["taskkill", "/PID", "9876", "/T", "/F"])
        self.assertFalse(child.terminated)

        child.stdout.release.set()
        wait_until(lambda: manager.state == "idle")
        events = []
        while not manager.events.empty():
            events.append(manager.events.get_nowait())
        self.assertEqual(events[-1].text, "stopped")

    def test_spawn_failure_unlocks_actions_and_reports_failure(self) -> None:
        manager = ManagedProcess(popen=Mock(side_effect=OSError("not found")), platform_name="nt")
        with self.assertRaisesRegex(OSError, "not found"):
            manager.start("OK GUI", ["missing.exe"], cwd=Path("C:/workspace"))

        self.assertEqual(manager.state, "idle")
        event = manager.events.get_nowait()
        self.assertEqual(event.kind, "finished")
        self.assertEqual(event.text, "not found")
        self.assertIsNone(event.returncode)


if __name__ == "__main__":
    unittest.main()
