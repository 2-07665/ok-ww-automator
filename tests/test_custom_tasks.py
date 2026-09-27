"""Behavior of game-independent parsers and control flow with upstream I/O stubbed."""

from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ok_ww_automator.ok_tasks.echo_stats import parse_echo_stats


@contextmanager
def custom_task_module(name):
    # Loading the real adapter against a tiny base keeps these control-flow
    # tests runnable without installing Windows capture, Qt or game assets.
    ok = ModuleType("ok")
    ok.find_color_rectangles = Mock(return_value=[])
    base = ModuleType("src.task.BaseWWTask")
    base.BaseWWTask = type("BaseWWTask", (), {})
    path = Path(__file__).resolve().parents[1] / "src" / "ok_ww_automator" / "ok_tasks" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"ok_ww_automator.ok_tasks.{name}", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"ok": ok, "src.task.BaseWWTask": base}):
        spec.loader.exec_module(module)
        yield module


def text_box(name, x, y, width=40, height=10):
    return SimpleNamespace(name=name, x=x, y=y, width=width, height=height)


class EchoStatsTest(unittest.TestCase):
    def test_geometry_pairs_shuffled_ocr_rows_and_handles_joined_fullwidth_text(self):
        boxes = [
            text_box("+10.5%", 100, 20), text_box("攻击", 0, 0),
            text_box("+40", 100, 0), text_box("暴击", 0, 20),
            text_box("暴击伤害＋２１．０％", 0, 40, width=140),
        ]
        self.assertEqual(parse_echo_stats(boxes), [
            {"buffName": "Attack_Flat", "buffValue": 40},
            {"buffName": "Crit_Rate", "buffValue": 105},
            {"buffName": "Crit_Damage", "buffValue": 210},
        ])

    def test_invalid_ocr_values_are_never_rounded_or_borrowed_from_another_row(self):
        boxes = [
            text_box("暴击+6.31%", 0, 0), text_box("防御", 0, 20),
            text_box("+8.1%", 100, 40), text_box("生命+1,320", 0, 60),
            text_box("暴击+105", 0, 80),
        ]
        self.assertEqual(parse_echo_stats(boxes), [])


class CustomTaskControlFlowTest(unittest.TestCase):
    def test_missing_boss_does_not_attack_or_increment_fight_count(self):
        with custom_task_module("fast_farm_echo") as module:
            task = module.FastFarmEchoTask()
            def wait_for_missing_boss(condition, **kwargs):
                if kwargs["raise_if_not_found"]:
                    raise TimeoutError("boss absent")
                return None

            task.wait_until = Mock(side_effect=wait_for_missing_boss)
            task._fixed_char = Mock()
            task.info_incr = Mock()
            task.simple_pickup_echo = Mock()
            with self.assertRaisesRegex(TimeoutError, "boss absent"):
                task.my_farm_once()
            task._fixed_char.one_shot.assert_not_called()
            task.info_incr.assert_not_called()
            task.simple_pickup_echo.assert_not_called()

    def test_merge_retries_navigation_but_never_retries_an_uncertain_submission(self):
        with custom_task_module("five_to_one") as module:
            for error, expected_attempts in [
                (module.MergeNavigationError("missing menu"), module.FiveToOneTask.MAX_RETRIES),
                (module.MergeOutcomeUnknown("result not confirmed"), 1),
            ]:
                with self.subTest(error=type(error).__name__):
                    task = module.FiveToOneTask()
                    task.log_info = Mock()
                    task.info_set = Mock()
                    task.enter_batch_merge = Mock()
                    task.loop_merge = Mock(side_effect=error)
                    task.ensure_main = Mock()
                    task.sleep = Mock()
                    with self.assertRaises(RuntimeError):
                        task.run()
                    self.assertEqual(task.enter_batch_merge.call_count, expected_attempts)
                    self.assertEqual(task.sleep.call_count, expected_attempts - 1)

    def test_unreadable_merge_count_is_not_treated_as_depleted_inventory(self):
        with custom_task_module("five_to_one") as module:
            task = module.FiveToOneTask()
            task.wait_click_ocr = Mock(return_value=True)
            task.ocr = Mock(return_value=[])
            with self.assertRaises(module.MergeNavigationError):
                task.loop_merge()
            # The only click was Select All, never the destructive Merge button.
            self.assertEqual(task.wait_click_ocr.call_count, 1)
            self.assertEqual(task.wait_click_ocr.call_args.kwargs["match"], "全选")


if __name__ == "__main__":
    unittest.main()
