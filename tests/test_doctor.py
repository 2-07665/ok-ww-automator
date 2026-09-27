import ast
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ok_ww_automator import doctor


class DoctorTests(unittest.TestCase):
    def test_call_contract_rejects_breaking_signature_changes(self):
        contract = dict(id="call", file="task.py", kind="call", symbol="Task.run",
                        positional=1, keywords=["timeout"], reason="Adapter call must bind")
        for signature, status in [
            ("self, config, timeout=10", "PASS"),
            ("self, config, *, timeout=10", "PASS"),
            ("self, config, timeout=10, *, required", "FAIL"),
            ("self, config, wait=10", "FAIL"),
            ("self, config, timeout, /", "FAIL"),
            ("self, *, config, timeout=10", "FAIL"),
        ]:
            with self.subTest(signature=signature):
                tree = ast.parse(f"class Task:\n def run({signature}): pass")
                self.assertEqual(doctor.check_contract(tree, contract)[0].status, status)

    def test_semantic_change_requires_review_while_formatting_does_not(self):
        original = ast.parse("def run():\n return (1, 2, 3)\n")
        contract = dict(id="stamina", file="task.py", kind="call", symbol="run",
                        sha256=doctor.fingerprint(doctor.find_node(original, "run")),
                        reason="Tuple order is current, backup, total")
        for source, status in [("def run(): # comment\n    return (1,2,3)", "PASS"),
                               ("def run():\n return (2,1,3)", "WARN")]:
            self.assertEqual(doctor.check_contract(ast.parse(source), contract)[0].status, status)

    def test_configuration_and_registration_drift_is_a_failure(self):
        cases = [
            (dict(kind="assignment", target="self.support_tasks", value=["tacet", "forgery"]),
             "self.support_tasks = ['forgery', 'tacet']"),
            (dict(kind="registrations", values=[["src.task.DailyTask", "DailyTask"]]),
             "config = {'onetime_tasks': [['src.task.Other', 'Other']]}"),
            (dict(kind="dict_keys", values=["Which to Farm"]),
             "default_config = {'Which Farm': 0}"),
        ]
        for options, source in cases:
            contract = dict(id="config", file="config.py", reason="Review adapter mapping", **options)
            self.assertEqual(doctor.check_contract(ast.parse(source), contract)[0].status, "FAIL")

    def test_source_checks_never_execute_upstream_and_report_missing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "safe.py").write_text("raise RuntimeError('must not execute')\ndef run(): pass")
            checks = [dict(id=name, root="ww", file=name, kind="call", symbol="run", reason="Required API")
                      for name in ("safe.py", "missing.py")]
            result = doctor.inspect_sources({"ww": root}, {"checks": checks})
            self.assertEqual([item.status for item in result], ["PASS", "FAIL"])

    def test_lazy_export_contract_checks_binding_not_incidental_strings(self):
        contract = dict(id="exports", file="ok/__init__.py", kind="lazy_exports",
                        target="_LAZY_IMPORTS", reason="Custom task imports must resolve",
                        values={"TaskDisabledException": ["ok.task.exceptions", "TaskDisabledException"]})
        for exports, status in [
            ({"TaskDisabledException": ("ok.task.exceptions", "TaskDisabledException")}, "PASS"),
            ({"TaskDisabledException": ("ok.task.exceptions", "OtherException")}, "FAIL"),
            ({"OtherException": ("ok.task.exceptions", "TaskDisabledException")}, "FAIL"),
            ({}, "FAIL"),
        ]:
            with self.subTest(exports=exports):
                source = f"_LAZY_IMPORTS = {exports!r}\nnotes = 'TaskDisabledException'"
                self.assertEqual(doctor.check_contract(ast.parse(source), contract)[0].status, status)

    def test_frame_property_and_ocr_return_behavior_require_review(self):
        for original, changed in [
            ("class Task:\n @property\n def frame(self): return self.executor.frame",
             "class Task:\n def frame(self): return self.executor.frame"),
            ("class Task:\n def wait_ocr(self): return boxes",
             "class Task:\n def wait_ocr(self): return bool(boxes)"),
        ]:
            old_tree = ast.parse(original)
            symbol = "Task." + old_tree.body[0].body[0].name
            contract = dict(id=symbol, file="task.py", kind="symbol", symbol=symbol,
                            reason="Consumers require a frame property and OCR boxes",
                            sha256=doctor.fingerprint(doctor.find_node(old_tree, symbol)))
            self.assertEqual(doctor.check_contract(ast.parse(changed), contract)[0].status, "WARN")

    def test_missing_runtime_still_checks_game_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "assets").mkdir()
            (root / "assets/coco_annotations.json").write_text('{"categories": []}')
            manifest = dict(checks=[dict(id="game.api", root="ww", file="missing.py", kind="symbol",
                                        symbol="Task", reason="Required task")], features=[], manual_checks=[])
            result = doctor.diagnose(ww_root=root, ok_root=None, source_only=True, manifest=manifest)
            failures = {item.check for item in result if item.status == "FAIL"}
            self.assertEqual(failures, {"ok-script.source", "game.api"})

    def test_cli_json_and_exit_status_distinguish_warnings_failures_and_manual_checks(self):
        for status, strict, expected in [("PASS", False, 0), ("WARN", False, 0),
                                         ("WARN", True, 1), ("FAIL", False, 1), ("MANUAL", True, 0)]:
            with self.subTest(status=status, strict=strict):
                output = io.StringIO()
                with patch.object(doctor, "diagnose", return_value=[doctor.Finding(status, "check", "detail")]), \
                     patch.object(doctor, "installed_ok_root", return_value=None), redirect_stdout(output):
                    code = doctor.main(["--json"] + (["--strict"] if strict else []))
                self.assertEqual(code, expected)
                self.assertEqual(json.loads(output.getvalue())[0]["status"], status)


if __name__ == "__main__":
    unittest.main()
