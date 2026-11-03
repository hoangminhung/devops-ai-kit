"""Tests for claude/skills/infra-scout/scripts/prod_names.py.

Run: python3 -m unittest discover -s tests -v
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KIT_DIR = Path(__file__).resolve().parent.parent
SCRIPT = KIT_DIR / "claude" / "skills" / "infra-scout" / "scripts" / "prod_names.py"


def run(*args, pattern=None):
    env = {k: v for k, v in os.environ.items() if k != "DEVOPS_KIT_PROD_PATTERN"}
    if pattern is not None:
        env["DEVOPS_KIT_PROD_PATTERN"] = pattern
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env, timeout=30)


class ProdNames(unittest.TestCase):
    def verdicts(self, result):
        """{name: True when it counts as production}, from lines like `k8s-hn-01   not production`."""
        verdicts = {}
        for line in result.stdout.splitlines()[1:]:
            negative = line.endswith("not production")
            verdicts[line[:-len("not production" if negative else "production")].strip()] = not negative
        return verdicts

    def test_uses_the_hooks_default(self):
        result = run("aks-prod-weu-ro", "k8s-hn-01", "kubeconfig.hetzner-live", "default")
        self.assertEqual(result.returncode, 0)
        self.assertIn("the hook's default", result.stdout)
        self.assertEqual(self.verdicts(result), {"aks-prod-weu-ro": True, "k8s-hn-01": False,
                                                 "kubeconfig.hetzner-live": True, "default": False})

    def test_uses_the_installed_pattern(self):
        result = run("k8s-hn-01", pattern="hn-0")
        self.assertIn("DEVOPS_KIT_PROD_PATTERN", result.stdout)
        self.assertEqual(self.verdicts(result), {"k8s-hn-01": True})

    def test_tries_a_new_pattern(self):
        result = run("--pattern", r"(^|[-_.:/@ ])(prod|live|hn)([-_.:/@ ]|$)", "k8s-hn-01", "live-demo-dev", "stg")
        self.assertEqual(self.verdicts(result), {"k8s-hn-01": True, "live-demo-dev": True, "stg": False})

    def test_names_with_spaces_or_a_leading_dash(self):
        result = run("--", "Production Subscription", "-prod", "Dev Sub")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.verdicts(result), {"Production Subscription": True, "-prod": True, "Dev Sub": False})

    def test_empty_pattern_is_named(self):
        result = run("--", "anything", pattern="")
        self.assertIn("empty, so every name matches", result.stdout)

    def test_missing_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "prod_names.py"
            shutil.copy(SCRIPT, copy)
            result = subprocess.run([sys.executable, str(copy), "--", "x"], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 2)

    def test_bad_pattern(self):
        self.assertEqual(run("--pattern", "(", "x").returncode, 2)


if __name__ == "__main__":
    unittest.main()
