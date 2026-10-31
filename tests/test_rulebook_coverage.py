"""Tests for claude/skills/infra-rulebook/scripts/coverage.py.

A small temp repo has infrastructure files both inside and outside the kit's
default `paths`; the kit's own rule files are used as the rules dir.

Run: python3 -m unittest discover -s tests -v
"""
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

KIT_DIR = Path(__file__).resolve().parent.parent
RULES_DIR = KIT_DIR / "claude" / "rules" / "devops-kit"
SCRIPT = KIT_DIR / "claude" / "skills" / "infra-rulebook" / "scripts" / "coverage.py"

spec = importlib.util.spec_from_file_location("coverage_script", SCRIPT)
coverage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coverage)

K8S_DEPLOYMENT = "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: web\n"
K8S_SERVICE = "apiVersion: v1\nkind: Service\nmetadata:\n  name: web\n"
ARGO_APP = "apiVersion: argoproj.io/v1alpha1\nkind: Application\nmetadata:\n  name: web\n"
PROM_RULE = "apiVersion: monitoring.coreos.com/v1\nkind: PrometheusRule\nmetadata:\n  name: cpu\n"
PLAYBOOK = "- name: Set up hosts\n  hosts: all\n  tasks:\n    - ansible.builtin.ping:\n"

FILES = {
    "infra/main.tf": 'resource "null_resource" "x" {}\n',
    "k8s/base/deployment.yaml": K8S_DEPLOYMENT,
    "deploy/web/deployment.yaml": K8S_DEPLOYMENT,
    "deploy/web/service.yml": K8S_SERVICE,
    "deploy/api/deployment.yaml": K8S_DEPLOYMENT,
    "charts/web/Chart.yaml": "apiVersion: v2\nname: web\nversion: 0.1.0\n",
    "charts/web/values.yaml": "replicaCount: 1\n",
    "charts/web/templates/deployment.yaml": "apiVersion: apps/v1\nkind: Deployment\n{{- include \"x\" . }}\n",
    "gitops/apps/web-app.yaml": ARGO_APP,
    "ops/setup.yml": PLAYBOOK,
    "ops/inventories/prod/hosts.ini": "[web]\nweb-1\n",
    "Dockerfile": "FROM alpine:3.20\n",
    "monitoring/config.alloy": "logging {}\n",
    "alerts-def/cpu.yaml": PROM_RULE,
    "config/settings.yaml": "debug: true\n",
    "README.md": "# demo\n",
}


class CoverageTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        for rel, content in FILES.items():
            path = self.repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)

    def tearDown(self):
        self.tmp.cleanup()

    def report(self):
        return coverage.build_report(self.repo, RULES_DIR)

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = coverage.main([*args, "--repo", str(self.repo), "--rules-dir", str(RULES_DIR)])
        return code, out.getvalue(), err.getvalue()


class Globs(unittest.TestCase):
    CASES = [
        ("**/*.tf", "main.tf", True),
        ("**/*.tf", "a/b/main.tf", True),
        ("**/*.tf", "main.tfvars", False),
        ("**/k8s/**", "k8s/x.yaml", True),
        ("**/k8s/**", "apps/k8s/a/b.yaml", True),
        ("**/k8s/**", "k8sx/a.yaml", False),
        ("**/*application*.{yaml,yml}", "gitops/my-application.yml", True),
        ("**/*application*.{yaml,yml}", "gitops/my-application.json", False),
        ("deploy/**/*.{yaml,yml}", "deploy/web/a.yaml", True),
        ("deploy/**/*.{yaml,yml}", "deploy/a.yaml", True),
        ("deploy/**/*.{yaml,yml}", "other/deploy/a.yaml", False),
        ("**/Dockerfile.*", "svc/Dockerfile.dev", True),
        ("?.tf", "a.tf", True),
    ]

    def test_glob_translation(self):
        for glob, path, expected in self.CASES:
            with self.subTest(glob=glob, path=path):
                self.assertEqual(bool(coverage.glob_to_regex(glob).match(path)), expected)


class Classification(CoverageTestCase):
    def test_files_are_found_by_content(self):
        r = self.report()
        self.assertEqual(r["terraform"]["files"], 1)
        self.assertEqual(r["kubernetes"]["files"], 5)  # 4 manifests + PrometheusRule
        self.assertEqual(r["helm"]["files"], 3)
        self.assertEqual(r["argocd"]["files"], 1)
        self.assertEqual(r["ansible"]["files"], 2)
        self.assertEqual(r["dockerfile"]["files"], 1)
        self.assertEqual(r["observability"]["files"], 2)

    def test_helm_templates_are_not_counted_as_kubernetes(self):
        r = self.report()
        self.assertNotIn("charts/web/templates/deployment.yaml", r["kubernetes"]["uncovered"])

    def test_plain_yaml_is_ignored(self):
        r = self.report()
        for entry in r.values():
            self.assertNotIn("config/settings.yaml", entry["uncovered"])


class Coverage(CoverageTestCase):
    def test_uncovered_files_are_listed(self):
        r = self.report()
        self.assertEqual(sorted(r["kubernetes"]["uncovered"]),
                         ["alerts-def/cpu.yaml", "deploy/api/deployment.yaml",
                          "deploy/web/deployment.yaml", "deploy/web/service.yml"])
        self.assertEqual(r["argocd"]["uncovered"], ["gitops/apps/web-app.yaml"])
        self.assertEqual(r["ansible"]["uncovered"], ["ops/setup.yml"])
        self.assertEqual(r["terraform"]["uncovered"], [])
        self.assertEqual(r["helm"]["uncovered"], [])

    def test_suggested_paths_are_narrow(self):
        r = self.report()
        self.assertIn("deploy/**/*.{yaml,yml}", r["kubernetes"]["suggested_paths"])
        self.assertEqual(r["argocd"]["suggested_paths"], ["gitops/apps/**/*.{yaml,yml}"])

    def test_same_file_name_gives_a_name_glob(self):
        for app in ("web", "api"):
            path = self.repo / "apps" / app / "app.yaml"
            path.parent.mkdir(parents=True)
            path.write_text(ARGO_APP)
            (self.repo / "apps" / app / "deployment.yaml").write_text(K8S_DEPLOYMENT)
        r = self.report()
        self.assertIn("apps/**/app.yaml", r["argocd"]["suggested_paths"])

    def test_project_rule_counts_as_coverage(self):
        rule = self.repo / ".claude" / "rules" / "devops-kit-paths-kubernetes.md"
        rule.parent.mkdir(parents=True)
        rule.write_text(coverage.emit_rule("kubernetes", ["deploy/**/*.{yaml,yml}"], RULES_DIR))
        r = self.report()
        self.assertTrue(r["kubernetes"]["project_rule"])
        self.assertEqual(r["kubernetes"]["uncovered"], ["alerts-def/cpu.yaml"])


class Emit(CoverageTestCase):
    def test_emitted_rule_round_trips(self):
        text = coverage.emit_rule("kubernetes", ["deploy/**/*.{yaml,yml}"], RULES_DIR)
        rule = self.repo / "rule.md"
        rule.write_text(text)
        self.assertEqual(coverage.read_paths(rule), ["deploy/**/*.{yaml,yml}"])

    def test_emitted_rule_points_to_kit_and_copies_no_standards(self):
        text = coverage.emit_rule("kubernetes", ["deploy/**"], Path.home() / ".claude/rules/devops-kit")
        self.assertIn("read `~/.claude/rules/devops-kit/kubernetes.md`", text)
        self.assertNotIn("**MUST**", text)
        self.assertNotIn("@", text.replace("devops-ai-kit", ""))  # no @import: it does not load files outside the project

    def test_pointer_outside_home_is_absolute(self):
        text = coverage.emit_rule("helm", ["x/**"], Path("/opt/claude/rules/devops-kit"))
        self.assertIn("`/opt/claude/rules/devops-kit/helm.md`", text)

    def test_cli_emit_uses_suggestions_and_keeps_existing_paths(self):
        rule = self.repo / ".claude" / "rules" / "devops-kit-paths-kubernetes.md"
        rule.parent.mkdir(parents=True)
        rule.write_text(coverage.emit_rule("kubernetes", ["manual/**"], RULES_DIR))
        code, out, _ = self.cli("emit", "kubernetes")
        self.assertEqual(code, 0)
        self.assertIn('  - "manual/**"', out)
        self.assertIn('  - "deploy/**/*.{yaml,yml}"', out)

    def test_cli_emit_when_nothing_to_add(self):
        code, _, err = self.cli("emit", "terraform")
        self.assertEqual(code, 1)
        self.assertIn("already covered", err)


class Cli(CoverageTestCase):
    def test_report_json(self):
        code, out, _ = self.cli("report", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["argocd"]["uncovered"], ["gitops/apps/web-app.yaml"])

    def test_report_table(self):
        code, out, _ = self.cli("report")
        self.assertEqual(code, 0)
        self.assertIn("suggested paths: alerts-def/**/*.{yaml,yml}, deploy/**/*.{yaml,yml}", out)
        self.assertIn("- gitops/apps/web-app.yaml", out)

    def test_missing_rules_dir(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = coverage.main(["report", "--repo", str(self.repo), "--rules-dir", str(self.repo / "nope")])
        self.assertEqual(code, 2)
        self.assertIn("rules not found", err.getvalue())


if __name__ == "__main__":
    unittest.main()
