from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ok_ww_automator.updater import build_update_plan, run_commands


class UpdaterTest(unittest.TestCase):
    def test_dependencies_use_the_running_python_not_environment_discovery(self) -> None:
        plan = build_update_plan(ww_root=Path("/repo/ok-wuthering-waves"), requirements_file=Path("requirements.txt"))
        with patch("ok_ww_automator.updater.subprocess.run") as run:
            run_commands(plan.commands[-1:])
        args = run.call_args.args[0]
        self.assertEqual(args[args.index("--python") + 1], sys.executable)
        self.assertEqual(Path(args[args.index("-r") + 1]), plan.ww_root / "requirements.txt")

    def test_update_fast_forwards_but_preserves_conflicting_work_and_commits(self) -> None:
        # Exercise actual Git behavior; a mocked command-string assertion cannot
        # establish that the updater preserves the user's checkout.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            remote = root / "remote"
            local = root / "local"

            def git(*args, cwd=None):
                return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()

            git("init", "--bare", "--initial-branch=master", str(remote))
            git("clone", str(remote), str(local))
            for key, value in (("user.name", "Automator tests"), ("user.email", "tests@example.invalid")):
                git("config", key, value, cwd=local)
            tracked = local / "tracked.txt"
            tracked.write_text("initial\n", encoding="utf-8")
            git("add", "tracked.txt", cwd=local)
            git("commit", "-m", "initial", cwd=local)
            git("push", "origin", "master", cwd=local)
            initial = git("rev-parse", "HEAD", cwd=local)
            tracked.write_text("upstream\n", encoding="utf-8")
            git("commit", "-am", "upstream", cwd=local)
            git("push", "origin", "master", cwd=local)
            upstream = git("rev-parse", "HEAD", cwd=local)
            git("reset", "--hard", initial, cwd=local)

            plan = build_update_plan(ww_root=local)
            tracked.write_text("uncommitted work\n", encoding="utf-8")
            with self.assertRaises(subprocess.CalledProcessError):
                run_commands(plan.commands[:2])
            self.assertEqual(tracked.read_text(encoding="utf-8"), "uncommitted work\n")
            self.assertEqual(git("rev-parse", "HEAD", cwd=local), initial)

            git("checkout", "--", "tracked.txt", cwd=local)
            run_commands(plan.commands[:2])
            self.assertEqual(git("rev-parse", "HEAD", cwd=local), upstream)

            git("reset", "--hard", initial, cwd=local)
            tracked.write_text("local committed work\n", encoding="utf-8")
            git("commit", "-am", "local", cwd=local)
            local_commit = git("rev-parse", "HEAD", cwd=local)
            with self.assertRaises(subprocess.CalledProcessError):
                run_commands(plan.commands[:2])
            self.assertEqual(git("rev-parse", "HEAD", cwd=local), local_commit)
            self.assertEqual(tracked.read_text(encoding="utf-8"), "local committed work\n")


if __name__ == "__main__":
    unittest.main()
