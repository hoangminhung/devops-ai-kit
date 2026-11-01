"""Tests for claude/skills/pki-secrets/scripts/secret_fingerprint.py.

A fake `kubectl` first in PATH serves Secrets from a JSON file, so no cluster is needed.
Run: python3 -m unittest discover -s tests -v
"""
import base64
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KIT_DIR = Path(__file__).resolve().parent.parent
SCRIPT = KIT_DIR / "claude" / "skills" / "pki-secrets" / "scripts" / "secret_fingerprint.py"

FAKE_KUBECTL = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
ctx = args[args.index("--context") + 1] if "--context" in args else "current"
ns = args[args.index("-n") + 1]
name = args[args.index("secret") + 1]
store = json.load(open(os.environ["FAKE_SECRETS"]))
key = f"{ctx}:{ns}/{name}"
if name == "noisy":
    print('I1101 request.go] Response Body: {"data":{"password":"UzNjcmV0LXZhbHVlLWxvbmctZW5vdWdoLXRvLWN1dA=="}}', file=sys.stderr)
    print('Response Body: {"data":{"password":"UzNjcmV0LXZhbHVlLWxvbmctZW5vdWdoLXRvLWN1dA=="}}', file=sys.stderr)
    print('error: short value UzNjcmV0 in the message', file=sys.stderr)
    sys.exit(1)
if key not in store:
    print(f'Error from server (NotFound): secrets "{name}" not found', file=sys.stderr)
    sys.exit(1)
print(json.dumps({"kind": "Secret", "data": store[key]}))
"""


def b64(text):
    return base64.b64encode(text.encode()).decode()


SECRETS = {
    "prod:shop/db": {"password": b64("S3cret-value"), "user": b64("app"), "ca.crt": b64("-----BEGIN CERTIFICATE-----\nx\n")},
    "stg:shop/db": {"password": b64("S3cret-value\n"), "user": b64("app2"), "extra": b64("")},
    "current:shop/db": {"password": b64("S3cret-value")},
    "current:shop/broken": {"password": "!!!not-base64"},
}


class SecretFingerprint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        kubectl = root / "kubectl"
        kubectl.write_text(FAKE_KUBECTL)
        kubectl.chmod(kubectl.stat().st_mode | stat.S_IEXEC)
        (root / "secrets.json").write_text(json.dumps(SECRETS))
        cls.env = dict(os.environ, PATH=f"{root}{os.pathsep}{os.environ['PATH']}", FAKE_SECRETS=str(root / "secrets.json"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_script(self, *args, env=None):
        result = subprocess.run([sys.executable, str(SCRIPT), *args], env=dict(self.env, **(env or {})),
                                capture_output=True, text=True, timeout=30)
        self.assertNotIn("S3cret", result.stdout + result.stderr)  # never a value
        return result

    def test_describe_shows_keys_sizes_and_kinds(self):
        result = self.run_script("prod:shop/db")
        self.assertEqual(result.returncode, 0)
        self.assertIn("password: 12 bytes, text", result.stdout)
        self.assertIn("ca.crt: 30 bytes, PEM", result.stdout)

    def test_compare_two_secrets(self):
        result = self.run_script("prod:shop/db", "stg:shop/db")
        self.assertEqual(result.returncode, 1)
        self.assertIn("password: differ (only a trailing newline)", result.stdout)
        self.assertIn("user: differ (3 / 4 bytes)", result.stdout)
        self.assertIn("ca.crt: only in prod:shop/db", result.stdout)
        self.assertIn("extra: only in stg:shop/db", result.stdout)

    def test_equal_secrets_exit_zero(self):
        result = self.run_script("prod:shop/db", "shop/db")
        self.assertIn("password: match", result.stdout)
        self.assertEqual(result.returncode, 1)  # user and ca.crt are only in prod
        self.assertEqual(self.run_script("shop/db", "shop/db").returncode, 0)

    def test_compare_with_env_var(self):
        result = self.run_script("prod:shop/db", "--env", "password=EXPECTED", env={"EXPECTED": "S3cret-value"})
        self.assertEqual(result.returncode, 0)
        self.assertIn("password vs $EXPECTED: match", result.stdout)
        result = self.run_script("prod:shop/db", "--env", "password=EXPECTED", env={"EXPECTED": "other"})
        self.assertEqual(result.returncode, 1)
        result = self.run_script("prod:shop/db", "--env", "password=NOT_SET_VAR")
        self.assertIn("env var NOT_SET_VAR is not set", result.stdout)

    def test_context_with_colons_and_slashes(self):
        spec = importlib.util.spec_from_file_location("secret_fingerprint", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.parse_spec("arn:aws:eks:eu-west-1:1:cluster/prod:shop/db"),
                         ("arn:aws:eks:eu-west-1:1:cluster/prod", "shop", "db"))

    def test_errors(self):
        self.assertEqual(self.run_script("not a spec").returncode, 2)
        result = self.run_script("prod:shop/missing")
        self.assertEqual(result.returncode, 2)
        self.assertIn("NotFound", result.stderr)

    def test_names_that_look_like_flags_are_refused(self):
        for spec in ("shop/-v9", "shop/--raw", "-n:shop/db", "-shop/db", "shop/db-"):
            with self.subTest(spec=spec):
                self.assertEqual(self.run_script(spec).returncode, 2)

    def test_bad_base64_is_an_error_not_empty(self):
        result = self.run_script("shop/broken")
        self.assertEqual(result.returncode, 2)
        self.assertIn("not a Secret with base64 data", result.stderr)

    def test_kubectl_errors_do_not_echo_response_bodies(self):
        result = self.run_script("shop/noisy")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("UzNjcmV0", result.stderr)
        self.assertIn("<cut>", result.stderr)


if __name__ == "__main__":
    unittest.main()
