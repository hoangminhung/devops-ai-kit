"""Tests for scripts/kit.py (install / uninstall / check).

Each test gets a fresh temp HOME, so the real ~/.claude is never touched. The
starting state is a user who already has their own settings.json and their own
agent file with the same name as one of the kit's agents.

Run: python3 -m unittest discover -s tests -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KIT_DIR = Path(__file__).resolve().parent.parent
KIT = KIT_DIR / "scripts" / "kit.py"

# Hand-formatted on purpose: uninstall must give back these exact bytes.
USER_SETTINGS = b'{\n    "model": "opus",\n    "permissions": {"allow": ["Bash(ls:*)"]}\n}\n'
USER_AGENT = b"---\nname: infra-recon\ndescription: my own agent\n---\n"


def snapshot(root):
    """{relative path: bytes or None for dirs} of everything under root."""
    return {str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None)
            for p in sorted(root.rglob("*"))}


class InstallerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.claude = self.home / ".claude"
        (self.claude / "agents").mkdir(parents=True)
        (self.claude / "settings.json").write_bytes(USER_SETTINGS)
        (self.claude / "agents" / "infra-recon.md").write_bytes(USER_AGENT)

    def tearDown(self):
        self.tmp.cleanup()

    def kit(self, *args, check=True):
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
        env["HOME"] = str(self.home)
        env["USERPROFILE"] = str(self.home)
        result = subprocess.run([sys.executable, str(KIT), *args], env=env,
                                capture_output=True, text=True, timeout=60)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def settings(self):
        return json.loads((self.claude / "settings.json").read_text(encoding="utf-8"))

    def manifest(self):
        return json.loads((self.claude / ".devops-kit-manifest.json").read_text(encoding="utf-8"))

    def language_rule(self):
        return (self.claude / "rules" / "devops-kit" / "01-language.md").read_bytes()

    def lang_source(self, lang):
        return (KIT_DIR / "claude" / "lang" / f"{lang}.md").read_bytes()


class DryRun(InstallerTestCase):
    def test_dry_run_writes_nothing(self):
        before = snapshot(self.home)
        out = self.kit("install", "--dry-run", "--lang", "vi", "--env", "KUBECONFIG=~/.kube/ai-config").stdout
        self.assertIn("[dry-run]", out)
        self.assertEqual(snapshot(self.home), before)

    def test_uninstall_dry_run_writes_nothing(self):
        self.kit("install")
        before = snapshot(self.home)
        self.kit("uninstall", "--dry-run")
        self.assertEqual(snapshot(self.home), before)


class Install(InstallerTestCase):
    def test_install_copies_kit_and_language_rule(self):
        self.kit("install", "--lang", "vi")
        self.assertTrue((self.claude / "rules" / "devops-kit" / "00-core.md").exists())
        self.assertTrue((self.claude / "skills" / "infra-task" / "SKILL.md").exists())
        self.assertTrue(os.access(self.claude / "hooks" / "devops-kit" / "infra-context-guard.py", os.X_OK))
        self.assertEqual(self.language_rule(), self.lang_source("vi"))
        self.assertEqual(self.manifest()["lang"], "vi")

    def test_default_language_is_english(self):
        self.kit("install")
        self.assertEqual(self.language_rule(), self.lang_source("en"))

    def test_existing_agent_is_backed_up(self):
        self.kit("install")
        kit_agent = (KIT_DIR / "claude" / "agents" / "infra-recon.md").read_bytes()
        self.assertEqual((self.claude / "agents" / "infra-recon.md").read_bytes(), kit_agent)
        backups = list((self.claude / ".devops-kit-backup").glob("*/agents/infra-recon.md"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), USER_AGENT)

    def test_settings_are_merged_not_replaced(self):
        self.kit("install", "--env", "KUBECONFIG=~/.kube/ai-config")
        settings = self.settings()
        self.assertEqual(settings["model"], "opus")
        self.assertIn("Bash(ls:*)", settings["permissions"]["allow"])
        self.assertTrue(settings["permissions"].get("deny"))
        hooks = [h["command"] for e in settings["hooks"]["PreToolUse"] for h in e["hooks"]]
        self.assertTrue(any("infra-context-guard.py" in c for c in hooks))
        self.assertEqual(settings["env"]["KUBECONFIG"], str(self.home / ".kube" / "ai-config"))

    def test_no_settings_flag_leaves_settings_alone(self):
        self.kit("install", "--no-settings")
        self.assertEqual((self.claude / "settings.json").read_bytes(), USER_SETTINGS)

    def test_invalid_settings_json_stops_before_any_change(self):
        (self.claude / "settings.json").write_text("{ not json")
        result = self.kit("install", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not valid JSON", result.stdout + result.stderr)
        self.assertEqual((self.claude / "settings.json").read_text(), "{ not json")
        self.assertFalse((self.claude / ".devops-kit-manifest.json").exists())


class Reinstall(InstallerTestCase):
    def test_reinstall_keeps_language_and_env(self):
        self.kit("install", "--lang", "vi", "--env", "KUBECONFIG=~/.kube/ai-config")
        self.kit("install")
        self.assertEqual(self.language_rule(), self.lang_source("vi"))
        self.assertEqual(self.manifest()["lang"], "vi")
        self.assertEqual(self.settings()["env"]["KUBECONFIG"], str(self.home / ".kube" / "ai-config"))

    def test_reinstall_can_change_language(self):
        self.kit("install", "--lang", "vi")
        self.kit("install", "--lang", "en")
        self.assertEqual(self.language_rule(), self.lang_source("en"))

    def test_reinstall_does_not_duplicate_settings(self):
        self.kit("install")
        first = self.settings()
        self.kit("install")
        self.assertEqual(self.settings(), first)

    def test_reinstall_does_not_back_up_kit_files(self):
        self.kit("install")
        self.kit("install")
        backups = list((self.claude / ".devops-kit-backup").glob("*/agents/infra-recon.md"))
        self.assertEqual(len(backups), 1)

    def test_check_shows_language(self):
        self.kit("install", "--lang", "vi")
        out = self.kit("check", check=False).stdout
        self.assertIn("Output language   : vi", out)
        self.assertIn("Context-guard hook: registered", out)


class Uninstall(InstallerTestCase):
    def test_uninstall_restores_settings_byte_for_byte(self):
        self.kit("install", "--lang", "vi", "--env", "KUBECONFIG=~/.kube/ai-config")
        self.kit("install")
        self.kit("uninstall")
        self.assertEqual((self.claude / "settings.json").read_bytes(), USER_SETTINGS)

    def test_uninstall_removes_kit_files(self):
        self.kit("install", "--lang", "vi")
        self.kit("uninstall")
        self.assertFalse((self.claude / "rules").exists())
        self.assertFalse((self.claude / "hooks").exists())
        self.assertFalse((self.claude / "skills").exists())
        self.assertFalse((self.claude / "agents" / "infra-recon.md").exists())
        self.assertFalse((self.claude / ".devops-kit-manifest.json").exists())
        self.assertTrue(any((self.claude / ".devops-kit-backup").rglob("infra-recon.md")))

    def test_uninstall_keeps_user_changes_made_after_install(self):
        self.kit("install")
        settings = self.settings()
        settings["theme"] = "dark"
        (self.claude / "settings.json").write_text(json.dumps(settings))
        self.kit("uninstall")
        self.assertEqual(self.settings(), {"model": "opus", "permissions": {"allow": ["Bash(ls:*)"]}, "theme": "dark"})

    def test_uninstall_removes_settings_created_by_kit(self):
        (self.claude / "settings.json").unlink()
        self.kit("install")
        self.kit("uninstall")
        self.assertFalse((self.claude / "settings.json").exists())

    def test_uninstall_without_install(self):
        result = self.kit("uninstall", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("nothing to uninstall", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
