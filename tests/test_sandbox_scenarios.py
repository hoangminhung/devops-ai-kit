"""Tests for sandbox/ and scenarios/: file format, traps, fixture, prepare.sh and lib.sh.

These tests need no cluster and no Claude session.
Run: python3 -m unittest discover -s tests -v
"""
import csv
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
    def test_every_scenario_is_listed_in_the_readme(self):
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
        bait = next(d for d in docs if "name: grafana-notes" in d)  # prompt-injection bait for scenario 12
        self.assertIn("AI agents reading this", bait)
        self.assertNotIn("AI agents", next(d for d in docs if "name: grafana\n" in d))
        self.assertNotIn("NetworkPolicy", kinds)
        for doc in docs:
            if re.search(r"(?m)^kind: Deployment", doc):
                self.assertIn("replicas: 0", doc)  # no image pull needed


class Fixture(unittest.TestCase):
    def test_injected_readme_keeps_the_sample_readme(self):
        text = (SCENARIOS / "fixtures/injected-readme/README.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith((SANDBOX / "repo/README.md").read_text(encoding="utf-8")))
        self.assertIn("-auto-approve", text)

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
            fh.write("\n".join(e if isinstance(e, str) else json.dumps(e) for e in self.EVENTS) + "\n")
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
        self.assertEqual(json.loads(self.run_lib("metrics"))["prompts"], 1)

    @unittest.skipUnless(shutil.which("jq"), "jq not installed")
    def test_metrics_count_subagent_denials(self):
        denied = {"type": "tool_result", "is_error": True, "content": "Permission to use Bash has been denied."}
        blocked = {"type": "tool_result", "is_error": True, "content": "devops-ai-kit: blocked: kubectl delete ns"}
        self.EVENTS = [{"type": "user", "parent_tool_use_id": "t1", "message": {"content": [denied, blocked, denied]}},
                       {"type": "result", "result": "x", "permission_denials": []}]
        self.assertEqual(json.loads(self.run_lib("metrics"))["prompts"], 3)

    @unittest.skipUnless(shutil.which("jq"), "jq not installed")
    def test_a_non_json_line_in_the_log_does_not_break_the_helpers(self):
        self.EVENTS = [*Lib.EVENTS[:1], "warning: not json", *Lib.EVENTS[1:]]
        self.assertEqual(self.run_lib("final_text"), "Stopped at GATE 1.")
        self.assertEqual(json.loads(self.run_lib("metrics"))["prompts"], 1)
        self.assertIn("make apply e=prod", self.run_lib("denied_tools"))


class Benchmark(unittest.TestCase):
    FAKE_CLAUDE = """#!/bin/sh
cat > /dev/null
echo '{"type":"assistant","message":{"usage":{"input_tokens":10,"cache_creation_input_tokens":1000,"cache_read_input_tokens":0},"content":[{"type":"text","text":"hi"}]}}'
echo '{"type":"result","result":"done","total_cost_usd":0.25,"num_turns":3,"permission_denials":[{"tool_name":"Bash","tool_input":{"command":"x"}}]}'
"""

    def refuse(self, home, config_dir):
        env = dict(os.environ, HOME=home)
        env.pop("CLAUDE_CONFIG_DIR", None)
        return subprocess.run([str(SCENARIOS / "benchmark.sh"), "--config-dir", config_dir],
                              env=env, capture_output=True, text=True, timeout=60)

    def test_refuses_the_real_config_dir_also_through_links_and_nesting(self):
        with tempfile.TemporaryDirectory() as home:
            Path(home, ".claude/sub").mkdir(parents=True)
            Path(home, "link").symlink_to(Path(home, ".claude"))
            for config_dir in (f"{home}/.claude", f"{home}/link", f"{home}/.claude/sub", home):
                with self.subTest(config_dir=config_dir):
                    result = self.refuse(home, config_dir)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("refusing to use your real Claude config dir", result.stderr)

    @unittest.skipUnless(shutil.which("jq"), "jq not installed")
    def test_runs_both_modes_and_writes_a_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            claude = Path(tmp, "claude")
            claude.write_text(self.FAKE_CLAUDE)
            claude.chmod(0o755)
            bench = Path(tmp, "bench")
            bench.mkdir()
            out = Path(tmp, "result.md")
            env = dict(os.environ, HOME=tmp, CLAUDE_BIN=str(claude))
            env.pop("CLAUDE_CONFIG_DIR", None)
            result = subprocess.run([str(SCENARIOS / "benchmark.sh"), "--config-dir", str(bench),
                                     "--models", "fake", "--scenarios", "05 01", "--out", str(out)],
                                    env=env, capture_output=True, text=True, timeout=300)
            self.assertEqual(result.returncode, 0, result.stderr)
            table = out.read_text()
            tsv = out.with_suffix(".tsv").read_text().splitlines()
            self.assertFalse((bench / ".devops-kit-manifest.json").exists())  # uninstalled at the end
        runs = Path(re.search(r"Work copies and logs: (\S+)", result.stderr).group(1))
        try:
            self.assertFalse(str(runs).startswith(str(Path.home())))  # outside $HOME: no parent CLAUDE.md
            copies = sorted(runs.glob("05-*/repo"))
            self.assertEqual(len(copies), 2)
            self.assertFalse((copies[0] / ".claude/skills").exists())  # baseline: no kit skill copied
        finally:
            shutil.rmtree(runs, ignore_errors=True)
        self.assertEqual(len(tsv), 5)  # header + 2 modes x 2 scenarios
        self.assertIn("| scenarios passed |", table)
        self.assertIn("| 01 | skip | skip |", table)  # cluster scenario while the sandbox is down
        self.assertIn("1 prompts · $0.25", table)
        self.assertIn("| context of the first request (avg tokens) | 1010 | 1010 |", table)
        self.assertIn("Kit version: ", table)

    @unittest.skipUnless(shutil.which("jq"), "jq not installed")
    def test_stops_and_uninstalls_on_term(self):
        with tempfile.TemporaryDirectory() as tmp:
            claude = Path(tmp, "claude")
            claude.write_text("#!/bin/sh\ncat > /dev/null\nsleep 4\n")
            claude.chmod(0o755)
            bench = Path(tmp, "bench")
            bench.mkdir()
            out = Path(tmp, "result.md")
            env = dict(os.environ, HOME=tmp, CLAUDE_BIN=str(claude))
            env.pop("CLAUDE_CONFIG_DIR", None)
            proc = subprocess.Popen([str(SCENARIOS / "benchmark.sh"), "--config-dir", str(bench), "--models", "fake",
                                     "--scenarios", "05", "--out", str(out)], env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            tsv = out.with_suffix(".tsv")
            for _ in range(100):  # wait until the kit run has started
                if (bench / ".devops-kit-manifest.json").exists() or proc.poll() is not None:
                    break
                import time
                time.sleep(0.2)
            import signal
            proc.send_signal(signal.SIGTERM)
            proc.communicate(timeout=60)
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(out.exists())
            self.assertFalse((bench / ".devops-kit-manifest.json").exists())
            lines = tsv.read_text().splitlines() if tsv.exists() else []
            self.assertFalse(any(line.startswith("kit\t") for line in lines))

    def test_unknown_scenario_is_refused_before_spending(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "bench").mkdir()
            env = dict(os.environ, HOME=tmp)
            env.pop("CLAUDE_CONFIG_DIR", None)
            result = subprocess.run([str(SCENARIOS / "benchmark.sh"), "--config-dir", f"{tmp}/bench", "--scenarios", "99"],
                                    env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown scenario: 99", result.stderr)


class Continuity(unittest.TestCase):
    """continuity.sh with a fake claude: it does the task, retries --inplace once per later part,
    writes PROGRESS.md when /handoff is confirmed, and marks /compact (unless FAKE_NO_COMPACT is set)."""
    FAKE_CLAUDE = r"""#!/usr/bin/env bash
prompt="$(cat)"
emit() { printf '%s\n' "$1"; }
bash_use() { emit "{\"type\":\"assistant\",\"message\":{\"content\":[{\"type\":\"tool_use\",\"name\":\"Bash\",\"input\":{\"command\":\"$1\"}}]}}"; }
emit '{"type":"system","subtype":"init","session_id":"s-'"$RANDOM"'"}'
case "$prompt" in
  /compact) [[ -n "${FAKE_NO_COMPACT:-}" ]] || emit '{"type":"system","subtype":"compact_boundary"}' ;;
  "Yes, write it.") printf '# PROGRESS\n' > PROGRESS.md ;;
  /handoff) ;;
  *)
    bash_use "tools/bump-tag.sh x 1 --inplace"
    if [[ "$prompt" == We\ release* ]]; then tools/bump-tag.sh api 1.4.2 --patch >/dev/null
    elif grep -q '"2.0.0"' release/tags.yaml; then tools/bump-tag.sh web 2.0.1 --patch >/dev/null
    else tools/bump-tag.sh worker 0.9.7 --patch >/dev/null; fi ;;
esac
emit '{"type":"result","result":"ok","total_cost_usd":0.5,"usage":{"input_tokens":100,"output_tokens":10,"cache_read_input_tokens":0}}'
"""

    def run_continuity(self, tmp, **env_extra):
        claude = Path(tmp, "claude")
        claude.write_text(self.FAKE_CLAUDE)
        claude.chmod(0o755)
        tsv = Path(tmp, "c.tsv")
        env = dict(os.environ, CLAUDE_BIN=str(claude), SCENARIO_RUNS_DIR=str(Path(tmp, "runs")), **env_extra)
        result = subprocess.run([str(SCENARIOS / "continuity.sh"), "--runs", "1", "--tsv", str(tsv)],
                                env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(tsv, encoding="utf-8") as fh:
            return {row["method"]: row for row in csv.DictReader(fh, delimiter="\t")}

    @unittest.skipUnless(shutil.which("jq"), "jq not installed")
    def test_measures_both_methods(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = self.run_continuity(tmp)
            report = load("continuity_report", SCENARIOS / "continuity_report.py").report(list(rows.values()), "x")
        for method, calls in (("compact", 5), ("handoff", 7)):
            with self.subTest(method=method):
                row = rows[method]
                self.assertEqual((row["valid"], row["planted"], row["retries"], row["next_ok"]), ("yes", "yes", "2", "2"))
                self.assertEqual(int(row["tokens"]), 110 * calls)
        self.assertIn("| parts 2–3 that did the right next step | 2 / 2 | 2 / 2 |", report)
        self.assertIn("| dead-end retries in parts 2–3 (total) | 2 | 2 |", report)

    @unittest.skipUnless(shutil.which("jq"), "jq not installed")
    def test_a_compact_that_did_not_run_makes_the_run_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = self.run_continuity(tmp, FAKE_NO_COMPACT="1")
            report = load("continuity_report", SCENARIOS / "continuity_report.py").report(list(rows.values()))
        self.assertTrue(rows["compact"]["valid"].startswith("no (no compact_boundary"))
        self.assertEqual(rows["handoff"]["valid"], "yes")
        self.assertIn("| valid runs | 0 / 1 | 1 / 1 |", report)

    @unittest.skipUnless(shutil.which("jq"), "jq not installed")
    def test_benchmark_continuity_installs_runs_reports_and_uninstalls(self):
        with tempfile.TemporaryDirectory() as tmp:
            claude = Path(tmp, "claude")
            claude.write_text(self.FAKE_CLAUDE)
            claude.chmod(0o755)
            bench = Path(tmp, "bench")
            bench.mkdir()
            out = Path(tmp, "result.md")
            env = dict(os.environ, HOME=tmp, CLAUDE_BIN=str(claude))
            env.pop("CLAUDE_CONFIG_DIR", None)
            result = subprocess.run([str(SCENARIOS / "benchmark.sh"), "--config-dir", str(bench), "--continuity",
                                     "--runs", "1", "--models", "fake", "--out", str(out)],
                                    env=env, capture_output=True, text=True, timeout=300)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = out.read_text()
            self.assertFalse((bench / ".devops-kit-manifest.json").exists())  # uninstalled at the end
            self.assertFalse(out.with_suffix(".tsv").exists())  # no empty without/with-kit table
        runs = Path(re.search(r"Work copies and logs: (\S+)", result.stderr).group(1))
        shutil.rmtree(runs, ignore_errors=True)
        self.assertIn("Model: fake.", report)
        self.assertIn("| valid runs | 1 / 1 | 1 / 1 |", report)

    def test_bad_arguments_are_refused_before_spending(self):
        for args in (["--runs", "0", "--tsv", "x"], ["--methods", "magic", "--tsv", "x"], []):
            with self.subTest(args=args):
                result = subprocess.run([str(SCENARIOS / "continuity.sh"), *args], capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)

    def test_fixture_dead_end_always_fails_and_patch_changes_one_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(SCENARIOS / "fixtures/continuity", tmp, dirs_exist_ok=True)
            before = Path(tmp, "release/tags.yaml").read_text()
            failed = subprocess.run(["tools/bump-tag.sh", "api", "1.4.2", "--inplace"], cwd=tmp, capture_output=True, text=True)
            self.assertEqual((failed.returncode, Path(tmp, "release/tags.yaml").read_text()), (3, before))
            subprocess.run(["tools/bump-tag.sh", "web", "2.0.1", "--patch"], cwd=tmp, check=True, capture_output=True)
            after = Path(tmp, "release/tags.yaml").read_text()
        changed = [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
        self.assertEqual(changed, [('    tag: "2.0.0"', '    tag: "2.0.1"')])
        self.assertIn("--inplace", (SCENARIOS / "fixtures/continuity/docs/RELEASE.md").read_text())


if __name__ == "__main__":
    unittest.main()
