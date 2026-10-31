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


class WholeKit(unittest.TestCase):
    def test_validate_passes_on_this_repo(self):
        result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
