"""Tests for the infra-context-guard PreToolUse hook.

The hook runs as a subprocess, exactly like Claude Code runs it. A fake
`kubectl` placed first in PATH answers `kubectl config view` so the tests never
touch a real cluster or the real kubeconfig. HOME points to a temp dir so no
real cloud config is read.

Run: python3 -m unittest discover -s tests -v
"""
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
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
        # Most tests check the "ask" text, so production blocking (on by default) is off here.
        environ = {"PATH": self.path, "HOME": str(self.home), "DEVOPS_KIT_BLOCK_PROD": "0"}
        if encoding:
            environ["PYTHONIOENCODING"] = encoding
        environ.update(env or {})
        environ = {k: v for k, v in environ.items() if v is not None}  # env={"X": None} removes X
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
        "kubectl --context x get --raw /api/v1/namespaces/shop/secrets/db",
        "kubectl get --raw=/api/v1/secrets",
        "curl -s http://127.0.0.1:8001/api/v1/namespaces/shop/secrets/db",
        "wget -qO- http://localhost:8001/api/v1/secrets?limit=1",
        # found by the independent review: short flags joined, value flags, files, encoding, log level
        "kubectl get secrets -Ao yaml",
        "kubectl get secret db -n x -Aojson",
        "kubectl get --sort-by .metadata.name secret db -o yaml",
        "kubectl get -L app secret db -o yaml",
        "kubectl get --chunk-size 10 secret -o yaml",
        "kubectl get --raw /api/v1/namespaces/x/%73ecrets/db",
        "kubectl get -v=0 --raw /api/v1/namespaces/x/secrets#x",
        "kubectl get secret db --sort-by=.metadata.name -v=9",
        "oc extract secret/db --to=-",
        "helm get values web",
        "helm --kube-context x get manifest web",
        "helm status web -o json",
        "curl http://127.0.0.1:8001/api/v1/watch/namespaces/x/secrets",
        "curl http://127.0.0.1:8001/api/v1/namespaces/x/%73ecrets/db",
        # second review round
        "kubectl get -o yaml -- secret db",
        "kubectl get -oyaml -- secrets",
        "helm status web -ojson",
        "helm status web -oyaml -n x",
        "kubectl get -v=0 --raw https://x/api/v1/namespaces/x/secrets/db",
        "kubectl view-secret db --all",
        "kubectl apply view-last-applied secret/db",
        # shell keywords at the start of a segment (third review round)
        "for x in 1; do kubectl get secret db -o yaml; done",
        "if true; then kubectl get secret db -o yaml; fi",
        "{ kubectl get secret db -o yaml; }",
        "(kubectl get secret db -o yaml)",
        "! kubectl get secret db -o yaml",
        "for n in a b; do kubectl --context x delete ns $n; done",
    ]
    ALLOWED = [
        "kubectl get secret -o name",
        "kubectl --context x get secrets -o wide",
        "kubectl get secrets -n mongodb-operator",
        "kubectl get secretstores -o yaml",
        "kubectl --context x describe secret db",
        "terraform -chdir=envs/prod plan -destroy",
        "kubectl get --raw /api/v1/namespaces/shop/pods",
        "kubectl get --raw /apis/secrets-store.csi.x-k8s.io/v1/secretproviderclasses",
        "kubectl get -f deploy.yaml",
        "kubectl get pods -o jsonpath={.items[*].metadata.name}",
        "kubectl get pods -v=9",
        "curl -s http://127.0.0.1:8001/api/v1/namespaces/shop/configmaps",
        "helm status web",
        "helm get notes web",
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

    def test_allowed_commands_are_not_denied_by_settings_either(self):
        """Simulates Claude Code rule matching: `*` matches any text, no `*` at the end means exact."""
        settings = json.loads((KIT_DIR / "claude" / "settings.devops-kit.json").read_text(encoding="utf-8"))
        rules = [re.compile(".*".join(map(re.escape, r[5:-1].split("*"))) + r"\Z")
                 for r in settings["permissions"]["deny"] if r.startswith("Bash(")]
        known_broad = {"kubectl get secret -o name", "kubectl --context x get secrets -o wide",
                       "kubectl get secretstores -o yaml"}
        for command in self.ALLOWED:
            if command in known_broad:
                continue  # documented in guide §8: the settings rule is broader than the hook
            with self.subTest(command=command):
                self.assertFalse(any(rule.match(command) for rule in rules))

    def test_unknown_resources_ask_instead_of_deny(self):
        for command in ("kubectl get -f k8s/secret.yaml -o yaml", "kubectl get -k overlays/prod -o yaml",
                        "kubectl get pod $POD -o yaml", "kubectl get $'secret' db -o yaml",
                        "kubectl get -n x {secret,} db -o yaml", "kubectl get secre? db -o yaml"):
            with self.subTest(command=command):
                decision, reason = self.decision(command)
                self.assertEqual(decision, "ask")
                self.assertIn("if it is a Secret, this shows its values", reason)

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
            rest = rest.replace("--raw*", "--raw /api/v1/namespaces/x")  # kubectl wants the path right after --raw
            command = f"{tool} {flags[tool]} " + " ".join(rest.replace("*", " x ").split())
            with self.subTest(rule=rule, command=command):
                self.assertEqual(self.decision(command)[0], "deny")


def settings_rules(kind):
    """Claude Code rule matching: `*` matches any text, no `*` at the end means exact."""
    settings = json.loads((KIT_DIR / "claude" / "settings.devops-kit.json").read_text(encoding="utf-8"))
    return [re.compile(".*".join(map(re.escape, r[5:-1].split("*"))) + r"\Z")
            for r in settings["permissions"][kind] if r.startswith("Bash(")]


class TerraformSecretReads(HookTestCase):
    """Checked with terraform 1.14: these print sensitive values in clear text."""

    FORBIDDEN = [
        "terraform state pull",
        "terraform -chdir=envs/prod state pull > s.json",
        "terraform output db_password",
        "terraform -chdir=envs/prod output db_password",
        "terraform output -raw db_password",
        "terraform output -json",
        "terraform output --json",
        "terraform output -json=true",
        "terraform output -state=x.tfstate db_password",
        "tofu output -json",
        "terraform show -json",
        "terraform show -json tfplan",
        "tofu -chdir=envs/prod show -json",
        "echo 'nonsensitive(var.pw)' | terraform console",
        "tofu plan -show-sensitive",
        "tofu state show -show-sensitive aws_db_instance.db",
        "terragrunt output -json",
        "terragrunt run-all output -json",
        # state files read through the shell
        "cat terraform.tfstate",
        "jq . .terraform/terraform.tfstate",
        "grep -i password envs/prod/terraform.tfstate.backup",
        "less terraform.tfstate.d/prod/terraform.tfstate",
        "cat terraform.tfst*",
        "head -c 500 errored.tfstate",
        "cp terraform.tfstate /tmp/s.json",
        "python3 -c \"print(open('terraform.tfstate').read())\"",
        "jq . < terraform.tfstate",
        "echo $(cat terraform.tfstate)",
        "git log -p -- terraform.tfstate",
        "git show HEAD:terraform.tfstate",
        "find . -name '*.tfstate' -exec cat {} +",
    ]
    ALLOWED = [
        "terraform output",
        "terraform output -no-color",
        "terraform output -json=false",
        "terraform output -state x.tfstate",
        "terraform state list",
        "terraform -chdir=envs/prod state list module.db",
        "terraform plan -refresh-only",
        "terraform show tfplan",
        "ls -la *.tfstate",
        "echo '*.tfstate' >> .gitignore",
        "git log --oneline -- terraform.tfstate",
        "git rm --cached terraform.tfstate",
        "find . -name '*.tfstate'",
        "grep '\\.tfstate' .gitignore",
        "cat main.tf",
        "cat tfstate-notes.md",
    ]

    def test_denied(self):
        for command in self.FORBIDDEN:
            with self.subTest(command=command):
                decision, reason = self.decision(command)
                self.assertEqual(decision, "deny")
                self.assertIn("devops-ai-kit: blocked:", reason)

    def test_not_denied(self):
        for command in self.ALLOWED:
            with self.subTest(command=command):
                self.assertNotEqual(self.decision(command)[0], "deny")

    def test_show_asks_with_a_warning(self):
        for command in ("terraform show", "terraform -chdir=envs/prod state show module.db.x", "tofu state show x"):
            with self.subTest(command=command):
                decision, reason = self.decision(command)
                self.assertEqual(decision, "ask")
                self.assertIn("not mark sensitive", reason)

    def test_output_deny_points_to_output_without_a_name(self):
        self.assertIn("`terraform output` without a name", self.decision("terraform output pw")[1])

    def test_settings_match_the_hook(self):
        deny, ask, allow = settings_rules("deny"), settings_rules("ask"), settings_rules("allow")
        for command in ("terraform state pull", "terraform -chdir=x output -raw pw", "tofu show -json",
                        "terraform console", "tofu plan -show-sensitive"):
            with self.subTest(command=command):
                self.assertTrue(any(rule.match(command) for rule in deny))
        # ask beats allow: `state list` must not hit an ask rule, `state rm` still must
        for command in ("terraform state list", "terraform -chdir=x state list", "tofu state list"):
            with self.subTest(command=command):
                self.assertFalse(any(rule.match(command) for rule in ask + deny))
                self.assertTrue(any(rule.match(command) for rule in allow))
        for command in ("terraform state rm x", "terraform -chdir=x state mv a b", "tofu state push s.json",
                        "terraform state show x"):
            with self.subTest(command=command):
                self.assertTrue(any(rule.match(command) for rule in ask))


class SecretReadBypasses(HookTestCase):
    """Found by the independent review: wrappers, flag injection, pipes, globs, plan files.

    The work folder holds real (empty) state files, because globs and recursive searches are checked
    against the files that exist."""

    DENY = [
        "unzip -p tfplan tfstate",
        "unzip -o tfplan && cat tfstate",
        "TF_CLI_ARGS_output=-json terraform output",
        "TF_CLI_ARGS_output=pw terraform output",
        "export TF_CLI_ARGS_output=-json; terraform output",
        "bash -lc 'terraform output -json'",
        "sh -ec 'terraform state pull'",
        "env -i PATH=/usr/bin terraform output -json",
        "env -u X terraform state pull",
        "env -S 'terraform output -json'",
        "timeout -s KILL 5 terraform output -json",
        "nice -n 5 terraform output pw",
        "sudo -E terraform state pull",
        "sudo -u ops cat terraform.tfstate",
        "eval terraform output -json",
        "watch -n 5 terraform output -json",
        "echo pw | xargs terraform output",
        "find . -exec terraform output -json \\;",
        "find . -name '*.tfstate' | xargs cat",
        "ls *.tfstate | xargs jq .",
        "cat terraform.*",
        "cat terraform.tfstate.d/*/*",
        "cat terraform.{tfstate,x}",
        "cat<terraform.tfstate",
        "f=terraform.tfstate; cat $f",
        "terragrunt --working-dir live/db output -json",
        "terragrunt --log-level info state pull",
        "cat *",
        "cd envs/prod && cat *",
        "grep -rn password .",
        "rg password",
        "find . -type f -exec grep -l password {} +",
        "echo $(cat terraform.tfstate)",
        "diff <(terraform output -json) old.json",
        # second review round
        "sudo -Eu root terraform output -json",
        "env -iu FOO terraform output -json",
        "env - terraform output -json",
        "echo ns1 | xargs -i kubectl delete ns {}",
        "xargs -e kubectl delete ns",
        "watch 'terraform output -json'",
        "watch -n1 'kubectl delete ns foo'",
        "bash -o pipefail -c 'terraform output -json'",
        "bash -O extglob -c 'kubectl delete ns foo'",
        "bash +x -c 'terraform state pull'",
        "find . -type f | xargs cat",
        "find . -type f | xargs grep -i FAKE",
        "cat $(find . -type f)",
        "grep -i FAKE $(find . -type f)",
        "tar cf - .",
        "grep -R FAKE linked/",
        "doppler run -- terraform output -json",
        "aws-vault exec prod -- terraform state pull",
        "direnv exec . terraform output -json",
        "flock /tmp/l terraform output -json",
        "su -c 'terraform output -json'",
        "unzip -p tfplan",
        "tar -xOf tfplan",
        "python3 -m zipfile -e tfplan out/",
        # third review round
        "python3 -c \"import json; print(open('envs/prod/terraform.tfstate.backup').read())\"",
        "python3 -c \"import zipfile;print(zipfile.ZipFile('tfplan').read('tfstate'))\"",
        "node -e \"const fs=require('fs'); console.log(fs.readFileSync('terraform.tfstate','utf8'))\"",
        "flock /tmp/l -c 'terraform output -json'",
        "flock -n /tmp/l -c 'kubectl delete ns foo'",
        "strace -fo /dev/null terraform output -json",
        "aws-vault exec prof terraform output -json",
        "doppler run --command 'terraform output -json'",
        "sops -d secrets.enc.yaml",
        "sops decrypt secrets.enc.yaml",
    ]
    ASK = [
        "echo 'terraform output -json' | bash",
        "bash <<< 'terraform output -json'",
        "t=terraform; $t output -json",
        "terragrunt state show x",
        "unzip -p other.zip",
        "tar -xOf other.tar",
        "argocd app list -o yaml",
        "argocd appset get x -o yaml",
        "helm diff upgrade r ch --diff-tool vimdiff",
        "HELM_DIFF_TOOL=x helm diff upgrade r ch",
        "helm template r ch --post-renderer ./x.sh",
        "KUBECTL_EXTERNAL_DIFF='sh -c id' kubectl diff -f deploy.yaml",
        "export KUBECTL_EXTERNAL_DIFF=cat; kubectl diff -f deploy.yaml",
    ]
    NOT_DENIED = [
        "grep -rn --exclude='*.tfstate*' password .",
        "rg -g '!*.tfstate*' password",
        "grep -n '*.tfstate' .gitignore",
        "grep -rn image app/",
        "tree -I '*.tfstate*'",
        "sha256sum terraform.tfstate",
        "git -C infra log --oneline -- terraform.tfstate",
        "git -C infra status",
        "ls -l $(pwd)/terraform.tfstate",
        "find . -name '*.tfstate' -exec ls -l {} \\;",
        "find . -name '*.yaml' -exec grep image {} +",
        "argocd app get shop --show-params=false",
        "cat app/values.yaml",
        "kubectl get pods -A | grep -v Running",
        "for ns in a b; do kubectl get pods -n $ns; done",
        "terraform plan -out=tfplan",
        "sudo -u ops kubectl get pods",
        "git add terraform.tfstate",
        'git commit -m "chore: move tfstate to remote backend"',
        'gh pr create --title "Remove tfstate from repo" --body x',
        "cat docs/tfstate.md",
        "git commit -m 'note: do not run $(terraform output -json)'",
        "ls *.tfstate* ; kubectl get pods -n $NS",
        "echo '*.tfstate' >> .gitignore && git commit -am \"$MSG\"",
        "grep -rn --exclude='*.tfstate*' password docs/",
        "kubectl get pods -A -o name | xargs -n1 kubectl describe",
        "grep -rn backend --include='*.tf' .",
        "unzip -l tfplan",
        "python3 -c 'print(1); print(2)'",
    ]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for name in ("terraform.tfstate", "envs/prod/terraform.tfstate.backup", "envs/prod/.terraform/terraform.tfstate",
                     "terraform.tfstate.d/dev/terraform.tfstate", "app/values.yaml", "main.tf", "docs/tfstate.md",
                     "secrets/terraform.tfstate"):
            path = cls.workdir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        with zipfile.ZipFile(cls.workdir / "tfplan", "w") as plan:  # `terraform plan -out` writes a zip like this
            plan.writestr("tfplan", "")
            plan.writestr("tfstate", "")
        (cls.workdir / "linked").mkdir()
        (cls.workdir / "linked" / "s").symlink_to(cls.workdir / "secrets")

    def test_denied(self):
        for command in self.DENY:
            with self.subTest(command=command):
                self.assertEqual(self.decision(command)[0], "deny")

    def test_ask(self):
        for command in self.ASK:
            with self.subTest(command=command):
                self.assertEqual(self.decision(command)[0], "ask")

    def test_not_denied(self):
        for command in self.NOT_DENIED:
            with self.subTest(command=command):
                self.assertNotEqual(self.decision(command)[0], "deny")

    def test_rg_skips_state_that_git_ignores(self):
        repo = self.workdir / "gitrepo"
        (repo / "envs").mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / ".gitignore").write_text("*.tfstate*\n")
        (repo / "envs" / "terraform.tfstate").touch()
        self.assertNotEqual(self.decision("rg password gitrepo/")[0], "deny")
        self.assertEqual(self.decision("rg --no-ignore password gitrepo/")[0], "deny")
        self.assertEqual(self.decision("grep -rn password gitrepo/")[0], "deny")

    def test_recursive_search_skips_backend_config(self):
        (self.workdir / "modules/db/.terraform").mkdir(parents=True, exist_ok=True)
        (self.workdir / "modules/db/.terraform/terraform.tfstate").touch()
        self.assertNotEqual(self.decision("grep -rn bucket modules/")[0], "deny")


class DiffAndArgoSecretReads(HookTestCase):
    """Found by the independent review of the live-vs-declared idea."""

    def test_show_secrets_and_external_diff_are_denied(self):
        for command in ("helm diff upgrade web chart/ --show-secrets",
                        "helm --kube-context x diff upgrade web chart/ --show-secrets-decoded",
                        "kubectl diff -f deploy.yaml --show-secrets",
                        "kubectl --context x diff --show-secrets=true -k overlays/prod",
                        "helm --burst-limit 100 diff upgrade web chart/ --show-secrets"):
            with self.subTest(command=command):
                decision, reason = self.decision(command)
                self.assertEqual(decision, "deny")
                self.assertIn("devops-ai-kit: blocked:", reason)

    def test_plain_diffs_are_not_denied(self):
        for command in ("helm diff upgrade web chart/ --three-way-merge", "kubectl diff -f deploy.yaml"):
            with self.subTest(command=command):
                self.assertNotEqual(self.decision(command)[0], "deny")

    def test_argocd_values_ask_with_a_warning(self):
        for command in ("argocd app get shop -o yaml", "argocd app get shop --show-params",
                        "argocd --server x app get shop -ojson", "argocd app manifests shop"):
            with self.subTest(command=command):
                decision, reason = self.decision(command)
                self.assertEqual(decision, "ask")
                self.assertIn("argocd app", reason)
        self.assertEqual(self.decision("argocd app get shop")[0], None)


class GitPushTargets(HookTestCase):
    """The production check looks at the branch a push writes to, not at every word of the branch name."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        git = ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "-c", "init.defaultBranch=main"]
        remote = cls.workdir / "remote.git"
        cls.repo = cls.workdir / "infra"
        subprocess.run(git + ["init", "-q", "--bare", str(remote)], check=True)
        subprocess.run(git + ["init", "-q", str(cls.repo)], check=True)
        run = lambda *a: subprocess.run(git + ["-C", str(cls.repo), *a], check=True, capture_output=True)
        run("commit", "-q", "--allow-empty", "-m", "x")
        run("remote", "add", "origin", str(remote))
        run("push", "-q", "origin", "main:live")
        run("checkout", "-q", "-b", "tracks-live", "--track", "origin/live")
        run("checkout", "-q", "-b", "feat/live-vs-declared")

    def push(self, command, cwd=None, block="1", field="permissionDecision"):
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command},
                              "cwd": str(cwd or self.repo)}).encode()
        result = subprocess.run([sys.executable, str(HOOK)], input=payload, capture_output=True, timeout=30,
                                env={"PATH": self.path, "HOME": str(self.home), "DEVOPS_KIT_BLOCK_PROD": block})
        return json.loads(result.stdout)["hookSpecificOutput"][field]

    def test_work_branch_with_live_in_its_name_asks(self):
        self.assertEqual(self.push("git push -u origin feat/live-vs-declared"), "ask")
        self.assertEqual(self.push("git push origin HEAD"), "ask")
        self.assertEqual(self.push("git push -u origin fix/prod-typo"), "ask")

    def test_push_to_a_production_branch_is_denied(self):
        for command in ("git push origin HEAD:live", "git push origin feat/x:refs/heads/prod",
                        "git push origin +main:production", "git push origin live-vs-declared",
                        "git push -o ci.skip origin HEAD:live"):
            with self.subTest(command=command):
                self.assertEqual(self.push(command), "deny")

    def test_bare_push_uses_the_upstream(self):
        subprocess.run(["git", "-C", str(self.repo), "checkout", "-q", "tracks-live"], check=True)
        try:
            self.assertEqual(self.push("git push"), "deny")  # pushes to origin/live
        finally:
            subprocess.run(["git", "-C", str(self.repo), "checkout", "-q", "feat/live-vs-declared"], check=True)

    def test_push_all_checks_every_branch(self):
        # local branch `tracks-live` is not a work branch and ends in the word `live`
        self.assertEqual(self.push("git push --all origin"), "deny")
        self.assertIn("tracks-live", self.push("git push --all origin", block="0", field="permissionDecisionReason"))

    def test_production_repo_name_counts_except_for_work_branches(self):
        prod_repo = self.workdir / "gitops-prod"
        subprocess.run(["git", "init", "-q", str(prod_repo)], check=True)
        self.assertEqual(self.push("git push origin main", cwd=prod_repo), "deny")
        self.assertEqual(self.push("git push -u origin feat/x", cwd=prod_repo), "ask")  # the GitOps PR branch

    def test_review_cases(self):
        for command in ("git -C . push origin live", "git -c push.default=current push origin live",
                        "git -C infra push origin HEAD:prod", "git push origin :live",
                        "git push origin 'refs/heads/*:refs/heads/*'", "git push origin :"):
            with self.subTest(command=command):
                cwd = self.workdir if command.startswith("git -C infra") else None
                self.assertEqual(self.push(command, cwd=cwd), "deny")
        for command in ("git push --repo prod-remote", "git push --repo=prod-remote"):
            with self.subTest(command=command):  # the current branch is a work branch, so it asks, but shows the remote
                self.assertIn("remote=prod-remote", self.push(command, block="0", field="permissionDecisionReason"))

    def test_pushes_that_delete_remote_branches_get_no_work_branch_exemption(self):
        clone = self.workdir / "only-feat"
        subprocess.run(["git", "init", "-q", "-b", "feat/a", str(clone)], check=True)
        subprocess.run(["git", "-C", str(clone), "-c", "user.email=t@example.com", "-c", "user.name=t",
                        "commit", "-q", "--allow-empty", "-m", "x"], check=True)
        for command in ("git push --mirror prod-remote", "git push --all --prune prod-remote",
                        "git push --prune prod-remote 'refs/heads/*:refs/heads/*'"):
            with self.subTest(command=command):
                self.assertEqual(self.push(command, cwd=clone), "deny")

    def test_prune_checks_the_branches_the_remote_has(self):
        subprocess.run(["git", "-C", str(self.repo), "fetch", "-q", "origin"], check=True)  # origin/live is tracked
        self.assertEqual(self.push("git push --prune origin 'refs/heads/*:refs/heads/*'"), "deny")
        self.assertEqual(self.push("git push --prune origin 'refs/heads/feat/*:refs/heads/feat/*'"), "deny")

    def test_work_branches_are_not_checked_by_name_in_a_mixed_push(self):
        self.assertEqual(self.push("git push origin feat/live-vs-declared main"), "ask")
        self.assertEqual(self.push("git push origin 'refs/heads/feat/*:refs/heads/feat/*'"), "ask")

    def test_remote_url_is_checked(self):
        subprocess.run(["git", "-C", str(self.repo), "remote", "add", "deploy", "https://git.example/gitops-prod.git"],
                       check=True)
        self.assertEqual(self.push("git push deploy main"), "deny")
        self.assertEqual(self.push("git push deploy feat/y"), "ask")


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
        self.assertIn("DEVOPS_KIT_BLOCK_PROD=0 turns it off", reason)

    def test_production_is_blocked_by_default(self):
        decision, _ = self.decision("kubectl --context aks-prod-weu delete pod web-1",
                                    env={"DEVOPS_KIT_BLOCK_PROD": None})
        self.assertEqual(decision, "deny")
        decision, _ = self.decision("kubectl --context kind-dev delete pod web-1",
                                    env={"DEVOPS_KIT_BLOCK_PROD": None})
        self.assertEqual(decision, "ask")

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


class DevPattern(HookTestCase):
    """DEVOPS_KIT_DEV_PATTERN (opt-in): one simple command on a dev target needs no confirmation."""
    ENV = {"DEVOPS_KIT_DEV_PATTERN": r"^(kind-|dev)"}

    def test_single_command_on_dev_is_allowed(self):
        decision, reason = self.decision("kubectl --context kind-dev -n app scale deploy/web --replicas=2", env=self.ENV)
        self.assertEqual(decision, "allow")
        self.assertIn("DEVOPS_KIT_DEV_PATTERN", reason)
        self.assertEqual(self.decision("terraform apply tfplan", env=dict(self.ENV, TF_WORKSPACE="dev"))[0], "allow")

    def test_still_asks_when_not_simple_or_not_dev(self):
        for command in (
            "kubectl --context kind-dev apply -f a.yaml && rm -r /tmp/x",
            "kubectl --context kind-dev apply -f a.yaml; kubectl --context kind-dev delete pod x",
            "kubectl --context kind-dev apply -f $(echo a.yaml)",
            "bash -c 'kubectl --context kind-dev apply -f a.yaml'",
            "kubectl --context aks-stg apply -f a.yaml",
            "kubectl --context dev-ro apply -f a.yaml",
        ):
            with self.subTest(command=command):
                self.assertEqual(self.decision(command, env=self.ENV)[0], "ask")

    def test_production_name_wins_over_dev_pattern(self):
        env = dict(self.ENV, DEVOPS_KIT_BLOCK_PROD=None)
        self.assertEqual(self.decision("kubectl --context dev --kubeconfig k/kubeconfig.hetzner-live delete pod x", env=env)[0], "deny")

    def test_forbidden_commands_stay_denied(self):
        self.assertEqual(self.decision("kubectl --context kind-dev delete ns app", env=self.ENV)[0], "deny")

    def test_off_by_default_and_bad_regex(self):
        self.assertEqual(self.decision("kubectl --context kind-dev delete pod x")[0], "ask")
        self.assertEqual(self.decision("kubectl --context kind-dev delete pod x", env={"DEVOPS_KIT_DEV_PATTERN": "("})[0], "ask")


class Heredocs(HookTestCase):
    def test_data_heredoc_body_is_not_read_as_commands(self):
        doc = "cat > notes.md <<'EOF'\nkubectl --context x delete ns shop\nterraform destroy\nEOF\ngit status"
        self.assertEqual(self.decision(doc), (None, None))
        doc = "python3 - <<EOF\nprint('kubectl delete pod web')\nEOF"
        self.assertEqual(self.decision(doc), (None, None))

    def test_backslash_delimiter_is_a_quoted_delimiter(self):
        doc = "cat > f.sh <<\\EOF\nkubectl --context x delete ns shop\nEOF"
        self.assertEqual(self.decision(doc), (None, None))

    def test_yaml_heredoc_to_kubectl_still_asks_for_the_apply(self):
        decision, reason = self.decision("kubectl apply -f - <<EOF\napiVersion: v1\nkind: ConfigMap\nEOF")
        self.assertEqual(decision, "ask")
        self.assertIn("kubectl apply", reason)

    def test_heredoc_fed_to_a_shell_is_checked(self):
        self.assertEqual(self.decision("bash <<'EOF'\nkubectl --context x delete ns shop\nEOF")[0], "deny")
        self.assertEqual(self.decision("sh <<-EOF\n\tkubectl delete pod web\n\tEOF")[0], "ask")

    def test_unquoted_body_with_substitution_is_checked(self):
        self.assertEqual(self.decision("cat <<EOF\n$(x)\nkubectl delete pod web\nEOF")[0], "ask")

    def test_commands_after_the_heredoc_are_checked(self):
        self.assertEqual(self.decision("cat > a.txt <<'EOF'\nhello\nEOF\nkubectl delete pod web")[0], "ask")

    def test_body_is_checked_when_it_may_run(self):
        """Found in review: these hid a forbidden command. Only cat/tee/kubectl apply -f - bodies are skipped."""
        delete = "kubectl --context x delete ns shop"
        for command in (
            f"echo '<<EOF'\n{delete}",                      # << inside quotes is not a heredoc
            f"cat <<EOF-1\nhello\nEOF-1\n{delete}",          # delimiter is the whole word
            f"cat <<'E'OF\nhello\nEOF\n{delete}",            # quotes removed: delimiter EOF
            f"cat <<EOF | bash\n{delete}\nEOF",              # piped to a shell
            f"source /dev/stdin <<EOF\n{delete}\nEOF",
            f"ssh jump <<EOF\n{delete}\nEOF",
            f"kubectl exec -i p -- sh <<EOF\n{delete}\nEOF",
            f"cat > a.txt <<'EOF'\nno end line\n{delete}",   # no end line: keep everything
            f"kubectl get pods <<<a\n{delete}",              # here-string, not a heredoc
            f"kubectl get pods # <<EOF\n{delete}",           # in a comment
            # second review round
            f"cat<<EOF|bash\n{delete}\nEOF",                 # no spaces around the pipe
            f"cat <<EOF \\\n| bash\n{delete}\nEOF",           # line goes on below
            f"cat <<EOF > >(bash)\n{delete}\nEOF",           # process substitution
            f"tee >(sh) <<EOF\n{delete}\nEOF",
            f'cat "a\\" <<EOF"\n{delete}\nEOF',              # << inside double quotes with \"
        ):
            with self.subTest(command=command):
                self.assertEqual(self.decision(command)[0], "deny")


class DevPatternIsStrict(HookTestCase):
    """Found in review: the "allow" covers the whole Bash command, so it must be one plain call."""
    ENV = {"DEVOPS_KIT_DEV_PATTERN": r"^(kind-|dev-)"}

    def test_no_allow_for_anything_but_one_plain_call(self):
        for command in (
            "kubectl --context kind-a delete pod x & rm -rf ~/work",
            "kubectl --context kind-a delete pod x # <<EOF\nrm -rf ~/work",
            "kubectl --context kind-a apply -f - > ~/.bashrc",
            "kubectl --context kind-a --cluster prod-aks --user prod-admin delete deploy api",
            "kubectl --context kind-a --server https://10.0.0.1 delete deploy api",
            "kubectl --context kind-a --token abc delete deploy api",
            "helm --kube-context kind-a --kube-apiserver https://10.0.0.1 upgrade web ./chart",
            "git push origin dev-x:main",
            "ansible-playbook -i dev-inv site.yml",
            "az --subscription dev-sub group delete -n rg",
            "make deploy e=dev-a",
            "kubectl --context kind-a exec pod -- rm -rf /data",
            "kubectl --context kind-a debug node/x -it --image=busybox",
            "helm --kube-context kind-a upgrade x ./chart --post-renderer ./run.sh",
            "helm --kube-context kind-a upgrade x oci://registry.example/chart",
        ):
            with self.subTest(command=command):
                self.assertNotEqual(self.decision(command, env=self.ENV)[0], "allow")

    def test_no_allow_when_any_word_looks_like_production(self):
        env = dict(self.ENV, TF_WORKSPACE="dev-a")
        self.assertNotEqual(self.decision("terraform apply -var-file=prod.tfvars", env=env)[0], "allow")
        self.assertNotEqual(self.decision("terraform apply -auto-approve tfplan", env=env)[0], "allow")
        self.assertEqual(self.decision("terraform apply tfplan", env=env)[0], "allow")


if __name__ == "__main__":
    unittest.main()
