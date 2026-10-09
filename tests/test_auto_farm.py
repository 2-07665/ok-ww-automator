from contextlib import nullcontext
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ok_ww_automator import auto_farm, ok_launcher
from ok_ww_automator.farm_progress import PROGRESS_PREFIX, read_progress


class AutoFarmTest(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.events = []
        self.progress = []
        self.farm = Mock(running=False)
        self.farm.info_get.return_value = 12
        self.merge = Mock()
        self.executor = Mock(current_task=None)
        self.executor.exit_event.is_set.return_value = False
        self.executor.get_task_by_class.side_effect = [self.farm, self.merge]
        self.runtime = Mock(task_executor=self.executor)
        self.ok_class = Mock(return_value=self.runtime)
        self.enterContext(patch.dict(sys.modules, {
            "ok": SimpleNamespace(OK=self.ok_class),
            "config": SimpleNamespace(config={}),
            "ok_ww_automator.ok_tasks.fast_farm_echo": SimpleNamespace(FastFarmEchoTask=type("Farm", (), {})),
            "ok_ww_automator.ok_tasks.five_to_one": SimpleNamespace(FiveToOneTask=type("Merge", (), {})),
        }))
        for name, value in (("ww_runtime_context", nullcontext()),
                            ("refresh_and_select_connected_device", None), ("is_ok_ready", True)):
            self.enterContext(patch.object(ok_launcher, name, return_value=value))
        self.enterContext(patch.object(ok_launcher.time, "monotonic", side_effect=lambda: self.now))
        self.enterContext(patch.object(ok_launcher.time, "sleep", side_effect=self.sleep))
        self.run_task = self.enterContext(patch.object(ok_launcher, "run_onetime_task", side_effect=self.run_task_impl))

    def sleep(self, seconds):
        self.now += seconds

    def run_task_impl(self, executor, task, **kwargs):
        self.events.append((task, self.now))
        if task is self.farm:
            self.now = 10
        return ""

    def run_farm(self):
        return ok_launcher.run_auto_farm(Path("unused"), stop_at=10, on_progress=self.progress.append)

    def test_scheduled_end_waits_300_seconds_before_merge(self):
        self.run_farm()
        self.assertEqual(self.events, [(self.farm, 0), (self.merge, 310)])
        self.assertEqual(self.progress[1].state, "waiting")
        self.assertEqual(self.progress[1].remaining, 300)
        self.assertEqual(self.progress[-1].state, "merging")
        self.runtime.quit.assert_called_once()
        self.assertEqual(len(self.ok_class.call_args.args[0]["onetime_tasks"]), 2)

    def test_deadline_timeout_waits_for_combat_exit_before_waiting(self):
        def run(executor, task, **kwargs):
            if task is self.farm:
                self.now = 10
                self.farm.running = True
                raise TimeoutError()
            self.events.append((task, self.now))
            return ""

        def sleep(seconds):
            self.sleep(seconds)
            self.farm.running = False

        self.run_task.side_effect = run
        with patch.object(ok_launcher.time, "sleep", side_effect=sleep):
            self.run_farm()
        self.farm.disable.assert_called_once()
        self.assertEqual(self.events, [(self.merge, 311)])

    def test_early_stop_and_failure_skip_wait_and_merge(self):
        for outcome in ("", "combat failed"):
            with self.subTest(outcome=outcome):
                self.executor.get_task_by_class.side_effect = [self.farm, self.merge]
                self.run_task.side_effect = None
                self.run_task.return_value = outcome
                with self.assertRaises(ok_launcher.OkLaunchError):
                    self.run_farm()
                self.assertEqual(self.now, 0)

    def test_exit_during_wait_skips_merge(self):
        def stop(seconds):
            self.sleep(seconds)
            self.executor.exit_event.is_set.return_value = True

        with patch.object(ok_launcher.time, "sleep", side_effect=stop):
            with self.assertRaises(ok_launcher.OkLaunchError):
                self.run_farm()
        self.assertEqual(self.events, [(self.farm, 0)])

    def test_stuck_combat_cannot_start_merge(self):
        self.farm.running = True
        with self.assertRaisesRegex(ok_launcher.OkLaunchError, "did not stop"):
            self.run_farm()
        self.assertEqual(self.events, [(self.farm, 0)])
        self.assertEqual(self.now, 40)

    def test_merge_failure_returns_for_shutdown_reporting(self):
        def run(executor, task, **kwargs):
            self.run_task_impl(executor, task, **kwargs)
            return "merge failed" if task is self.merge else ""

        self.run_task.side_effect = run
        self.assertEqual(self.run_farm(), "merge failed")
        self.runtime.quit.assert_called_once()

    def test_merge_timeout_returns_for_shutdown_reporting(self):
        def run(executor, task, **kwargs):
            self.run_task_impl(executor, task, **kwargs)
            if task is self.merge:
                raise TimeoutError("merge timed out")
            return ""

        self.run_task.side_effect = run
        self.assertEqual(self.run_farm(), "merge timed out")
        self.runtime.quit.assert_called_once()

    def test_exit_during_merge_does_not_allow_shutdown(self):
        def run(executor, task, **kwargs):
            self.run_task_impl(executor, task, **kwargs)
            if task is self.merge:
                self.executor.exit_event.is_set.return_value = True
            return ""

        self.run_task.side_effect = run
        with self.assertRaisesRegex(ok_launcher.OkLaunchError, "Executor exited"):
            self.run_farm()

    def test_merge_failure_still_shuts_down_and_reports_error(self):
        with patch.object(ok_launcher, "run_auto_farm", return_value="merge failed"), patch.object(auto_farm.subprocess, "run") as shutdown, patch.object(auto_farm, "emit_progress") as emit:
            auto_farm.main([])
        shutdown.assert_called_once_with(["shutdown.exe", "/s", "/t", "5"], check=True)
        self.assertEqual(emit.call_args.args[0].state, "shutdown")
        self.assertIn("merge failed", emit.call_args.args[0].message)

    def test_shutdown_only_after_successful_workflow(self):
        for failure in (None, RuntimeError("failed"), KeyboardInterrupt()):
            with self.subTest(failure=failure), patch.object(ok_launcher, "run_auto_farm", side_effect=failure, return_value="") as run, patch.object(auto_farm.subprocess, "run") as shutdown, patch.object(auto_farm, "emit_progress"):
                if failure is None:
                    auto_farm.main([])
                    shutdown.assert_called_once_with(["shutdown.exe", "/s", "/t", "5"], check=True)
                else:
                    with self.assertRaises(type(failure)):
                        auto_farm.main([])
                    shutdown.assert_not_called()
                run.assert_called_once()

    def test_finishing_progress_is_accepted(self):
        for state in ("waiting", "merging"):
            self.assertEqual(read_progress(PROGRESS_PREFIX + '{"state":"' + state + '"}').state, state)


if __name__ == "__main__":
    unittest.main()
