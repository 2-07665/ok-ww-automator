from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ok_ww_automator.ok_launcher import (
    OkLaunchError,
    OkLauncher,
    OkLaunchOptions,
    get_task_error,
    is_ok_ready,
    kill_game_processes,
    run_onetime_task,
    ww_import_path,
    ww_runtime_context,
)


class FakeCapture:
    def __init__(self, connected: bool = True) -> None:
        self._connected = connected

    def connected(self) -> bool:
        return self._connected


class FakeDeviceManager:
    def __init__(self, preferred=None, capture=None, interaction=object()) -> None:
        self.preferred = preferred
        self.capture_method = capture
        self.interaction = interaction
        self.refreshes = []
        self.stopped = False

    def do_refresh(self, current=False) -> None:
        self.refreshes.append(current)

    def get_preferred_device(self):
        return self.preferred

    def stop_hwnd(self) -> None:
        self.stopped = True


class FakeExitEvent:
    def __init__(self, is_set: bool = False) -> None:
        self._is_set = is_set

    def is_set(self) -> bool:
        return self._is_set


class FakeExecutor:
    def __init__(self, current_task=None, exit_event=None) -> None:
        self.current_task = current_task
        self.exit_event = exit_event or FakeExitEvent()
        self.started = False

    def start(self) -> None:
        self.started = True


class FakeOk:
    def __init__(self, device_manager, task_executor=None) -> None:
        self.device_manager = device_manager
        self.task_executor = task_executor or FakeExecutor()

    def quit(self) -> None:
        pass


class FakeTask:
    name = "Fake Task"

    def __init__(self, *, enabled=False, error=None) -> None:
        self.enabled = enabled
        self.running = True
        self.error = error
        self.enable_count = 0
        self.unpause_count = 0

    def enable(self) -> None:
        self.enable_count += 1

    def unpause(self) -> None:
        self.unpause_count += 1

    def info_get(self, key, default=None):
        if key in {"Error", "error"}:
            return self.error
        return default


class Clock:
    def __init__(self) -> None:
        self.value = 0.0
        self.sleeps = []

    def monotonic(self) -> float:
        current = self.value
        self.value += 1.0
        return current

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


class OkLauncherTest(unittest.TestCase):
    def test_is_ok_ready_requires_device_capture_and_interaction(self) -> None:
        ready = FakeOk(FakeDeviceManager({"connected": True}, FakeCapture(True), object()))
        no_capture = FakeOk(FakeDeviceManager({"connected": True}, None, object()))

        self.assertTrue(is_ok_ready(ready))
        self.assertFalse(is_ok_ready(no_capture))

    def test_ensure_game_ready_launches_when_preferred_device_is_missing(self) -> None:
        device_manager = FakeDeviceManager(None, FakeCapture(True), object())
        ok = FakeOk(device_manager)
        launches = []
        clock = Clock()
        launcher = OkLauncher(
            OkLaunchOptions(
                ww_root=Path("/ww"),
                game_exe_path=Path("/game/Wuthering Waves.exe"),
                launch_wait_seconds=2,
                ready_timeout_seconds=3,
                ready_poll_seconds=1,
            ),
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

        with patch("ok_ww_automator.ok_launcher.load_runtime_imports") as load_imports:
            def launch(path: str) -> None:
                launches.append(path)
                device_manager.preferred = {"connected": True}

            load_imports.return_value.process_execute = launch
            launcher.ensure_game_ready(ok)

        self.assertEqual(launches, [str(Path("/game/Wuthering Waves.exe"))])
        self.assertTrue(ok.task_executor.started)
        self.assertIn(2, clock.sleeps)

    def test_start_ok_keeps_ww_root_on_path_during_ok_construction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ww_root = Path(tmp_dir).resolve()
            seen = []

            class FakeOkClass:
                def __init__(self, config) -> None:
                    seen.append((str(ww_root) in sys.path, Path.cwd(), config["use_gui"]))
                    self.device_manager = FakeDeviceManager({"connected": True}, FakeCapture(True), object())
                    self.task_executor = FakeExecutor()

                def quit(self) -> None:
                    pass

            launcher = OkLauncher(
                OkLaunchOptions(
                    ww_root=ww_root,
                    game_exe_path=Path("/game/Wuthering Waves.exe"),
                )
            )

            with patch("ok_ww_automator.ok_launcher.load_runtime_imports") as load_imports:
                load_imports.return_value.ok_class = FakeOkClass
                load_imports.return_value.config = {"use_gui": True}
                ok = launcher.start_ok()

            self.assertIsInstance(ok, FakeOkClass)
            self.assertEqual(seen, [(True, ww_root, False)])
            self.assertNotIn(str(ww_root), sys.path)
            self.assertNotEqual(Path.cwd(), ww_root)

    def test_start_ok_and_game_kills_existing_game_processes_before_starting(self) -> None:
        launcher = OkLauncher(
            OkLaunchOptions(
                ww_root=Path("/ww"),
                game_exe_path=Path("/game/Wuthering Waves.exe"),
            )
        )
        ok = FakeOk(FakeDeviceManager({"connected": True}, FakeCapture(True), object()))

        with (
            patch("ok_ww_automator.ok_launcher.kill_game_processes") as kill_processes,
            patch.object(launcher, "start_ok", return_value=ok) as start_ok,
            patch.object(launcher, "ensure_game_ready") as ensure_game_ready,
        ):
            self.assertIs(launcher.start_ok_and_game(), ok)

        kill_processes.assert_called_once_with()
        start_ok.assert_called_once_with()
        ensure_game_ready.assert_called_once_with(ok)

    def test_kill_game_processes_kills_known_process_names(self) -> None:
        class FakeProc:
            def __init__(self, name: str | None) -> None:
                self.info = {"name": name}
                self.killed = False

            def kill(self) -> None:
                self.killed = True

        game_launcher = FakeProc("Wuthering Waves.exe")
        game_client = FakeProc("Client-Win64-Shipping.exe")
        unrelated = FakeProc("notepad.exe")

        class FakePsutil:
            NoSuchProcess = RuntimeError
            AccessDenied = PermissionError

            @staticmethod
            def process_iter(attrs):
                self.assertEqual(attrs, ["name", "exe"])
                return [game_launcher, game_client, unrelated]

        with patch.dict(sys.modules, {"psutil": FakePsutil}):
            kill_game_processes()

        self.assertTrue(game_launcher.killed)
        self.assertTrue(game_client.killed)
        self.assertFalse(unrelated.killed)

    def test_run_onetime_task_returns_task_error(self) -> None:
        task = FakeTask(enabled=False, error="bad state")
        executor = FakeExecutor(current_task=None)

        error = run_onetime_task(executor, task, sleep=lambda _: None)

        self.assertEqual(error, "Fake Task: bad state")
        self.assertFalse(task.running)
        self.assertEqual(task.enable_count, 1)
        self.assertEqual(task.unpause_count, 1)

    def test_run_onetime_task_times_out(self) -> None:
        clock = Clock()
        task = FakeTask(enabled=True)
        executor = FakeExecutor(current_task=task)

        with self.assertRaisesRegex(TimeoutError, "Fake Task did not finish"):
            run_onetime_task(
                executor,
                task,
                timeout_seconds=2,
                poll_seconds=1,
                sleep=clock.sleep,
                monotonic=clock.monotonic,
            )

    def test_run_onetime_task_fails_when_executor_exits(self) -> None:
        task = FakeTask(enabled=True)
        executor = FakeExecutor(exit_event=FakeExitEvent(is_set=True))

        with self.assertRaisesRegex(OkLaunchError, "Executor exit event"):
            run_onetime_task(executor, task, sleep=lambda _: None)

    def test_get_task_error_falls_back_without_qt(self) -> None:
        self.assertEqual(get_task_error(FakeTask(error="  failed  ")), "failed")

    def test_ww_import_path_is_temporary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = str(Path(tmp_dir).resolve())
            self.assertNotIn(root, sys.path)
            with ww_import_path(Path(root)):
                self.assertEqual(sys.path[0], root)
            self.assertNotIn(root, sys.path)

    def test_ww_runtime_context_sets_path_and_cwd_temporarily(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir).resolve()
            previous = Path.cwd()
            with ww_runtime_context(root):
                self.assertEqual(Path.cwd(), root)
                self.assertEqual(sys.path[0], str(root))
            self.assertEqual(Path.cwd(), previous)
            self.assertNotIn(str(root), sys.path)


if __name__ == "__main__":
    unittest.main()
