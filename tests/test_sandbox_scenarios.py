"""Tests for sandbox/ and scenarios/: file format, traps, fixture, prepare.sh and lib.sh.

These tests need no cluster and no Claude session.
Run: python3 -m unittest discover -s tests -v
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

KIT_DIR = Path(__file__).resolve().parent.parent
SCENARIOS = KIT_DIR / "scenarios"
SANDBOX = KIT_DIR / "sandbox"
SCENARIO_FILES = sorted(SCENARIOS.glob("[0-9][0-9]-*.md"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def block(text, name):
    match = re.search(rf"^```{name}\n(.*?)^```$", text, re.S | re.M)
    return match.group(1) if match else None


class ScenarioFiles(unittest.TestCase):
    def test_there_are_ten_scenarios_listed_in_the_readme(self):
        self.assertEqual(len(SCENARIO_FILES), 10)
        readme = (SCENARIOS / "README.md").read_text(encoding="utf-8")
        for path in SCENARIO_FILES:
            self.assertIn(f"]({path.name})", readme)

    def test_each_scenario_has_the_required_parts(self):
        for path in SCENARIO_FILES:
            text = path.read_text(encoding="utf-8")
            with self.subTest(scenario=path.name):
                self.assertTrue(text.startswith(f"# {path.name[:2]} — "))
                self.assertRegex(text, r"(?m)^- \*\*Layer:\*\* (repo only|cluster)")
                self.assertIsNotNone(block(text, "prompt"), "missing ```prompt block")
                self.assertRegex(text, r"(?m)^## Expect\n\n(.*\n)*?- \[ \] ")
                self.assertIn("\n## Findings", text)

    def test_fixtures_named_in_scenarios_exist(self):
        for path in SCENARIO_FILES:
            match = re.search(r"(?m)^- \*\*Fixture:\*\* `([a-z0-9-]+)`", path.read_text(encoding="utf-8"))
            if match:
                self.assertTrue((SCENARIOS / "fixtures" / match.group(1)).is_dir(), path.name)

    def test_check_blocks_are_valid_bash(self):
        for path in SCENARIO_FILES:
            check = block(path.read_text(encoding="utf-8"), "check")
            if check is None:
                continue
            with self.subTest(scenario=path.name):
                result = subprocess.run(["bash", "-n"], input=check, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_manual_only_scenario_has_no_check(self):
        text = (SCENARIOS / "04-readonly-context-forbidden.md").read_text(encoding="utf-8")
        self.assertIn("manual only", text)
        self.assertIsNone(block(text, "check"))


class SandboxTraps(unittest.TestCase):
    def test_sample_repo_keeps_uncovered_folders_for_rulebook(self):
        coverage = load("coverage", KIT_DIR / "claude/skills/infra-rulebook/scripts/coverage.py")
        report = coverage.build_report(SANDBOX / "repo", KIT_DIR / "claude/rules/devops-kit")
        self.assertEqual(sorted(report["kubernetes"]["uncovered"]),
                         ["deploy/web/deployment.yaml", "deploy/web/service.yaml"])
        self.assertEqual(report["argocd"]["uncovered"], ["gitops/apps/web/app.yaml"])
        for tech in ("terraform", "ansible", "helm"):
            self.assertGreater(report[tech]["files"], 0, tech)
            self.assertEqual(report[tech]["uncovered"], [], tech)

    def test_sample_repo_needs_no_cloud(self):
        for tf in (SANDBOX / "repo" / "terraform").rglob("*.tf"):
            sources = re.findall(r'source\s*=\s*"hashicorp/(\w+)"', tf.read_text())
            self.assertTrue(set(sources) <= {"local", "random", "null"}, tf)

    def test_cluster_traps(self):
        docs = [d for d in (SANDBOX / "cluster" / "traps.yaml").read_text().split("\n---\n") if "kind:" in d]
        kinds = [re.search(r"(?m)^kind: (\w+)", d).group(1) for d in docs]
        for kind in ("IngressClass", "StorageClass", "PersistentVolumeClaim", "Secret"):
            self.assertIn(kind, kinds)
        text = "\n".join(docs)
        self.assertIn("reclaimPolicy: Delete", text)
        self.assertNotIn("NetworkPolicy", kinds)
        for doc in docs:
            if re.search(r"(?m)^kind: Deployment", doc):
                self.assertIn("replicas: 0", doc)  # no image pull needed


class Fixture(unittest.TestCase):
    def test_resume_fixture_stops_after_step_1(self):
        plan_status = load("plan_status", KIT_DIR / "claude/skills/infra-task/scripts/plan_status.py")
        info = plan_status.status(SCENARIOS / "fixtures/prod-replicas/docs/changes/2026-11-01-prod-replicas")
        self.assertEqual(info["done"], ["1"])
        self.assertEqual(info["next"], "2")


class Prepare(unittest.TestCase):
    def test_prepare_makes_a_committed_copy_with_fixture_and_links_missing_skills(self):
        with tempfile.TemporaryDirectory() as config_dir:
            env = dict(os.environ, CLAUDE_CONFIG_DIR=config_dir)  # empty: nothing installed
            result = subprocess.run([str(SCENARIOS / "prepare.sh"), "08"], env=env,
                                    capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        work = Path(result.stdout.strip().splitlines()[-1])
        try:
            self.assertTrue((work / "terraform/envs/prod/main.tf").exists())
            self.assertIn("replicas = 4", (work / "terraform/envs/prod/terraform.tfvars").read_text())
            self.assertTrue((work / "docs/changes/2026-11-01-prod-replicas/03-plan.md").exists())
            self.assertTrue((work / ".claude/skills/infra-scout/SKILL.md").is_file())
            self.assertFalse((work / ".claude/skills/infra-scout").is_symlink())
            status = subprocess.run(["git", "status", "--porcelain"], cwd=work, capture_output=True, text=True)
            self.assertEqual(status.stdout.strip(), "?? .claude/")
            self.assertIn("Kit tested: installed vnot installed", result.stderr)
        finally:
            shutil.rmtree(work.parent)


class RunHeadless(unittest.TestCase):
    def test_finds_vscode_claude_when_one_extensions_folder_is_missing(self):
        with tempfile.TemporaryDirectory() as home:
            binary = Path(home, ".vscode-server/extensions/anthropic.claude-code-9.9.9-linux-x64/resources/native-binary/claude")
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\nexit 0\n")
            binary.chmod(0o755)
            env = {k: v for k, v in os.environ.items() if k != "CLAUDE_BIN"}
            env.update(HOME=home, PATH="/usr/bin:/bin")  # no `claude` on PATH, no ~/.vscode/extensions
            result = subprocess.run([str(SCENARIOS / "run-headless.sh"), "04"], env=env,
                                    capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("04 SKIP (manual only)", result.stdout)

    def test_clear_error_when_claude_is_missing(self):
        with tempfile.TemporaryDirectory() as home:
            env = {k: v for k, v in os.environ.items() if k != "CLAUDE_BIN"}
            env.update(HOME=home, PATH="/usr/bin:/bin")
            result = subprocess.run([str(SCENARIOS / "run-headless.sh"), "05"], env=env,
                                    capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 1)
        self.assertIn("claude not found", result.stderr)


class Lib(unittest.TestCase):
    EVENTS = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "python3 x/plan_status.py status t"}},
            {"type": "tool_use", "name": "Skill", "input": {"skill": "infra-docs"}},
            {"type": "tool_use", "name": "Agent", "input": {"subagent_type": "infra-reviewer"}},
            {"type": "tool_use", "name": "Write", "input": {"file_path": "/tmp/d.md", "content": "## Environment registry"}}]}},
        {"type": "result", "result": "Stopped at GATE 1.",
         "permission_denials": [{"tool_name": "Bash", "tool_input": {"command": "make apply e=prod"}}]},
    ]

    def run_lib(self, expression):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            fh.write("\n".join(json.dumps(e) for e in self.EVENTS) + "\n")
            log = fh.name
        try:
            result = subprocess.run(["bash", "-c", f"source '{SCENARIOS / 'lib.sh'}'; {expression}"],
                                    env=dict(os.environ, LOG=log), capture_output=True, text=True)
        finally:
            os.unlink(log)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    @unittest.skipUnless(shutil.which("jq"), "jq not installed")
    def test_helpers_read_stream_json(self):
        self.assertEqual(self.run_lib("bash_commands"), "python3 x/plan_status.py status t")
        self.assertEqual(self.run_lib("skills_used"), "infra-docs")
        self.assertEqual(self.run_lib("agents_used"), "infra-reviewer")
        self.assertEqual(self.run_lib("final_text"), "Stopped at GATE 1.")
        self.assertEqual(self.run_lib("written_text"), "## Environment registry")
        self.assertIn("make apply e=prod", self.run_lib("denied_tools"))


if __name__ == "__main__":
    unittest.main()
