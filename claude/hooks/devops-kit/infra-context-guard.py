#!/usr/bin/env python3
"""devops-ai-kit PreToolUse hook for the Bash and PowerShell tools.

When Claude is about to run a state-changing infrastructure command, this hook
forces an interactive confirmation whose reason line shows WHERE the command
will land: kube context + namespace, terraform workspace/backend, Azure
subscription, AWS profile, GCP project, Ansible inventory/limit, git remote.

Design rules:
  * Never loosens anything. The hook only returns "ask", or "deny" when
    DEVOPS_KIT_BLOCK_PROD=1 and the target looks like production.
    Permission deny/ask rules in settings.json still apply regardless.
  * Fails open: on any internal error it prints nothing and exits 0, so the
    normal permission flow decides.
  * Fast: no network calls, only local config lookups with short timeouts.

Environment knobs:
  DEVOPS_KIT_PROD_PATTERN  regex matched against target names (case-insensitive)
  DEVOPS_KIT_BLOCK_PROD=1  deny (instead of ask) mutations on production targets
  DEVOPS_KIT_GUARD_OFF=1   disable the hook entirely
"""

import configparser
import json
import os
import re
import shlex
import subprocess
import sys

PROD_RE = re.compile(
    os.environ.get(
        "DEVOPS_KIT_PROD_PATTERN",
        r"(^|[-_.:/@ ])(prod|prd|production|live)([-_.:/@ ]|$)",
    ),
    re.IGNORECASE,
)
BLOCK_PROD = os.environ.get("DEVOPS_KIT_BLOCK_PROD") == "1"

SEGMENT_SPLIT = re.compile(r"&&|\|\||;|\||\n")
ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
WRAPPERS = {"sudo", "time", "nice", "nohup", "command", "builtin", "exec", "&"}
SHELL_TOOLS = {"Bash", "PowerShell"}
SHELLS = {"bash", "sh", "zsh", "dash"}

# --- kubectl ---------------------------------------------------------------
KUBECTL_VALUE_FLAGS = {
    "-n", "--namespace", "--context", "--kubeconfig", "--cluster", "--user",
    "-s", "--server", "--token", "--as", "--as-group", "--request-timeout",
    "-v", "--v", "-f", "--filename", "-l", "--selector", "-o", "--output",
    "-c", "--container", "--field-selector", "-k", "--kustomize",
}
KUBECTL_MUTATING = {
    "apply", "create", "delete", "patch", "replace", "scale", "edit", "label",
    "annotate", "set", "drain", "cordon", "uncordon", "taint", "exec", "cp",
    "run", "debug", "expose", "autoscale",
}
KUBECTL_ROLLOUT_MUTATING = {"restart", "undo", "pause", "resume"}
KUBECTL_CONFIG_MUTATING = {
    "use-context", "use", "set-context", "set", "set-cluster",
    "set-credentials", "delete-context", "delete-cluster", "delete-user",
    "rename-context", "unset",
}
KUBECTL_PLUGIN_READONLY = {
    "cnpg": {"status", "report", "logs", "version", "help"},
    "pgo": {"show", "version", "support", "help"},
}

# --- helm ------------------------------------------------------------------
HELM_VALUE_FLAGS = {
    "-n", "--namespace", "--kube-context", "--kubeconfig", "--kube-apiserver",
    "--kube-token", "--repository-config", "--registry-config",
    "--repository-cache", "-f", "--values", "--version", "--set",
    "--set-string", "--set-file", "--timeout", "-o", "--output",
}
HELM_MUTATING = {"install", "upgrade", "uninstall", "delete", "del", "un", "rollback"}

# --- terraform / tofu ------------------------------------------------------
TF_MUTATING = {"apply", "destroy", "import", "taint", "untaint", "force-unlock"}
TF_STATE_MUTATING = {"rm", "mv", "push", "replace-provider"}
TF_WORKSPACE_MUTATING = {"select", "new", "delete"}

# --- cloud CLIs ------------------------------------------------------------
AZ_MUTATING = {
    "create", "delete", "update", "set", "start", "stop", "restart", "scale",
    "upgrade", "add", "remove", "assign", "purge", "deploy", "import",
    "rotate", "reset", "attach", "detach", "enable", "disable", "install",
    "uninstall", "get-credentials", "invoke", "restore", "failover",
}
AWS_MUTATING_PREFIX = (
    "create", "delete", "put", "update", "modify", "terminate", "run",
    "start", "stop", "reboot", "attach", "detach", "associate",
    "disassociate", "authorize", "revoke", "register", "deregister",
    "restore", "import", "reset", "set", "enable", "disable", "execute",
    "replace", "promote", "failover", "tag", "untag",
)
AWS_S3_MUTATING = {"rm", "mv", "sync", "mb", "rb"}
GCLOUD_MUTATING = {
    "create", "delete", "update", "set", "add-iam-policy-binding",
    "remove-iam-policy-binding", "deploy", "resize", "start", "stop",
    "reset", "patch", "import", "restore", "failover", "promote-replica",
}
ARGOCD_MUTATING = {"sync", "delete", "set", "rollback", "patch", "create", "rm", "terminate-op", "run"}
VELERO_MUTATING = {"create", "delete"}


def run(cmd, env=None, cwd=None, timeout=3):
    try:
        out = subprocess.run(
            cmd, env=env, cwd=cwd, capture_output=True, text=True, timeout=timeout,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def tokenize(segment):
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def peel(tokens):
    """Strip leading env assignments and wrapper commands.

    Returns (tokens, env_overrides).
    """
    env = {}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if ENV_ASSIGN.match(tok):
            key, _, val = tok.partition("=")
            env[key] = val
            i += 1
        elif tok in WRAPPERS:
            i += 1
        elif tok == "env":
            i += 1
        elif tok == "timeout" and i + 1 < len(tokens):
            i += 2
        else:
            break
    return tokens[i:], env


def parse_args(args, value_flags):
    """Split CLI args into positionals and a flag dict (last value wins)."""
    positionals, flags = [], {}
    i = 0
    while i < len(args):
        tok = args[i]
        if tok == "--":
            break
        if tok.startswith("-") and len(tok) > 1:
            if "=" in tok:
                key, _, val = tok.partition("=")
                flags[key] = val
            elif tok in value_flags and i + 1 < len(args):
                flags[tok] = args[i + 1]
                i += 1
            else:
                flags[tok] = True
        else:
            positionals.append(tok)
        i += 1
    return positionals, flags


def flag(flags, *names):
    for name in names:
        val = flags.get(name)
        if isinstance(val, str):
            return val
    return None


def is_prod(*names):
    return any(n and PROD_RE.search(n) for n in names)


# --- target resolvers --------------------------------------------------------

def kubeconfig_name(kubeconfig, env):
    """File name of the kubeconfig in use, or "" for the default ~/.kube/config.

    Many clusters call their only context "default", so the file name is often
    the only thing that tells the targets apart (e.g. kubeconfig.hetzner-live).
    """
    path = kubeconfig or env.get("KUBECONFIG") or os.environ.get("KUBECONFIG") or ""
    first = path.split(os.pathsep)[0].rstrip("/\\")
    return re.split(r"[\\/]", first)[-1] if first else ""


def kube_target(ctx, ns, kubeconfig, env, all_ns=False, cwd=None):
    environ = dict(os.environ, **env)
    cmd = ["kubectl", "config", "view", "--minify",
           "-o", "jsonpath={.contexts[0].name}|{.contexts[0].context.namespace}"]
    if kubeconfig:
        cmd += ["--kubeconfig", kubeconfig]
    if ctx:
        cmd += ["--context", ctx]
    resolved = run(cmd, env=environ, cwd=cwd if cwd and os.path.isdir(cwd) else None)
    cur_ctx, _, cur_ns = resolved.partition("|")
    ctx = ctx or cur_ctx or "unknown"
    ns = "ALL namespaces" if all_ns else (ns or cur_ns or "default")
    return ctx, ns


def tf_target(cwd, chdir, env):
    base = os.path.normpath(os.path.join(cwd or os.getcwd(), chdir or "."))
    ws = env.get("TF_WORKSPACE") or os.environ.get("TF_WORKSPACE")
    if not ws:
        try:
            with open(os.path.join(base, ".terraform", "environment"), encoding="utf-8") as fh:
                ws = fh.read().strip()
        except OSError:
            ws = "default"
    backend = ""
    try:
        with open(os.path.join(base, ".terraform", "terraform.tfstate"), encoding="utf-8") as fh:
            data = json.load(fh).get("backend") or {}
        btype = data.get("type", "")
        conf = data.get("config") or {}
        key = conf.get("key") or conf.get("prefix") or ""
        backend = f"{btype}:{key}" if key else btype
    except (OSError, ValueError, AttributeError):
        pass
    return base, ws, backend


def az_target(sub_flag, env):
    if sub_flag:
        return sub_flag
    cfg_dir = env.get("AZURE_CONFIG_DIR") or os.environ.get("AZURE_CONFIG_DIR") or os.path.expanduser("~/.azure")
    try:
        with open(os.path.join(cfg_dir, "azureProfile.json"), encoding="utf-8-sig") as fh:
            subs = json.load(fh).get("subscriptions", [])
        for sub in subs:
            if sub.get("isDefault"):
                return f"{sub.get('name', '?')} ({sub.get('id', '?')})"
    except (OSError, ValueError, AttributeError):
        pass
    return "unknown"


def gcloud_project(flag_project, env):
    if flag_project:
        return flag_project
    proj = env.get("CLOUDSDK_CORE_PROJECT") or os.environ.get("CLOUDSDK_CORE_PROJECT")
    if proj:
        return proj
    cfg_dir = env.get("CLOUDSDK_CONFIG") or os.environ.get("CLOUDSDK_CONFIG") or os.path.expanduser("~/.config/gcloud")
    try:
        with open(os.path.join(cfg_dir, "active_config"), encoding="utf-8") as fh:
            active = fh.read().strip() or "default"
        parser = configparser.ConfigParser()
        parser.read(os.path.join(cfg_dir, "configurations", f"config_{active}"))
        return parser.get("core", "project", fallback="unknown")
    except (OSError, configparser.Error):
        return "unknown"


# --- detectors: return (summary, [names used for prod check], readonly_ctx) or None

def kube_summary(ctx, ns, kc_name):
    shown = f"context={ctx}" + (f" kubeconfig={kc_name}" if kc_name else "")
    return shown + (f" namespace={ns}" if ns is not None else "")


def detect_kubectl(base, args, env, cwd):
    pos, flags = parse_args(args, KUBECTL_VALUE_FLAGS)
    if not pos:
        return None
    sub = pos[0]
    nxt = pos[1] if len(pos) > 1 else ""
    mutating = False
    if sub in KUBECTL_MUTATING:
        mutating = True
    elif sub == "rollout" and nxt in KUBECTL_ROLLOUT_MUTATING:
        mutating = True
    elif sub == "config" and nxt in KUBECTL_CONFIG_MUTATING:
        mutating = True
    elif sub in KUBECTL_PLUGIN_READONLY and nxt not in KUBECTL_PLUGIN_READONLY[sub]:
        mutating = True
    if not mutating:
        return None
    dry_run = flag(flags, "--dry-run")
    if dry_run and dry_run != "none":
        return None
    if sub == "config":
        return (f"{base} config {nxt} (changes the local kubeconfig selection)", [], False)
    kubeconfig = flag(flags, "--kubeconfig")
    ctx, ns = kube_target(
        flag(flags, "--context"), flag(flags, "-n", "--namespace"), kubeconfig, env,
        all_ns=bool(flags.get("-A") or flags.get("--all-namespaces")), cwd=cwd,
    )
    kc_name = kubeconfig_name(kubeconfig, env)
    shown = " ".join(pos[:3])
    if len(pos) > 3:
        shown += " …"
    return (f"{base} {shown} → {kube_summary(ctx, ns, kc_name)}", [ctx, ns, kc_name], ctx.endswith("-ro"))


def detect_helm(args, env, cwd):
    pos, flags = parse_args(args, HELM_VALUE_FLAGS)
    if not pos or pos[0] not in HELM_MUTATING:
        return None
    if flags.get("--dry-run"):
        return None
    kubeconfig = flag(flags, "--kubeconfig")
    ctx, ns = kube_target(
        flag(flags, "--kube-context"), flag(flags, "-n", "--namespace"), kubeconfig, env, cwd=cwd,
    )
    kc_name = kubeconfig_name(kubeconfig, env)
    release = pos[1] if len(pos) > 1 else "?"
    return (f"helm {pos[0]} {release} → {kube_summary(ctx, ns, kc_name)}",
            [ctx, ns, release, kc_name], ctx.endswith("-ro"))


def detect_terraform(base, args, env, cwd):
    chdir = None
    rest = []
    for tok in args:
        if tok.startswith("-chdir="):
            chdir = tok.split("=", 1)[1]
        else:
            rest.append(tok)
    pos = [t for t in rest if not t.startswith("-")]
    if not pos:
        return None
    sub = pos[0]
    nxt = pos[1] if len(pos) > 1 else ""
    if not (sub in TF_MUTATING
            or (sub == "state" and nxt in TF_STATE_MUTATING)
            or (sub == "workspace" and nxt in TF_WORKSPACE_MUTATING)):
        return None
    path, ws, backend = tf_target(cwd, chdir, env)
    action = f"{sub} {nxt}".strip() if sub in ("state", "workspace") else sub
    extra = " [auto-approve]" if any(t.startswith("-auto-approve") for t in rest) else ""
    be = f" backend={backend}" if backend else ""
    return (f"{base} {action}{extra} → workspace={ws}{be} dir={path}", [ws, backend, path], False)


def detect_az(args, env):
    pos, flags = parse_args(args, {"--subscription", "-g", "--resource-group", "-n", "--name", "--query", "-o", "--output"})
    hit = next((p for p in pos[:6] if p in AZ_MUTATING), None)
    if not hit:
        return None
    sub = az_target(flag(flags, "--subscription"), env)
    rg = flag(flags, "-g", "--resource-group") or ""
    rg_txt = f" resource-group={rg}" if rg else ""
    return (f"az {' '.join(pos[:pos.index(hit) + 1])} → subscription={sub}{rg_txt}", [sub, rg], False)


def detect_aws(args, env):
    pos, flags = parse_args(args, {"--profile", "--region", "--output", "--query"})
    if len(pos) < 2:
        return None
    service, op = pos[0], pos[1]
    if service == "s3":
        mutating = op in AWS_S3_MUTATING or (op == "cp" and pos and pos[-1].startswith("s3://"))
    else:
        mutating = op.startswith(AWS_MUTATING_PREFIX)
    if not mutating:
        return None
    profile = flag(flags, "--profile") or env.get("AWS_PROFILE") or os.environ.get("AWS_PROFILE") or "default"
    region = flag(flags, "--region") or env.get("AWS_REGION") or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "?"
    return (f"aws {service} {op} → profile={profile} region={region}", [profile, region], False)


def detect_gcloud(args, env):
    pos, flags = parse_args(args, {"--project", "--region", "--zone", "--format"})
    hit = next((p for p in pos if p in GCLOUD_MUTATING), None)
    if not hit:
        return None
    project = gcloud_project(flag(flags, "--project"), env)
    return (f"gcloud {' '.join(pos[:pos.index(hit) + 1])} → project={project}", [project], False)


def detect_ansible_playbook(args):
    if any(a in ("--check", "-C", "--syntax-check", "--list-hosts", "--list-tasks", "--list-tags") for a in args):
        return None
    pos, flags = parse_args(args, {"-i", "--inventory", "-l", "--limit", "-e", "--extra-vars", "-t", "--tags", "--skip-tags", "-u", "--user"})
    inv = flag(flags, "-i", "--inventory") or "default inventory"
    limit = flag(flags, "-l", "--limit") or "ALL hosts in play"
    playbook = pos[0] if pos else "?"
    return (f"ansible-playbook {playbook} → inventory={inv} limit={limit}", [inv, limit, playbook], False)


def detect_argocd(args):
    pos, flags = parse_args(args, {"--server", "--grpc-web-root-path", "-o", "--output", "--revision"})
    hit = next((p for p in pos[:3] if p in ARGOCD_MUTATING), None)
    if not hit:
        return None
    app = pos[pos.index(hit) + 1] if len(pos) > pos.index(hit) + 1 else "?"
    server = flag(flags, "--server") or os.environ.get("ARGOCD_SERVER") or "current argocd context"
    return (f"argocd {' '.join(pos[:pos.index(hit) + 1])} {app} → server={server}", [app, server], False)


def detect_velero(args, env, cwd):
    pos, flags = parse_args(args, {"--kubecontext", "-n", "--namespace", "--kubeconfig", "--from-backup", "--from-schedule"})
    if len(pos) < 2 or pos[1] not in VELERO_MUTATING:
        return None
    kubeconfig = flag(flags, "--kubeconfig")
    ctx, _ = kube_target(flag(flags, "--kubecontext"), None, kubeconfig, env, cwd=cwd)
    kc_name = kubeconfig_name(kubeconfig, env)
    return (f"velero {pos[0]} {pos[1]} → {kube_summary(ctx, None, kc_name)}", [ctx, kc_name], ctx.endswith("-ro"))


def detect_git_push(args, cwd):
    if not args or args[0] != "push":
        return None
    pos = [a for a in args[1:] if not a.startswith("-")]
    remote = pos[0] if pos else "origin"
    branch = pos[1] if len(pos) > 1 else run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd) or "?"
    top = run(["git", "rev-parse", "--show-toplevel"], cwd=cwd)
    repo = os.path.basename(top) if top else "?"
    force = " [FORCE]" if any(a in ("-f", "--force", "--force-with-lease") for a in args) else ""
    return (f"git push{force} → repo={repo} remote={remote} branch={branch} (if this repo is watched by Argo CD/Flux, this deploys)", [branch, repo], False)


def detect_psql(args):
    pos, flags = parse_args(args, {"-h", "--host", "-d", "--dbname", "-U", "--username", "-p", "--port", "-c", "--command", "-f", "--file"})
    uri = next((p for p in pos if p.startswith(("postgres://", "postgresql://"))), None)
    if uri:
        target = re.sub(r"//[^@/]*@", "//***@", uri)
    else:
        host = flag(flags, "-h", "--host") or os.environ.get("PGHOST") or "local socket"
        db = flag(flags, "-d", "--dbname") or (pos[0] if pos else os.environ.get("PGDATABASE", "?"))
        user = flag(flags, "-U", "--username") or os.environ.get("PGUSER", "?")
        target = f"host={host} db={db} user={user}"
    return (f"psql → {target}", [target], False)


def exported_vars(segment, cwd):
    """KEY=VALUE pairs set by an `export` segment, with $PWD and ~ expanded."""
    tokens = tokenize(segment)
    if not tokens or tokens[0] != "export":
        return {}
    found = {}
    for tok in tokens[1:]:
        if ENV_ASSIGN.match(tok):
            key, _, val = tok.partition("=")
            val = val.replace("${PWD}", cwd).replace("$PWD", cwd)
            found[key] = os.path.expanduser(val)
    return found


def analyse_segment(segment, cwd, depth=0, exported=None):
    tokens, env = peel(tokenize(segment))
    env = dict(exported or {}, **env)
    if not tokens:
        return []
    base = re.split(r"[\\/]", tokens[0])[-1]
    if base.lower().endswith(".exe"):
        base = base[:-4]
    args = tokens[1:]

    if base in SHELLS and "-c" in args and depth < 2:
        idx = args.index("-c")
        if idx + 1 < len(args):
            return analyse_command(args[idx + 1], cwd, depth + 1)
        return []

    if base in ("kubectl", "oc"):
        hit = detect_kubectl(base, args, env, cwd)
    elif base == "helm":
        hit = detect_helm(args, env, cwd)
    elif base in ("terraform", "tofu"):
        hit = detect_terraform(base, args, env, cwd)
    elif base == "az":
        hit = detect_az(args, env)
    elif base == "aws":
        hit = detect_aws(args, env)
    elif base == "gcloud":
        hit = detect_gcloud(args, env)
    elif base == "ansible-playbook":
        hit = detect_ansible_playbook(args)
    elif base == "argocd":
        hit = detect_argocd(args)
    elif base == "velero":
        hit = detect_velero(args, env, cwd)
    elif base == "git":
        hit = detect_git_push(args, cwd)
    elif base == "psql":
        hit = detect_psql(args)
    else:
        hit = None
    return [hit] if hit else []


def analyse_command(command, cwd, depth=0):
    hits, exported = [], {}
    for segment in SEGMENT_SPLIT.split(command):
        segment = segment.strip()
        if segment:
            # `export KUBECONFIG=...; kubectl ...` must use the exported file for the later segments.
            exported.update(exported_vars(segment, cwd))
            hits.extend(analyse_segment(segment, cwd, depth, exported))
    return hits


def main():
    if os.environ.get("DEVOPS_KIT_GUARD_OFF") == "1":
        return
    payload = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    if payload.get("tool_name") not in SHELL_TOOLS:
        return
    command = (payload.get("tool_input") or {}).get("command") or ""
    if payload.get("tool_name") == "PowerShell":
        # PowerShell escapes with backtick, not backslash: keep Windows paths intact for shlex.
        command = command.replace("\\", "/")
    cwd = payload.get("cwd") or os.getcwd()
    hits = analyse_command(command, cwd)
    if not hits:
        return

    parts, prod_targets = [], []
    for summary, names, readonly in hits:
        if readonly:
            parts.append(f"🔒 {summary} (read-only AI context: RBAC will reject this)")
        elif is_prod(*names):
            parts.append(f"⚠️ PRODUCTION · {summary}")
            prod_targets.append(summary)
        else:
            parts.append(f"▶ {summary}")
    reason = "devops-ai-kit: " + " | ".join(parts)

    if BLOCK_PROD and prod_targets:
        decision = "deny"
        reason = (
            "devops-ai-kit: mutating command against a production target is blocked in this "
            "session (DEVOPS_KIT_BLOCK_PROD=1): " + " | ".join(prod_targets) +
            ". Prepare the change as a GitOps PR or give the exact command to the user to run."
        )
    else:
        decision = "ask"

    json.dump({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }, sys.stdout, ensure_ascii=True)  # ASCII-safe: Windows consoles may not be UTF-8


if __name__ == "__main__":
    try:
        main()
    except Exception:  # fail open: never break the session because of the guard
        pass
    sys.exit(0)
