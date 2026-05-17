from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ok_ww_automator.models import SheetRunConfig
from ok_ww_automator.game_clients import (
    OkStaminaGameClient,
    apply_daily_task_config,
    simulation_material_value,
    stamina_burn_unit,
)


class FakeDailyTask:
    def __init__(self) -> None:
        self.config = {}
        self.support_tasks = ["Tacet", "Forgery", "Simulation"]


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


class GameClientsTest(unittest.TestCase):
    def test_apply_daily_task_config_maps_sheet_values(self) -> None:
        task = FakeDailyTask()
        config = SheetRunConfig(
            which_to_farm="凝素领域",
            tacet_serial=3,
            forgery_serial=2,
            simulation_material="武器经验",
            run_nightmare=True,
        )

        apply_daily_task_config(config, task)

        self.assertEqual(task.config["Which to Farm"], "Forgery")
        self.assertEqual(task.config["Which Tacet Suppression to Farm"], 3)
        self.assertEqual(task.config["Which Forgery Challenge to Farm"], 2)
        self.assertEqual(task.config["Material Selection"], "Weapon EXP")
        self.assertTrue(task.config["Auto Farm all Nightmare Nest"])
        self.assertTrue(task.config["Farm Nightmare Nest for Daily Echo"])

    def test_unknown_simulation_material_defaults_to_shell_credit(self) -> None:
        self.assertEqual(simulation_material_value("unknown"), "Shell Credit")

    def test_stamina_burn_unit_depends_on_farm_type(self) -> None:
        self.assertEqual(stamina_burn_unit(SheetRunConfig(which_to_farm="无音区")), 60)
        self.assertEqual(stamina_burn_unit(SheetRunConfig(which_to_farm="凝素领域")), 40)


class OkStaminaGameClientTest(unittest.TestCase):
    def test_close_stops_game(self) -> None:
        client = OkStaminaGameClient(launcher=object())
        ok = FakeOkRuntime()
        client.ok = ok

        client.close(SheetRunConfig())

        self.assertEqual(ok.device_manager.stop_count, 1)
        self.assertEqual(ok.quit_count, 1)

    def test_close_resets_cached_runtime(self) -> None:
        client = OkStaminaGameClient(launcher=object())
        ok = FakeOkRuntime()
        client.ok = ok

        client.close(SheetRunConfig())

        self.assertIsNone(client.ok)
        self.assertIsNone(client.stamina_task)


if __name__ == "__main__":
    unittest.main()
