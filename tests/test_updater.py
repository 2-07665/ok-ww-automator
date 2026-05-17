from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ok_ww_automator.updater import build_update_plan


class UpdaterTest(unittest.TestCase):
    def test_build_update_plan_targets_wuthering_waves_and_uv_pip(self) -> None:
        ww_root = Path("/repo/ok-wuthering-waves")
        plan = build_update_plan(ww_root=ww_root, remote="origin", branch="my")
        
        resolved_root_str = str(ww_root.resolve())
        req_str = str((ww_root / "requirements.txt").resolve())

        self.assertEqual(plan.commands[0].args, ("git", "-C", resolved_root_str, "fetch", "origin", "--prune"))
        self.assertEqual(plan.commands[1].args, ("git", "-C", resolved_root_str, "reset", "--hard", "origin/my"))
        self.assertEqual(plan.commands[2].args, ("uv", "pip", "install", "-r", req_str))
        self.assertEqual(plan.commands[2].cwd, ww_root.resolve())


if __name__ == "__main__":
    unittest.main()
