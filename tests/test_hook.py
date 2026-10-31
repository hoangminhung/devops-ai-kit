"""Tests for the infra-context-guard PreToolUse hook.

The hook runs as a subprocess, exactly like Claude Code runs it. A fake
`kubectl` placed first in PATH answers `kubectl config view` so the tests never
touch a real cluster or the real kubeconfig. HOME points to a temp dir so no
real cloud config is read.

Run: python3 -m unittest discover -s tests -v
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KIT_DIR = Path(__file__).resolve().parent.parent
HOOK = KIT_DIR / "claude" / "hooks" / "devops-kit" / "infra-context-guard.py"

FAKE_KUBECTL = """#!/bin/sh
# Fake kubectl: prints "<context>|<namespace>" for `kubectl config view --minify`.
ctx="${FAKE_KUBE_CTX:-dev-cluster}"
prev=""
for arg in "$@"; do
  if [ "$prev" = "--context" ]; then ctx="$arg"; fi
  prev="$arg"
done
printf '%s|%s' "$ctx" "${FAKE_KUBE_NS:-default}"
"""


class HookTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.home = root / "home"
        cls.home.mkdir()
        cls.workdir = root / "work"
        cls.workdir.mkdir()
        bin_dir = root / "bin"
        bin_dir.mkdir()
        kubectl = bin_dir / "kubectl"
        kubectl.write_text(FAKE_KUBECTL)
        kubectl.chmod(kubectl.stat().st_mode | stat.S_IEXEC)
        cls.path = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_hook(self, command, tool="Bash", env=None, raw_input=None, encoding=None):
        environ = {"PATH": self.path, "HOME": str(self.home)}
        if encoding:
            environ["PYTHONIOENCODING"] = encoding
        environ.update(env or {})
        payload = raw_input if raw_input is not None else json.dumps(
            {"tool_name": tool, "tool_input": {"command": command}, "cwd": str(self.workdir)}
        ).encode("utf-8")
        result = subprocess.run([sys.executable, str(HOOK)], input=payload, env=environ,
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def decision(self, command, **kwargs):
        """Return (decision, reason), or (None, None) when the hook stays silent."""
        out = self.run_hook(command, **kwargs)
        if not out.strip():
            return None, None
        data = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(data["hookEventName"], "PreToolUse")
        return data["permissionDecision"], data["permissionDecisionReason"]


class ReadOnlyCommands(HookTestCase):
    READ_ONLY = [
        "kubectl get pods -A",
        "kubectl describe deploy web -n app",
        "kubectl diff -f app.yaml",
        "kubectl apply --dry-run=server -f app.yaml",
        "kubectl rollout status deploy/web",
        "kubectl config get-contexts",
        "kubectl cnpg status pg-main",
        "helm list -A",
        "helm template web ./chart",
        "helm upgrade web ./chart --dry-run",
        "terraform plan -out=tfplan",
        "terraform state list",
        "tofu validate",
        "az aks list -o table",
        "az account show",
        "aws ec2 describe-instances",
        "aws s3 ls s3://bucket",
        "aws s3 cp s3://bucket/file.txt .",
        "gcloud compute instances list",
        "ansible-playbook site.yml --check --diff",
        "argocd app get web",
        "velero backup get",
        "git status",
        "git log --oneline",
        "bash -c 'kubectl get pods'",
        "echo kubectl delete pod web",
    ]

    def test_read_only_commands_pass_silently(self):
        for command in self.READ_ONLY:
            with self.subTest(command=command):
                self.assertEqual(self.decision(command), (None, None))


class ForbiddenCommands(HookTestCase):
    """The settings deny rules match from the start of the command; the hook must deny in any flag order."""

    FORBIDDEN = [
        "kubectl --context prod-x get secret db -o yaml",
        "kubectl -n shop --context x get secrets -ojson",
        "kubectl get secret/db --output=jsonpath={.data.password}",
        "kubectl -o yaml get secret db",
        "kubectl get secret db --template={{.data.password}}",
        "kubectl --context x delete ns shop",
        "kubectl delete namespace/shop",
        "kubectl -n shop delete pvc,pod data",
        "kubectl --context x delete crd widgets.example.com",
        "oc --context x delete pv pv-1",
        "helm --kube-context x uninstall web",
        "helm -n monitoring delete mon",
        "terraform -chdir=envs/prod destroy",
        "tofu apply -destroy",
        "az --subscription s keyvault secret show --vault-name v -n db",
        "aws --profile p secretsmanager get-secret-value --secret-id db",
        "gcloud --project p secrets versions access latest --secret db",
        "bash -c 'kubectl --context x delete pvc data'",
        "kubectl get pods && kubectl --context x delete ns shop",
    ]
    ALLOWED = [
        "kubectl get secret -o name",
        "kubectl --context x get secrets -o wide",
        "kubectl get secretstores -o yaml",
        "kubectl --context x describe secret db",
        "terraform -chdir=envs/prod plan -destroy",
    ]

    def test_denied_in_any_flag_order(self):
        for command in self.FORBIDDEN:
            with self.subTest(command=command):
                decision, reason = self.decision(command)
                self.assertEqual(decision, "deny")
                self.assertIn("devops-ai-kit: blocked:", reason)

    def test_secret_names_and_destroy_plans_are_not_denied(self):
        for command in self.ALLOWED:
            with self.subTest(command=command):
                self.assertNotEqual(self.decision(command)[0], "deny")

    def test_secret_deny_points_to_describe(self):
        self.assertIn("kubectl describe secret", self.decision("kubectl get secret db -o yaml")[1])

    def test_every_settings_deny_rule_is_denied_with_a_flag_first(self):
        settings = json.loads((KIT_DIR / "claude" / "settings.devops-kit.json").read_text(encoding="utf-8"))
        flags = {"kubectl": "--context prod-x", "helm": "--kube-context prod-x", "terraform": "-chdir=envs/prod",
                 "tofu": "-chdir=envs/prod", "az": "--subscription s", "aws": "--profile p", "gcloud": "--project p"}
        for rule in settings["permissions"]["deny"]:
            if not rule.startswith("Bash(") or rule.startswith(("Bash(rm ", "Bash(git ")):
                continue
            tool, _, rest = rule[5:-1].partition(" ")
            if rest.startswith(("* ", "-chdir=")):
                continue  # flag-first twin of another rule
            command = f"{tool} {flags[tool]} " + " ".join(rest.replace("*", " x ").split())
            with self.subTest(rule=rule, command=command):
                self.assertEqual(self.decision(command)[0], "deny")


class MakeTargets(HookTestCase):
    def test_mutating_target_shows_variables_and_production(self):
        decision, reason = self.decision("make apply e=prod")
        self.assertEqual(decision, "ask")
        self.assertIn("make apply e=prod", reason)
        self.assertIn("PRODUCTION", reason)

    def test_directory_flag(self):
        self.assertIn("terraform", self.decision("make -C terraform deploy-dev")[1])

    def test_read_only_targets_and_dry_run_pass(self):
        for command in ("make plan e=prod", "make -n apply", "make lint test", "make --dry-run deploy"):
            with self.subTest(command=command):
                self.assertEqual(self.decision(command), (None, None))


class MutatingCommands(HookTestCase):
    def assert_ask(self, command, *expected, **kwargs):
        decision, reason = self.decision(command, **kwargs)
        self.assertEqual(decision, "ask", f"{command!r} should ask")
        self.assertTrue(reason.startswith("devops-ai-kit: "), reason)
        for text in expected:
            self.assertIn(text, reason)
        return reason

    def test_kubectl_shows_context_and_namespace(self):
        self.assert_ask("kubectl delete pod web-1 -n app", "context=dev-cluster", "namespace=app")

    def test_kubectl_uses_current_namespace_from_kubeconfig(self):
        self.assert_ask("kubectl scale deploy/web --replicas=0", "namespace=monitoring",
                        env={"FAKE_KUBE_NS": "monitoring"})

    def test_kubectl_all_namespaces(self):
        self.assert_ask("kubectl delete pods -A -l app=web", "namespace=ALL namespaces")

    def test_kubectl_rollout_and_config_changes(self):
        self.assert_ask("kubectl rollout restart deploy/web", "rollout restart")
        self.assert_ask("kubectl config use-context other", "changes the local kubeconfig selection")

    def test_kubectl_plugin_write(self):
        self.assert_ask("kubectl cnpg promote pg-main 2", "cnpg promote")

    def test_production_context_is_marked(self):
        reason = self.assert_ask("kubectl --context aks-prod-weu rollout restart deploy/web", "context=aks-prod-weu")
        self.assertIn("PRODUCTION", reason)

    def test_read_only_ai_context_is_marked(self):
        reason = self.assert_ask("kubectl delete pod web-1", env={"FAKE_KUBE_CTX": "aks-prod-weu-ro"})
        self.assertIn("read-only AI context", reason)
        self.assertNotIn("PRODUCTION", reason)

    def test_helm(self):
        self.assert_ask("helm upgrade --install mon prometheus-community/kube-prometheus-stack -n monitoring",
                        "helm upgrade mon", "namespace=monitoring")
        self.assert_ask("helm rollback web 2 --kube-context kind-dev", "context=kind-dev")

    def test_terraform_and_tofu(self):
        self.assert_ask("terraform apply tfplan", "terraform apply", "workspace=default")
        self.assert_ask("terraform apply -auto-approve", "[auto-approve]")
        self.assert_ask("terraform state rm module.db", "state rm")
        self.assert_ask("terraform -chdir=envs/prod apply", "apply", "envs")
        self.assert_ask("tofu import aws_s3_bucket.b my-bucket", "tofu import")

    def test_terraform_workspace_from_env(self):
        reason = self.assert_ask("TF_WORKSPACE=prod terraform apply", "workspace=prod")
        self.assertIn("PRODUCTION", reason)

    def test_cloud_clis(self):
        self.assert_ask("az group delete -n rg-test --yes", "az group delete", "subscription=unknown")
        self.assert_ask("az aks get-credentials -g rg -n aks1", "get-credentials", "resource-group=rg")
        self.assert_ask("aws ec2 terminate-instances --instance-ids i-1 --profile dev", "profile=dev")
        self.assert_ask("aws s3 cp file.txt s3://bucket/", "aws s3 cp")
        self.assert_ask("aws s3 rm s3://bucket/file.txt", "aws s3 rm")
        self.assert_ask("gcloud container clusters delete c1 --project demo-123", "project=demo-123")

    def test_ansible_playbook(self):
        self.assert_ask("ansible-playbook -i inventories/stg site.yml -l web",
                        "inventory=inventories/stg", "limit=web")
        self.assert_ask("ansible-playbook site.yml", "limit=ALL hosts in play")

    def test_gitops_tools(self):
        self.assert_ask("argocd app sync web", "argocd app sync web")
        self.assert_ask("velero restore create --from-backup daily", "velero restore create")

    def test_git_push(self):
        self.assert_ask("git push origin main", "remote=origin", "branch=main")
        self.assert_ask("git push --force origin main", "[FORCE]")

    def test_psql_hides_password(self):
        reason = self.assert_ask("psql postgresql://app:S3cret@db.example:5432/app -c 'select 1'", "psql")
        self.assertNotIn("S3cret", reason)
        self.assertIn("***@", reason)

    def test_bash_dash_c_is_unwrapped(self):
        self.assert_ask("bash -c 'kubectl delete pod tmp'", "kubectl delete pod")
        self.assert_ask("sh -c \"helm rollback web 3\"", "helm rollback web")

    def test_wrappers_and_env_assignments(self):
        self.assert_ask("sudo KUBECONFIG=/tmp/x kubectl apply -f app.yaml", "kubectl apply")
        self.assert_ask("timeout 60 terraform apply", "terraform apply")

    def test_chained_commands_report_each_mutation(self):
        reason = self.assert_ask("kubectl get pods && kubectl delete pod web-1; helm rollback web 2",
                                 "kubectl delete pod", "helm rollback web")
        self.assertEqual(reason.count(" | "), 1)


class KubeconfigName(HookTestCase):
    """Many clusters name their only context "default"; the kubeconfig file name is then the real target."""

    def reason(self, command, **kwargs):
        decision, reason = self.decision(command, env={"FAKE_KUBE_CTX": "default", **kwargs.pop("env", {})}, **kwargs)
        self.assertEqual(decision, "ask", command)
        return reason

    def test_kubeconfig_flag_is_shown(self):
        reason = self.reason("kubectl --kubeconfig /x/kubeconfig.azure-sandbox delete pod web-1")
        self.assertIn("kubeconfig=kubeconfig.azure-sandbox", reason)
        self.assertNotIn("PRODUCTION", reason)

    def test_production_detected_from_kubeconfig_name(self):
        reason = self.reason("kubectl --kubeconfig ./kubeconfig.hetzner-live delete pod web-1")
        self.assertIn("PRODUCTION", reason)

    def test_exported_kubeconfig_applies_to_later_segments(self):
        reason = self.reason("export KUBECONFIG=$PWD/kubeconfig.hetzner-live; kubectl -n app delete pod web-1")
        self.assertIn("kubeconfig=kubeconfig.hetzner-live", reason)
        self.assertIn("PRODUCTION", reason)

    def test_inline_kubeconfig_assignment(self):
        reason = self.reason("KUBECONFIG=~/lea/kubeconfig.azure-live kubectl apply -f app.yaml")
        self.assertIn("kubeconfig=kubeconfig.azure-live", reason)
        self.assertIn("PRODUCTION", reason)

    def test_kubeconfig_from_session_environment(self):
        reason = self.reason("helm rollback web 2", env={"KUBECONFIG": "/k/kubeconfig.hetzner-live"})
        self.assertIn("kubeconfig=kubeconfig.hetzner-live", reason)
        self.assertIn("PRODUCTION", reason)

    def test_helm_kubeconfig_flag(self):
        reason = self.reason("helm upgrade web ./chart --kubeconfig kubeconfig.azure-live")
        self.assertIn("PRODUCTION", reason)

    def test_default_kubeconfig_is_not_shown(self):
        reason = self.reason("kubectl delete pod web-1")
        self.assertNotIn("kubeconfig=", reason)

    def test_blocked_on_production_kubeconfig(self):
        decision, _ = self.decision("export KUBECONFIG=./kubeconfig.hetzner-live && kubectl delete ns tmp",
                                    env={"FAKE_KUBE_CTX": "default", "DEVOPS_KIT_BLOCK_PROD": "1"})
        self.assertEqual(decision, "deny")


class PowerShellAndWindows(HookTestCase):
    def assert_ask(self, command, *expected, tool="PowerShell"):
        out = self.run_hook(command, tool=tool)
        self.assertTrue(out.strip(), f"{command!r} should ask")
        data = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(data["permissionDecision"], "ask")
        for text in expected:
            self.assertIn(text, data["permissionDecisionReason"])

    def test_windows_exe_path(self):
        self.assert_ask(r"C:\tools\kubectl.exe delete pod web-1 -n app", "kubectl delete pod", "namespace=app")

    def test_call_operator(self):
        self.assert_ask(r"& 'C:\Program Files\Helm\helm.exe' upgrade web .\chart -n app", "helm upgrade web")

    def test_powershell_terraform(self):
        self.assert_ask(r"terraform.exe -chdir=envs\dev apply", "terraform apply")

    def test_powershell_read_only(self):
        self.assertEqual(self.run_hook(r"C:\tools\kubectl.exe get pods -A", tool="PowerShell").strip(), b"")

    def test_bash_tool_with_windows_path(self):
        self.assert_ask(r"/c/tools/kubectl.exe apply -f app.yaml", "kubectl apply", tool="Bash")


class EncodingAndSwitches(HookTestCase):
    def test_output_is_ascii_on_cp1252_console(self):
        command = "kubectl --context aks-prod-weu delete pod web-1  # xóa pod lỗi"
        out = self.run_hook(command, encoding="cp1252")
        out.decode("ascii")  # raises if any byte is not ASCII
        reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("PRODUCTION", reason)

    def test_non_utf8_input_does_not_crash(self):
        bad = b'{"tool_name": "Bash", "tool_input": {"command": "kubectl delete pod \xff"}}'
        out = self.run_hook(None, raw_input=bad)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_block_prod_denies_production(self):
        decision, reason = self.decision("kubectl --context aks-prod-weu delete pod web-1",
                                         env={"DEVOPS_KIT_BLOCK_PROD": "1"})
        self.assertEqual(decision, "deny")
        self.assertIn("DEVOPS_KIT_BLOCK_PROD=1", reason)

    def test_block_prod_still_asks_for_non_production(self):
        decision, _ = self.decision("kubectl delete pod web-1", env={"DEVOPS_KIT_BLOCK_PROD": "1"})
        self.assertEqual(decision, "ask")

    def test_custom_prod_pattern(self):
        _, reason = self.decision("kubectl --context customer-a delete pod x",
                                  env={"DEVOPS_KIT_PROD_PATTERN": "customer-a"})
        self.assertIn("PRODUCTION", reason)

    def test_guard_off(self):
        self.assertEqual(self.decision("kubectl delete pod web-1", env={"DEVOPS_KIT_GUARD_OFF": "1"}),
                         (None, None))

    def test_other_tools_are_ignored(self):
        self.assertEqual(self.decision("kubectl delete pod web-1", tool="Read"), (None, None))

    def test_invalid_json_fails_open(self):
        self.assertEqual(self.run_hook(None, raw_input=b"not json"), b"")


if __name__ == "__main__":
    unittest.main()
