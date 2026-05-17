from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ok_ww_automator.ok_main import EXTRA_ONETIME_TASKS, build_ok_config


class OkMainTest(unittest.TestCase):
    def test_build_ok_config_adds_extra_tasks_without_mutating_base_config(self) -> None:
        base_config = {
            "onetime_tasks": [["src.task.DailyTask", "DailyTask"], list(EXTRA_ONETIME_TASKS[0])],
            "use_gui": True,
        }

        config = build_ok_config(base_config)

        self.assertIsNot(config, base_config)
        self.assertEqual(base_config["onetime_tasks"], [["src.task.DailyTask", "DailyTask"], list(EXTRA_ONETIME_TASKS[0])])
        self.assertEqual(config["use_gui"], True)
        for task in EXTRA_ONETIME_TASKS:
            self.assertIn(list(task), config["onetime_tasks"])
        self.assertEqual(config["onetime_tasks"].count(list(EXTRA_ONETIME_TASKS[0])), 1)


if __name__ == "__main__":
    unittest.main()
