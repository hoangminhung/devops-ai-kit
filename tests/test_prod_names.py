"""Tests for claude/skills/infra-scout/scripts/prod_names.py.

Run: python3 -m unittest discover -s tests -v
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

KIT_DIR = Path(__file__).resolve().parent.parent
SCRIPT = KIT_DIR / "claude" / "skills" / "infra-scout" / "scripts" / "prod_names.py"


def run(*args, pattern=None):
    env = {k: v for k, v in os.environ.items() if k != "DEVOPS_KIT_PROD_PATTERN"}
    if pattern:
        env["DEVOPS_KIT_PROD_PATTERN"] = pattern
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env, timeout=30)


class ProdNames(unittest.TestCase):
    def verdicts(self, result):
        """{name: True when it counts as production}, from lines like `k8s-hn-01   not production`."""
        return {line.split()[0]: not line.endswith("not production") for line in result.stdout.splitlines()[1:]}

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

    def test_bad_pattern(self):
        self.assertEqual(run("--pattern", "(", "x").returncode, 2)


if __name__ == "__main__":
    unittest.main()
