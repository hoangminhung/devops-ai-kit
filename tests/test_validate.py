"""Tests for scripts/validate.py checks that compare files.

Run: python3 -m unittest discover -s tests -v
"""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KIT_DIR = Path(__file__).resolve().parent.parent
SCRIPT = KIT_DIR / "scripts" / "validate.py"

spec = importlib.util.spec_from_file_location("validate_script", SCRIPT)
validate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validate)

PAIRS = [("templates/a.md", "claude/skills/s/templates/a.md")]


class TemplateCopies(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kit = Path(self.tmp.name)
        for rel in ("templates/a.md", "claude/skills/s/templates/a.md"):
            (self.kit / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.kit / rel).write_text("# same\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_identical_copies_pass(self):
        self.assertEqual(validate.template_copy_errors(self.kit, PAIRS), [])

    def test_changed_copy_is_reported(self):
        (self.kit / "claude/skills/s/templates/a.md").write_text("# changed\n")
        errors = validate.template_copy_errors(self.kit, PAIRS)
        self.assertEqual(len(errors), 1)
        self.assertIn("differs from templates/a.md", errors[0])

    def test_missing_copy_is_reported(self):
        (self.kit / "claude/skills/s/templates/a.md").unlink()
        self.assertIn("missing", validate.template_copy_errors(self.kit, PAIRS)[0])

    def test_real_kit_copies_are_identical(self):
        self.assertEqual(validate.template_copy_errors(KIT_DIR), [])


class FlagFirstRules(unittest.TestCase):
    def test_twin_of_each_tool_rule(self):
        self.assertEqual(validate.flag_first_twin("Bash(kubectl get *)"), "Bash(kubectl * get *)")
        self.assertEqual(validate.flag_first_twin("Bash(helm uninstall*)"), "Bash(helm * uninstall*)")
        self.assertEqual(validate.flag_first_twin("Bash(terraform plan*)"), "Bash(terraform -chdir=* plan*)")
        self.assertIsNone(validate.flag_first_twin("Bash(kubectl * get *)"))
        self.assertIsNone(validate.flag_first_twin("Bash(git status*)"))

    def test_missing_twin_is_reported(self):
        permissions = {"deny": ["Bash(kubectl delete ns *)"], "allow": ["Bash(kubectl get *)", "Bash(kubectl * get *)"]}
        self.assertEqual(validate.missing_twins(permissions), ["deny: Bash(kubectl * delete ns *)"])


class StaleReviews(unittest.TestCase):
    def test_old_review_dates_are_reported(self):
        import datetime as dt
        with tempfile.TemporaryDirectory() as tmp:
            kit = Path(tmp)
            (kit / "claude/skills/a").mkdir(parents=True)
            (kit / "claude/skills/a/SKILL.md").write_text("<!-- devops-ai-kit · Last reviewed: 2026-01-01 -->\n")
            (kit / "claude/skills/b").mkdir(parents=True)
            (kit / "claude/skills/b/SKILL.md").write_text("<!-- devops-ai-kit · Last reviewed: 2026-10-01 -->\n")
            (kit / "claude/agents").mkdir(parents=True)
            (kit / "claude/agents/x.md").write_text("no date\n")
            (kit / "claude/skills/b/references").mkdir()
            (kit / "claude/skills/b/references/r.md").write_text("no date, not checked\n")
            stale = validate.stale_reviews(kit, dt.date(2026, 11, 1), 183)
        self.assertEqual(stale, [(Path("claude/agents/x.md"), "no date"), (Path("claude/skills/a/SKILL.md"), "2026-01-01")])

    def test_fail_on_stale_flag(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--stale-days", "0", "--fail-on-stale"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("WARNING claude/", result.stdout)
        result = subprocess.run([sys.executable, str(SCRIPT), "--stale-days", "0"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)  # warnings only


class WholeKit(unittest.TestCase):
    def test_validate_passes_on_this_repo(self):
        result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
