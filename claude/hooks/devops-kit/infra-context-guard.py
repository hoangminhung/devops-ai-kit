#!/usr/bin/env python3
"""devops-ai-kit PreToolUse hook for the Bash and PowerShell tools.

When Claude is about to run a state-changing infrastructure command, this hook
forces an interactive confirmation whose reason line shows WHERE the command
will land: kube context + namespace, terraform workspace/backend, Azure
subscription, AWS profile, GCP project, Ansible inventory/limit, git remote.

It also denies the commands the kit always forbids (namespace / PVC / CRD
deletes, destroy, helm uninstall, printing secret values). The settings deny
rules match command text from the start, so `kubectl --context X delete ns Y`
slips past `Bash(kubectl delete ns *)`; the hook parses the flags and catches
it in any order.

Design rules:
  * Does not loosen anything by default. The hook returns "ask" or "deny"
    ("deny" for the forbidden commands above, and for production targets
    unless DEVOPS_KIT_BLOCK_PROD=0). The only "allow" is opt-in: a single
    simple command on a target that matches DEVOPS_KIT_DEV_PATTERN. Permission
    deny rules in settings.json still apply regardless.
  * Fails open: on any internal error it prints nothing and exits 0, so the
    normal permission flow decides.
  * Fast: no network calls, only local config lookups with short timeouts.

Environment knobs:
  DEVOPS_KIT_PROD_PATTERN  regex matched against target names (case-insensitive)
  DEVOPS_KIT_BLOCK_PROD=0  ask (instead of deny) for mutations on production targets
  DEVOPS_KIT_DEV_PATTERN   regex for dev/sandbox targets: a single mutating command
                           there runs without a confirm dialog (off when unset)
  DEVOPS_KIT_GUARD_OFF=1   disable the hook entirely
"""

import configparser
import fnmatch
import glob
import itertools
import json
import os
import re
import shlex
import subprocess
import sys
import zipfile
from urllib.parse import unquote, urlsplit

PROD_RE = re.compile(
    os.environ.get(
        "DEVOPS_KIT_PROD_PATTERN",
        r"(^|[-_.:/@ ])(prod|prd|production|live)([-_.:/@ ]|$)",
    ),
    re.IGNORECASE,
)
BLOCK_PROD = os.environ.get("DEVOPS_KIT_BLOCK_PROD", "1") != "0"
DEV_PATTERN = os.environ.get("DEVOPS_KIT_DEV_PATTERN", "")

SEGMENT_SPLIT = re.compile(r"&&|\|\||;|\||\n")
HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# Wrapper commands and their flags that take a value.
WRAPPERS = {
    "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U", "-T", "--user", "--group", "--chdir", "--host", "--prompt"},
    "nice": {"-n", "--adjustment"},
    "env": {"-u", "--unset", "-C", "--chdir"},
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
    "ionice": {"-c", "-n", "-p", "--class", "--classdata"},
    "stdbuf": {"-i", "-o", "-e"},
    "time": {"-f", "-o", "--format", "--output"},
    "exec": {"-a"},
    "nohup": set(), "setsid": set(), "command": set(), "builtin": set(), "&": set(),
}
# Shell keywords that can start a segment: `for …; do kubectl …; done`, `if …; then …; fi`, `{ …; }`, `( … )`, `! …`
SHELL_KEYWORDS = {"do", "then", "else", "elif", "while", "until", "!", "{", "(", "}", ")"}
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
    "--set-string", "--set-file", "--timeout", "-o", "--output", "--burst-limit", "--qps",
    "--kube-as-user", "--kube-as-group", "--kube-ca-file", "--kube-tls-server-name",
}
HELM_MUTATING = {"install", "upgrade", "uninstall", "delete", "del", "un", "rollback"}

# --- terraform / tofu ------------------------------------------------------
TF_MUTATING = {"apply", "destroy", "import", "taint", "untaint", "force-unlock"}
TF_STATE_MUTATING = {"rm", "mv", "push", "replace-provider"}
TF_WORKSPACE_MUTATING = {"select", "new", "delete"}
TF_FALSE = {"0", "f", "false"}  # Go bool flags: -json=false is off
# State files hold every value in clear text (passwords, keys); .terraform/terraform.tfstate holds backend config.
TFSTATE_NAME = re.compile(r"[^\\/]*\.tfstate(?:\.[^/]*)?")
TFSTATE_SAMPLES = ("terraform.tfstate", "terraform.tfstate.backup", "errored.tfstate")
# Commands that may name a state file without printing it.
STATE_FILE_SAFE = {"ls", "stat", "file", "du", "wc", "test", "[", "touch", "mkdir", "rm", "echo", "printf", "tree", "zipinfo",
                   "sha256sum", "sha1sum", "md5sum", "cd", "terraform", "tofu", "terragrunt"}
GIT_VALUE_FLAGS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
GIT_PRINTS_FILES = {"show", "diff", "cat-file", "blame", "grep", "archive", "format-patch", "log", "whatchanged"}
GIT_PATCH_FLAGS = ("-p", "-u", "-U", "--patch", "--word-diff", "--cc", "--color-words", "-L")
GREP_TOOLS = {"grep", "egrep", "fgrep", "zgrep", "rg", "ag", "ack"}
ALWAYS_RECURSIVE = {"rg", "ag", "ack"}
# Commands that pass a file name from elsewhere (a pipe, a loop, a variable) to another command.
INDIRECT = {"xargs", "parallel", "while", "read", "for", "eval", "source", "."}
# Copy or pack a whole folder: a state file inside is copied in clear text (`tar cf - .`).
DIR_READERS = {"tar", "bsdtar", "zip", "7z", "7za", "cp", "rsync", "scp"}
GLOB_LIMIT = 2000
FIND_EXEC = {"-exec", "-execdir", "-ok", "-okdir"}
FIND_FILTERS = {"-name", "-iname", "-path", "-ipath", "-regex", "-iregex", "-wholename"}
SKIP_DIRS = {".git", "node_modules", ".terraform"}  # .terraform/terraform.tfstate is backend config only
WALK_LIMIT = 20000

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

# --- make ------------------------------------------------------------------
# A target name with one of these words probably changes something (make apply e=prod).
MAKE_MUTATING = re.compile(
    r"apply|destroy|deploy|install|upgrade|delete|rollout|rollback|release|sync|migrate|push",
    re.IGNORECASE,
)
MAKE_VALUE_FLAGS = {"-C", "--directory", "-f", "--file", "--makefile", "-I", "--include-dir", "-j", "--jobs", "-o", "-W"}
MAKE_DRY_RUN = {"-n", "--dry-run", "--just-print", "--recon", "-q", "--question"}

# --- always forbidden (same list as the settings deny rules) ----------------
KUBECTL_FORBIDDEN_DELETE = {
    "ns", "namespace", "namespaces", "pvc", "pvcs", "persistentvolumeclaim",
    "persistentvolumeclaims", "pv", "pvs", "persistentvolume", "persistentvolumes",
    "crd", "crds", "customresourcedefinition", "customresourcedefinitions",
}
SECRET_RESOURCES = {"secret", "secrets"}
SECRET_SAFE_OUTPUT = {"name", "wide"}  # these show no values
HELM_REMOVE = {"uninstall", "delete", "del", "un"}
# /api/v1/[watch/][namespaces/<ns>/]secrets[/<name>] (kubectl proxy + curl)
SECRETS_API = re.compile(r"/api/v1/(watch/)?(namespaces/[^/]+/)?secrets(/|$)")
KUBECTL_SHORT_VALUE = set("nolLfkcsv")  # short flags that take a value (pflag: -Aoyaml = -A -o yaml)
KUBECTL_UNKNOWN_OBJECTS = {"-f", "--filename", "-k", "--kustomize"}  # objects named in files: may be Secrets
HELM_GET_SECRET = {"values", "manifest", "all"}  # release values and rendered Secrets


class Blocked(Exception):
    """A command the kit always forbids, whatever the flag order."""


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
    """Strip leading env assignments, wrapper commands and shell keywords.

    Returns (tokens, env_overrides).
    """
    tokens = [t for t in (tok.lstrip("(").rstrip(")") if tok not in ("(", ")") else tok for tok in tokens) if t]
    env = {}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in SHELL_KEYWORDS:
            i += 1
        elif ENV_ASSIGN.match(tok):
            key, _, val = tok.partition("=")
            env[key] = val
            i += 1
        elif tok in WRAPPERS:
            # `sudo -u x`, `nice -n 5`, `env -i -u X`, `timeout -s KILL 5`: skip the wrapper's own flags
            value_flags = WRAPPERS[tok]
            i += 1
            while i < len(tokens) and tokens[i].startswith("-") and (tokens[i] != "-" or tok == "env"):
                flag_tok = tokens[i]
                if tok == "env" and flag_tok in ("-S", "--split-string") and i + 1 < len(tokens):
                    tokens[i:i + 2] = tokenize(tokens[i + 1])  # `env -S 'terraform output -json'`
                    break
                # `sudo -Eu root`: in a group of short flags, only the last one can take the next word
                last = flag_tok if flag_tok.startswith("--") else "-" + flag_tok[-1]
                i += 2 if "=" not in flag_tok and last in value_flags else 1
            if tok == "timeout" and i < len(tokens):
                i += 1  # the duration
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


# --- forbidden commands ------------------------------------------------------

def resource_types(token):
    """`ns,pvc` / `secret/db` / `deploy.apps` → {"ns", "pvc"} / {"secret"} / {"deploy"}."""
    return {part.split("/")[0].split(".")[0].lower() for part in token.split(",") if part}


def output_values(args):
    """Values of -o / --output in any form: `-o yaml`, `-oyaml`, `-o=yaml`, `--output=json`."""
    values = []
    for i, tok in enumerate(args):
        if tok in ("-o", "--output"):
            values.append(args[i + 1] if i + 1 < len(args) else "")
        elif tok.startswith("--output="):
            values.append(tok.split("=", 1)[1])
        elif tok.startswith("-o") and not tok.startswith("--"):
            values.append(tok[2:].lstrip("="))
    return values


def expand_short_flags(args):
    """`-Ao yaml` → `-A -o yaml`, `-Aojson` → `-A -o json`, `-v=9` → `-v 9` (pflag rules)."""
    out = []
    for tok in args:
        if not tok.startswith("-") or tok.startswith("--") or len(tok) <= 2:
            out.append(tok)
            continue
        rest = tok[1:]
        for j, char in enumerate(rest):
            out.append("-" + char)
            if char in KUBECTL_SHORT_VALUE:
                value = rest[j + 1:].lstrip("=")
                if value:
                    out.append(value)
                break
    return out


def url_path(text):
    """Decoded path of a URL or API path, without query and fragment (`%73ecrets` → `secrets`)."""
    try:
        path = urlsplit(text).path if "://" in text else text.split("?")[0].split("#")[0]
    except ValueError:
        path = text
    return unquote(unquote(path)).lower()


def verbosity(flags):
    try:
        return int(flag(flags, "-v", "--v") or 0)
    except ValueError:
        return 0


def kubectl_get_parts(args):
    """(positionals, flags) of a kubectl command, parsed like pflag; words after `--` are positionals too."""
    args = expand_short_flags(args)
    head, tail = (args[:args.index("--")], args[args.index("--") + 1:]) if "--" in args else (args, [])
    pos, flags = parse_args(head, KUBECTL_VALUE_FLAGS | {"--sort-by", "--label-columns", "--chunk-size", "--template", "--raw"})
    return pos + tail, flags, head


def kubectl_secret_read(base, args):
    """Why this kubectl/oc command can print secret values, or None."""
    pos, flags, head = kubectl_get_parts(args)
    if base == "oc" and pos[:1] == ["extract"]:
        return "oc extract (writes or prints secret values)"
    if pos[:1] == ["view-secret"]:
        return f"{base} view-secret (plugin that prints secret values)"
    if pos[:2] == ["apply", "view-last-applied"] and any(resource_types(p) & SECRET_RESOURCES for p in pos[2:]):
        return f"{base} apply view-last-applied on a Secret (prints its values)"
    if pos[:1] != ["get"]:
        return None
    raw = flag(flags, "--raw")
    if raw is not None:
        if "secrets" in url_path(raw).split("/"):
            return f"{base} get --raw on the secrets API (prints secret values)"
        return None
    shows_values = (any(v.lower() not in SECRET_SAFE_OUTPUT for v in output_values(head))
                    or "--template" in flags or verbosity(flags) >= 6)
    if not shows_values:
        return None
    if any(resource_types(p) & SECRET_RESOURCES for p in pos[1:]):
        return (f"{base} get Secrets with an output or log level that prints values "
                "(use `kubectl describe secret <name>`, or secret_fingerprint.py to compare)")
    return None


def kubectl_unknown_objects(base, args):
    """`kubectl get -f x.yaml -o yaml`: the files may name Secrets, so ask (not deny)."""
    pos, flags, head = kubectl_get_parts(args)
    if pos[:1] != ["get"]:
        return None
    from_files = any(f in flags for f in KUBECTL_UNKNOWN_OBJECTS)
    expanded = any(ch in p for p in pos[1:] for ch in "${`*?[")
    if not (from_files or expanded):
        return None
    if any(v.lower() not in SECRET_SAFE_OUTPUT for v in output_values(head)) or "--template" in flags or verbosity(flags) >= 6:
        where = "objects from -f / -k" if from_files else "a resource set by the shell ($VAR, {a,b}, glob)"
        return (f"{base} get {where} with an output that prints values: if it is a Secret, this shows its values",
                [], False)
    return None


def subsequence(pos, words):
    n = len(words)
    return any(pos[i:i + n] == words for i in range(len(pos) - n + 1))


def tf_flag_on(args, name):
    """True when the Go bool flag -name / --name is set (`-json`, `-json=true`, not `-json=false`)."""
    for tok in args:
        if tok.startswith("-"):
            key, eq, value = tok.lstrip("-").partition("=")
            if key == name and (not eq or value.lower() not in TF_FALSE):
                return True
    return False


def terraform_secret_read(base, args):
    """Terraform / OpenTofu commands that print sensitive values in clear text (checked with terraform 1.14)."""
    pos, i = [], 0
    while i < len(args):
        tok = args[i]
        if tok in ("-state", "--state"):
            i += 2  # `output -state path`: the path is not an output name
            continue
        if not tok.startswith("-"):
            pos.append(tok)
        i += 1
    if base == "terragrunt":
        # `terragrunt --log-level info run-all output -json`: flag values come before the subcommand
        start = next((n for n, p in enumerate(pos) if p in ("output", "show", "state", "console")), None)
        pos = pos[start:] if start is not None else []
    if not pos:
        return None
    sub = pos[0]
    if tf_flag_on(args, "show-sensitive"):
        return f"{base} {sub} -show-sensitive (prints sensitive values)"
    if sub == "console":
        return f"{base} console (nonsensitive() prints any sensitive value)"
    if sub == "state" and pos[1:2] == ["pull"]:
        return f"{base} state pull (prints the whole state: every password and key in it)"
    if sub == "output" and (len(pos) > 1 or tf_flag_on(args, "json") or tf_flag_on(args, "raw")):
        return (f"{base} output with a name, -json or -raw (prints sensitive outputs in clear text; "
                f"`{base} output` without a name shows them as <sensitive>)")
    if sub == "show" and tf_flag_on(args, "json"):
        return f"{base} show -json (prints sensitive values in clear text; `{base} show` hides values marked sensitive)"
    return None


def terraform_state_view(base, args):
    """`terraform show` / `state show`: values marked sensitive are hidden, others are not, so ask."""
    pos = [t for t in args if not t.startswith("-")]
    if pos[:1] == ["show"] or pos[:2] == ["state", "show"]:
        return (f"{base} {' '.join(pos[:2]) if pos[0] == 'state' else 'show'}: prints resource attributes; "
                "a value the provider does not mark sensitive (e.g. a derived output) is shown in clear text",
                [], False)
    return None


def expand_braces(word):
    """`terraform.{tfstate,x}` → ["terraform.tfstate", "terraform.x"] (one level is enough here)."""
    match = re.search(r"\{([^{}]*,[^{}]*)\}", word)
    if not match:
        return [word]
    return [word[:match.start()] + alt + word[match.end():] for alt in match.group(1).split(",")]


def names_state_file(tok, cwd):
    """True when a word names a Terraform state file: directly, inside `-c '...'` code, or as a glob / brace
    pattern that matches one in `cwd` or looks like `terraform.*` / `*.tfst*`."""
    for whole in expand_braces(tok):
        for word in re.split(r"[\s=:,;'\"()<>|&]+", whole):
            name = word.rstrip("/").rsplit("/", 1)[-1]
            if "\\" in name:
                continue  # a regex like `\.tfstate`, not a file
            if TFSTATE_NAME.fullmatch(name) or is_plan_file(word, cwd):
                return True
            if not any(ch in word for ch in "*?["):
                continue
            path = word if os.path.isabs(word) else os.path.join(cwd, word)
            try:
                found = list(itertools.islice(glob.iglob(path), GLOB_LIMIT))  # `/*/*/*/*/*` must not take seconds
            except (OSError, re.error):
                found = []
            if any(TFSTATE_NAME.fullmatch(os.path.basename(f)) for f in found):
                return True
            literal = re.sub(r"[*?]|\[[^\]]*\]", "", name)
            if len(literal) >= 3 and any(fnmatch.fnmatchcase(s, name) for s in TFSTATE_SAMPLES):
                return True  # the folder may not exist yet, or the command `cd`s first
    return False


def is_plan_file(word, cwd):
    """A saved plan (`terraform plan -out`) is a zip that holds the state (`tfstate`) in clear text."""
    path = word if os.path.isabs(word) else os.path.join(cwd, word)
    try:
        if not os.path.isfile(path) or not zipfile.is_zipfile(path):
            return False
        with zipfile.ZipFile(path) as archive:
            return any(n in ("tfstate", "tfstate-prev") for n in archive.namelist())
    except (OSError, zipfile.BadZipFile, ValueError):
        return False


def git_subcommand(args):
    i = 0
    while i < len(args):
        tok = args[i]
        if not tok.startswith("-"):
            return tok
        i += 2 if tok in GIT_VALUE_FLAGS else 1
    return ""


def grep_parts(base, args):
    """(paths, exclude globs, recursive) of a grep-like command; the search pattern is not a path."""
    paths, excludes, includes, recursive, pattern_given = [], [], [], base in ALWAYS_RECURSIVE, False
    value_flags = {"-e", "--regexp", "-f", "--file", "-m", "--max-count", "-A", "-B", "-C", "-g", "--glob",
                   "--iglob", "--exclude", "--exclude-dir", "--include", "--ignore", "--ignore-dir", "-t", "-T",
                   "--type", "--type-not", "-d", "--directories", "--color", "--colour", "-M", "-j", "--threads"}
    i = 0
    while i < len(args):
        tok = args[i]
        if tok == "--":
            paths += args[i + 1:]
            break
        key, eq, value = tok.partition("=")
        if tok.startswith("--"):
            if not eq and key in value_flags and i + 1 < len(args):
                value = args[i + 1]
                i += 1
            if key in ("--exclude", "--exclude-dir", "--ignore", "--ignore-dir"):
                excludes.append(value)
            elif key in ("--glob", "--iglob"):
                (excludes if value.startswith("!") else includes).append(value.lstrip("!"))
            elif key == "--include":
                includes.append(value)
            elif key in ("--regexp", "--file"):
                pattern_given = True
            elif key in ("--recursive", "--dereference-recursive") or (key == "--directories" and value == "recurse"):
                recursive = True
        elif tok.startswith("-") and len(tok) > 1:
            letters = tok[1:]
            if letters[0] in "efmABCgtTdMj" and len(letters) == 1 and i + 1 < len(args):
                value = args[i + 1]
                i += 1
                if letters == "g":
                    (excludes if value.startswith("!") else includes).append(value.lstrip("!"))
                elif letters in "ef":
                    pattern_given = True
                elif letters == "d" and value == "recurse":
                    recursive = True
            elif base not in ALWAYS_RECURSIVE and ("r" in letters or "R" in letters):
                recursive = True
        else:
            paths.append(tok)
        i += 1
    if not pattern_given and paths:
        paths = paths[1:]  # the first word is the pattern
    return paths, excludes, includes, recursive


def state_files_under(paths, excludes, cwd, follow=False, includes=(), gitignore=False):
    """True when a recursive read of `paths` would reach a state file that is not excluded.

    `includes`: only matching files are read (`grep --include='*.tf'`). `gitignore`: rg / ag skip
    files that git ignores."""
    def excluded(name):
        return any(fnmatch.fnmatchcase(name, pattern) for pattern in excludes)

    def read(folder, name):
        if excluded(name) or not TFSTATE_NAME.fullmatch(name):
            return False
        if includes and not any(fnmatch.fnmatchcase(name, pattern) for pattern in includes):
            return False
        if gitignore and subprocess.run(["git", "-C", folder, "check-ignore", "-q", name],
                                        capture_output=True, timeout=3).returncode == 0:
            return False
        return True

    seen = 0
    for path in paths or ["."]:
        root = path if os.path.isabs(path) else os.path.join(cwd, path)
        if os.path.isfile(root):
            if TFSTATE_NAME.fullmatch(os.path.basename(root)) and not excluded(os.path.basename(root)):
                return True  # named on purpose: includes and .gitignore do not apply
            continue
        for folder, dirs, files in os.walk(root, followlinks=follow):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not excluded(d)]
            for name in files:
                try:
                    if read(folder, name):
                        return True
                except (OSError, subprocess.SubprocessError):
                    return True  # cannot tell: treat it as read
            seen += len(files) + len(dirs)
            if seen > WALK_LIMIT:
                return False  # a very large tree: not checked (guide §8)
    return False


def state_file_read(base, args, cwd):
    """Why this command reads a Terraform state file, or None."""
    if base in STATE_FILE_SAFE:
        return None
    if base == "git":
        sub = git_subcommand(args)  # `git commit -m "move tfstate"` prints nothing
        if sub not in GIT_PRINTS_FILES or (sub == "log" and not any(t.startswith(GIT_PATCH_FLAGS) for t in args)):
            return None
    if base == "find" or (base == "unzip" and {"-l", "-Z", "-v"} & set(args) and not {"-p", "-c"} & set(args)):
        return None  # names only (find -exec commands are checked in analyse_segment)
    words = args
    if base in DIR_READERS:
        excludes = [t.split("=", 1)[1] for t in args if t.startswith("--exclude=")]
        dirs = [t for t in args if not t.startswith("-") and os.path.isdir(os.path.join(cwd, t))]
        if dirs and state_files_under(dirs, excludes, cwd):
            return f"{base} on a folder that holds a Terraform state file (it is copied in clear text)"
    if base in GREP_TOOLS:
        paths, excludes, includes, recursive = grep_parts(base, args)
        follow = any(t in ("-R", "-L", "--follow", "--dereference-recursive") or
                     (t.startswith("-") and not t.startswith("--") and "R" in t) for t in args)
        gitignore = base in ("rg", "ag") and not any(t in ("-u", "-uu", "-uuu", "--no-ignore", "--no-ignore-vcs",
                                                             "--unrestricted", "--skip-vcs-ignores") for t in args)
        if recursive and state_files_under(paths, excludes, cwd, follow, includes, gitignore):
            return (f"{base} searches a folder that holds a Terraform state file "
                    "(add --exclude='*.tfstate*', or rg -g '!*.tfstate*')")
        words = paths
    if any(names_state_file(w, cwd) for w in words):
        return (f"{base} on a Terraform state file (state holds every value in clear text; "
                "use `terraform state list` or `terraform output` without a name)")
    return None


def archive_to_stdout(base, args):
    """`unzip -p tfplan`, `tar -xOf`: a Terraform plan file is a zip that holds the state, so ask."""
    short = [t[1:] for t in args if t.startswith("-") and not t.startswith("--")]
    if base in ("tar", "bsdtar") and args and not args[0].startswith("-"):
        short.append(args[0])  # old style: `tar xOf plan`
    to_stdout = (base == "funzip"
                 or (base == "unzip" and any(set(t) & {"p", "c"} for t in short))
                 or (base in ("tar", "bsdtar") and ("--to-stdout" in args or any("O" in t for t in short))))
    if to_stdout:
        return (f"{base} to stdout: prints archive members; a Terraform plan file (`plan -out`) holds the whole state",
                [], False)
    return None


def forbidden(base, args):
    """Why this command is always denied, or None."""
    if base in ("kubectl", "oc"):
        pos, _ = parse_args(expand_short_flags(args), KUBECTL_VALUE_FLAGS)
        if len(pos) >= 2 and pos[0] == "delete" and resource_types(pos[1]) & KUBECTL_FORBIDDEN_DELETE:
            return f"{base} delete {pos[1]} (namespace / PV / PVC / CRD deletes are never run by the AI)"
        if any(t.split("=", 1)[0] == "--show-secrets" for t in args):
            return f"{base} --show-secrets (prints Secret values)"
        return kubectl_secret_read(base, args)
    elif base in ("curl", "wget", "http", "https"):
        if any(SECRETS_API.search(url_path(a)) for a in args if not a.startswith("-")):
            return f"{base} on the Kubernetes secrets API (prints secret values)"
    elif base == "helm":
        pos, flags = parse_args(args, HELM_VALUE_FLAGS)
        if pos and pos[0] in HELM_REMOVE:
            return f"helm {pos[0]} {pos[1] if len(pos) > 1 else ''}".rstrip()
        if pos[:1] == ["get"] and len(pos) > 1 and pos[1] in HELM_GET_SECRET:
            return f"helm get {pos[1]} (release values and rendered Secrets can hold passwords)"
        if pos[:1] == ["status"] and any(v.lower() in ("json", "yaml") for v in output_values(args)):
            return "helm status -o json/yaml (prints the release config)"
        if "diff" in pos[:2] and any(t.split("=", 1)[0] in ("--show-secrets", "--show-secrets-decoded") for t in args):
            return "helm diff --show-secrets (prints Secret values; without the flag helm-diff hides them)"
    elif base == "terragrunt":
        return terraform_secret_read(base, args)
    elif base == "sops":
        pos = [t for t in args if not t.startswith("-")]
        if {"-d", "--decrypt"} & set(args) or pos[:1] == ["decrypt"]:
            return "sops decrypt (prints secret values)"
    elif base in ("terraform", "tofu"):
        pos = [t for t in args if not t.startswith("-")]
        if pos and (pos[0] == "destroy" or (pos[0] == "apply" and "-destroy" in args)):
            return f"{base} {pos[0]}{' -destroy' if pos[0] == 'apply' else ''}"
        return terraform_secret_read(base, args)
    elif base == "az":
        pos, _ = parse_args(args, {"--subscription", "--vault-name", "-n", "--name", "--id", "-f", "--file", "-o", "--output", "--query"})
        if subsequence(pos, ["keyvault", "secret", "show"]) or subsequence(pos, ["keyvault", "secret", "download"]):
            return "az keyvault secret show/download (prints a secret value)"
    elif base == "aws":
        pos, _ = parse_args(args, {"--profile", "--region", "--output", "--query", "--secret-id", "--version-id", "--version-stage"})
        if subsequence(pos, ["secretsmanager", "get-secret-value"]):
            return "aws secretsmanager get-secret-value (prints a secret value)"
    elif base == "gcloud":
        pos, _ = parse_args(args, {"--project", "--secret", "--format", "--out-file"})
        if subsequence(pos, ["secrets", "versions", "access"]):
            return "gcloud secrets versions access (prints a secret value)"
    return None


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


def argocd_values_view(args):
    """`argocd app get -o yaml`, `--show-params`, `app manifests`: Helm values and parameters can hold passwords, so ask."""
    pos, flags = parse_args(args, {"--server", "--grpc-web-root-path", "-o", "--output", "--revision", "--source"})
    if pos[:2] == ["app", "manifests"]:
        return ("argocd app manifests: rendered manifests can include Secrets", [], False)
    show_params = str(flags.get("--show-params", "false")).lower() not in ("false", "0")
    if pos[:1] in (["app"], ["appset"]) and pos[1:2] in (["get"], ["list"]) and (
            show_params or any(v.lower() in ("json", "yaml") for v in output_values(args))):
        return (f"argocd {pos[0]} {pos[1]} -o json/yaml or --show-params: Helm values and parameters "
                "in the Application can hold passwords", [], False)
    return None


def detect_velero(args, env, cwd):
    pos, flags = parse_args(args, {"--kubecontext", "-n", "--namespace", "--kubeconfig", "--from-backup", "--from-schedule"})
    if len(pos) < 2 or pos[1] not in VELERO_MUTATING:
        return None
    kubeconfig = flag(flags, "--kubeconfig")
    ctx, _ = kube_target(flag(flags, "--kubecontext"), None, kubeconfig, env, cwd=cwd)
    kc_name = kubeconfig_name(kubeconfig, env)
    return (f"velero {pos[0]} {pos[1]} → {kube_summary(ctx, None, kc_name)}", [ctx, kc_name], ctx.endswith("-ro"))


# Work branches: a push there deploys nothing, even when the name has `live` or `prod` in it.
WORK_BRANCH_PREFIXES = {"feat", "feature", "fix", "bugfix", "hotfix", "chore", "docs", "refactor", "test", "tests",
                        "ci", "perf", "build", "style", "wip", "dependabot", "renovate"}
GIT_PUSH_VALUE_FLAGS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}


def push_destinations(args, cwd):
    """(remote, [destination branches]) of `git push …`: the part after `:` in a refspec, the upstream of the
    current branch for a bare `git push`, every local branch for `--all` / `--mirror`."""
    pos, i, repo_flag = [], 1, None
    while i < len(args):
        if args[i] in GIT_PUSH_VALUE_FLAGS:
            if args[i] == "--repo" and i + 1 < len(args):
                repo_flag = args[i + 1]
            i += 2
            continue
        if args[i].startswith("--repo="):
            repo_flag = args[i].split("=", 1)[1]
        elif not args[i].startswith("-"):
            pos.append(args[i])
        i += 1
    if repo_flag and not pos:
        pos = [repo_flag]
    current = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd) or "?"
    local = lambda: run(["git", "for-each-ref", "--format=%(refname:short)", "refs/heads"], cwd=cwd).split()
    if any(a in ("--all", "--mirror", "--branches") for a in args) or any(s.lstrip("+") == ":" for s in pos[1:]):
        return (pos[0] if pos else "origin"), local() or ["?"]
    if any("*" in spec for spec in pos[1:]):
        # `refs/heads/feat/*:refs/heads/feat/*` pushes the local branches that match the source pattern
        patterns = [spec.lstrip("+").split(":")[0].replace("refs/heads/", "", 1) for spec in pos[1:] if "*" in spec]
        matched = [b for b in local() if any(fnmatch.fnmatchcase(b, p) for p in patterns)]
        rest = [spec.lstrip("+").split(":")[-1].replace("refs/heads/", "", 1) for spec in pos[1:] if "*" not in spec]
        return pos[0], matched + rest or ["?"]
    if len(pos) > 1:
        dests = []
        for spec in pos[1:]:
            dst = spec.lstrip("+").split(":")[-1] or spec.lstrip("+").split(":")[0]
            dst = current if dst == "HEAD" else dst
            dests.append(dst[len("refs/heads/"):] if dst.startswith("refs/heads/") else dst)
        return pos[0], dests
    upstream = run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], cwd=cwd)
    if upstream and "/" in upstream and not pos:
        remote, _, branch = upstream.partition("/")
        return remote, [branch]  # `git push` on a branch that tracks origin/main pushes to main
    return (pos[0] if pos else "origin"), [current]


def work_branch(branch):
    return "/" in branch and branch.split("/", 1)[0].lower() in WORK_BRANCH_PREFIXES


def git_push_args(args, cwd):
    """`git -C dir -c x=y push …` → (["push", …], dir): global flags before the subcommand are skipped."""
    sub = git_subcommand(args)
    if sub != "push":
        return [], cwd
    i = 0
    while args[i] != "push":
        if args[i] == "-C" and i + 1 < len(args):
            cwd = os.path.join(cwd, os.path.expanduser(args[i + 1]))
        i += 2 if args[i] in GIT_VALUE_FLAGS else 1
    return args[i:], cwd


def detect_git_push(args, cwd):
    if not args or args[0] != "push":
        return None
    remote, branches = push_destinations(args, cwd)
    top = run(["git", "rev-parse", "--show-toplevel"], cwd=cwd)
    repo = os.path.basename(top) if top else "?"
    force = " [FORCE]" if any(a in ("-f", "--force", "--force-with-lease") or a.startswith("--force-with-lease=")
                              for a in args) else ""
    url = run(["git", "remote", "get-url", remote], cwd=cwd) if re.fullmatch(r"[\w.-]+", remote) else ""
    # A push to work branches deploys nothing, also in a production GitOps repo: that is how its PRs start.
    # --mirror / --prune also delete remote branches the local repo does not have, so they never qualify.
    deletes = any(a in ("--mirror", "--prune") for a in args)
    work_only = all(work_branch(b) for b in branches) and not deletes
    checked = [] if work_only else [b for b in branches if not work_branch(b)] + [repo, remote, url]
    if deletes and re.fullmatch(r"[\w.-]+", remote):
        # branches the remote had at the last fetch (no network): the ones --mirror / --prune may delete
        tracked = run(["git", "for-each-ref", "--format=%(refname:short)", f"refs/remotes/{remote}"], cwd=cwd).split()
        checked += [t.split("/", 1)[-1] for t in tracked]
    return (f"git push{force} → repo={repo} remote={remote} branch={','.join(branches)} "
            "(if this repo is watched by Argo CD/Flux, this deploys)", checked, False)


def detect_make(base, args, cwd):
    if any(a in MAKE_DRY_RUN for a in args):
        return None
    directory, targets, variables = None, [], []
    i = 0
    while i < len(args):
        tok = args[i]
        if tok in MAKE_VALUE_FLAGS:
            if tok in ("-C", "--directory") and i + 1 < len(args):
                directory = args[i + 1]
            i += 2
            continue
        if tok.startswith("--directory="):
            directory = tok.split("=", 1)[1]
        elif not tok.startswith("-"):
            (variables if ENV_ASSIGN.match(tok) else targets).append(tok)
        i += 1
    if not any(MAKE_MUTATING.search(t) for t in targets):
        return None
    path = os.path.normpath(os.path.join(cwd or os.getcwd(), directory or "."))
    shown = " ".join(targets + variables)
    values = [v.split("=", 1)[1] for v in variables]
    return (f"{base} {shown} → dir={path} (a Makefile target: check the commands it runs and their target)",
            targets + values + [path], False)


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


# Tools that run the command after `--` (secrets managers, version managers).
RUN_AFTER_DASHDASH = {"aws-vault", "doppler", "mise", "op", "dotenv", "infisical", "chamber", "sops"}
# Tools that run a command after a fixed number of words: `flock FILE cmd`, `direnv exec DIR cmd`.
RUN_AFTER_WORDS = {"flock": 1, "taskset": 1, "direnv": 1, "strace": 0, "ltrace": 0}


def nested_command(base, args):
    """The command text that `bash -lc`, `eval`, `watch`, `xargs` or a runner such as `doppler run --`
    runs, or None. "" means: it runs something the hook cannot see."""
    if base in SHELLS or base in ("su", "script"):
        i = 0
        while i < len(args):
            tok = args[i]
            if tok in ("-o", "-O", "+o", "+O", "--rcfile", "--init-file"):
                i += 2  # `bash -o pipefail -c '…'`
                continue
            if not tok.startswith(("-", "+")):
                break
            if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*|--command", tok):
                rest = [t for t in args[i + 1:] if not t.startswith(("-", "+"))]
                return rest[0] if rest else ""
            i += 1
        if base in SHELLS and (i >= len(args) or args[i].startswith("<")):
            return ""  # `echo '…' | bash`, `bash <<< '…'`: commands from stdin
        return None  # `bash script.sh`: a script file is not read (guide §8)
    if base == "eval":
        return " ".join(args)
    if base == "watch":
        i = 0
        while i < len(args) and args[i].startswith("-"):
            i += 2 if args[i] in ("-n", "--interval", "-q", "--equexit") else 1
        return " ".join(args[i:])  # watch runs its words through `sh -c`
    if base in ("xargs", "parallel"):
        # -i / -e / --replace take a value only when it is attached (`-i{}`), so they are not listed here
        value_flags = {"-I", "-n", "-P", "-d", "-L", "-a", "-E", "-s", "-j", "--max-args",
                       "--max-procs", "--delimiter", "--arg-file", "--jobs"}
        i = 0
        while i < len(args) and args[i].startswith("-"):
            i += 2 if args[i] in value_flags else 1
        # the input words are added at the end: `echo pw | xargs terraform output` = `terraform output pw`
        return shlex.join(args[i:] + ["XARGS_INPUT"]) if i < len(args) else ""
    if base in RUN_AFTER_DASHDASH and "--" in args:
        return shlex.join(args[args.index("--") + 1:])
    command_flag = next((args[i + 1] for i, t in enumerate(args[:-1]) if t in ("--command", "-c")), None)
    if (base in RUN_AFTER_DASHDASH or base == "flock") and command_flag is not None:
        return command_flag  # `doppler run --command '…'`, `flock /tmp/l -c '…'`
    if base == "aws-vault" and args[:1] == ["exec"]:
        i = 1
        while i < len(args) and args[i].startswith("-"):
            i += 1 if "=" in args[i] or args[i] in ("--no-session", "-j", "--json", "-n") else 2
        return shlex.join(args[i + 1:])  # `aws-vault exec PROFILE terraform …`
    if base in RUN_AFTER_WORDS:
        rest = args[1:] if base == "direnv" and args[:1] == ["exec"] else args
        i = 0
        while i < len(rest) and rest[i].startswith("-"):
            i += 2 if "-" + rest[i][-1] in ("-o", "-e", "-p", "-s", "-w") else 1  # `strace -fo log`
        return shlex.join(rest[i + RUN_AFTER_WORDS[base]:])
    return None


def analyse_find(args, cwd, depth):
    """Check each -exec command; a reader on the found files must not reach a state file."""
    hits, i, find_args = [], 0, []
    while i < len(args):
        if args[i] in FIND_EXEC:
            end = next((j for j in range(i + 1, len(args)) if args[j] in (";", "+", "\\;")), len(args))
            command = args[i + 1:end]
            if command:
                hits += analyse_segment(shlex.join(command), cwd, depth + 1)
                base = re.split(r"[\\/]", command[0])[-1]
                filtered = any(t in FIND_FILTERS for t in find_args)
                if base not in STATE_FILE_SAFE and (
                        any(names_state_file(t, cwd) for t in find_args)
                        or (not filtered and state_files_under([t for t in find_args if not t.startswith("-")][:1], [], cwd))):
                    raise Blocked(f"find -exec {base} on Terraform state files (state holds every value in clear text)")
            i = end + 1
        else:
            find_args.append(args[i])
            i += 1
    return hits


def tf_cli_args(args, env):
    """Words that TF_CLI_ARGS / TF_CLI_ARGS_<command> add to this command."""
    pos = [t for t in args if not t.startswith("-")]
    sub = pos[0] if pos else ""
    merged = dict(os.environ, **env)
    extra = []
    for key in ("TF_CLI_ARGS", f"TF_CLI_ARGS_{sub}"):
        if merged.get(key):
            extra += tokenize(merged[key])
    return extra


def runs_program(base, args, env):
    """Allowed read commands that can be told to run any program: ask instead of allow."""
    if base in ("kubectl", "oc") and "KUBECTL_EXTERNAL_DIFF" in env:
        return ("KUBECTL_EXTERNAL_DIFF: `kubectl diff` runs this program", [], False)
    if base == "helm":
        if "HELM_DIFF_TOOL" in env or any(k.startswith("HELM_DIFF") and "SECRET" in k for k in env):
            return ("HELM_DIFF_* in the command: helm-diff runs this program or shows secrets", [], False)
        if any(t.split("=", 1)[0] in ("--diff-tool", "--post-renderer") for t in args):
            return ("helm --post-renderer / --diff-tool: runs this program", [], False)
    return None


def analyse_segment(segment, cwd, depth=0, exported=None):
    tokens, env = peel(tokenize(segment))
    env = dict(exported or {}, **env)
    if not tokens:
        return []
    split = re.match(r"([^<>]+)([<>].*)", tokens[0])
    if split:
        tokens = [split.group(1), split.group(2)] + tokens[1:]  # `cat<terraform.tfstate`
    base = re.split(r"[\\/]", tokens[0])[-1]
    if base.lower().endswith(".exe"):
        base = base[:-4]
    args = tokens[1:]

    if base.startswith("$"):
        return [("command name from a variable (`$t output`): the hook cannot check it", [], False)]
    if depth < 3:
        nested = nested_command(base, args)
        if nested == "" and base in SHELLS:
            return [(f"{base} reads commands from stdin: the hook cannot check them", [], False)]
        if nested is not None:
            return analyse_command(nested, cwd, depth + 1)
        if base == "find":
            return analyse_find(args, cwd, depth)

    reason = forbidden(base, args) or state_file_read(base, args, cwd)
    if base in ("terraform", "tofu", "terragrunt") and not reason:
        extra = tf_cli_args(args, env)
        reason = extra and terraform_secret_read(base, args + extra)
    if reason:
        raise Blocked(reason)
    runs = runs_program(base, args, env) or archive_to_stdout(base, args)
    if runs:
        return [runs]

    if base in ("kubectl", "oc"):
        hit = detect_kubectl(base, args, env, cwd) or kubectl_unknown_objects(base, args)
    elif base == "helm":
        hit = detect_helm(args, env, cwd)
    elif base in ("terraform", "tofu"):
        hit = detect_terraform(base, args, env, cwd) or terraform_state_view(base, args)
    elif base == "terragrunt":
        hit = terraform_state_view(base, [a for a in args if a in ("show", "state") or a.startswith("-")])
    elif base == "az":
        hit = detect_az(args, env)
    elif base == "aws":
        hit = detect_aws(args, env)
    elif base == "gcloud":
        hit = detect_gcloud(args, env)
    elif base == "ansible-playbook":
        hit = detect_ansible_playbook(args)
    elif base == "argocd":
        hit = detect_argocd(args) or argocd_values_view(args)
    elif base == "velero":
        hit = detect_velero(args, env, cwd)
    elif base == "git":
        hit = detect_git_push(*git_push_args(args, cwd))
    elif base == "psql":
        hit = detect_psql(args)
    elif base in ("make", "gmake"):
        hit = detect_make(base, args, cwd)
    else:
        hit = None
    return [hit] if hit else []


def heredoc_start(line):
    """(position, delimiter, quoted, strip_tabs) of a `<<` heredoc on this line, or None.

    Only one plain heredoc is accepted: `<<` outside quotes and comments, not `<<<`,
    delimiter word with its quotes removed (`'E'OF` is EOF). Anything unusual → None,
    so the lines below are checked as commands (fail closed).
    """
    quote, i, found = None, 0, []
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == quote:
                quote = None
            elif ch == "\\" and quote == '"':
                i += 1  # \" inside double quotes does not close them
        elif ch in "'\"":
            quote = ch
        elif ch == "\\":
            i += 1
        elif ch == "#" and (i == 0 or line[i - 1].isspace()):
            break
        elif line.startswith("<<", i):
            if line.startswith("<<<", i) or (i and line[i - 1] == "<"):
                return None
            found.append(i)
            i += 1
        i += 1
    if len(found) != 1 or line.rstrip().endswith("\\"):
        return None  # several heredocs, or the line goes on below (`<<EOF \` + `| bash`)
    pos = found[0]
    rest = line[pos + 2:]
    strip_tabs = rest.startswith("-")
    word = re.match(r"\s*(\S+)", rest[1:] if strip_tabs else rest)
    if not word:
        return None
    raw = word.group(1)
    # Anything that could pass the body to code: pipes, chains, background, (process) substitution.
    if re.search(r"[;|&()`$]", line[:pos] + line[pos:]):
        return None
    delim = re.sub(r"['\"\\]", "", raw)
    if not delim or re.search(r"[<>]", delim):
        return None
    return pos, delim, raw != delim, strip_tabs


def data_feeder(text):
    """True when the command before `<<` only stores or applies data: cat/tee to a file, kubectl apply -f -."""
    segments = SEGMENT_SPLIT.split(text)
    if len(segments) != 1:
        return False
    try:
        tokens, _ = peel(shlex.split(segments[0], posix=True))
    except ValueError:
        return False  # unbalanced quotes: do not guess
    if not tokens:
        return False
    base = re.split(r"[\\/]", tokens[0])[-1]
    if base in ("cat", "tee"):
        return True
    if base in ("kubectl", "oc"):
        pos, _ = parse_args(tokens[1:], KUBECTL_VALUE_FLAGS - {"-f", "--filename"})
        return bool(pos) and pos[0] in ("apply", "create", "replace", "diff") and "-" in tokens
    return False


def strip_heredocs(command):
    """Drop heredoc bodies that are only data (`cat > f.md <<'EOF'`, `kubectl apply -f - <<EOF`).

    Without this, every line of a file written with a heredoc is read as a command,
    which gives false asks and denies. Bodies are kept (and checked) in every other
    case: fed to anything else (bash, ssh, kubectl exec, source …), a pipe or a chain
    after the heredoc, `$(`/backticks in an unquoted body, no exact end line.
    """
    lines, out, i = command.split("\n"), [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        start = heredoc_start(line)
        if not start:
            continue
        pos, delim, quoted, strip_tabs = start
        end = next((j for j in range(i, len(lines))
                    if (lines[j].lstrip("\t") if strip_tabs else lines[j]) == delim), None)
        if end is None:
            continue  # no end line: keep everything
        body = lines[i:end]
        runs_code = not quoted and any("$(" in b or "`" in b for b in body)
        if data_feeder(line[:pos]) and not runs_code:
            out.append(lines[end])
            i = end + 1
    return "\n".join(out)


# Characters that make a command more than one plain call: chains, background, pipes,
# redirection, substitution, comments, variables. Any of them → no "allow".
NOT_SIMPLE = re.compile(r"[\n;&|<>`$#(){}]")
RUNS_CODE = {"exec", "attach", "debug", "cp", "port-forward", "proxy", "run", "--post-renderer"}
# Flags that send a command somewhere else than its named context.
REDIRECT_FLAGS = ("--server", "-s", "--cluster", "--user", "--token", "--as", "--as-group",
                  "--kube-apiserver", "--kube-token", "--kube-as-user", "--kube-as-group")


def single_simple_command(command):
    """True for one plain kubectl / helm / terraform / tofu call with no shell features."""
    if NOT_SIMPLE.search(command):
        return False
    tokens, env = peel(tokenize(command))
    if not tokens or re.split(r"[\\/]", tokens[0])[-1] not in ("kubectl", "helm", "terraform", "tofu"):
        return False
    if any(t in RUNS_CODE for t in tokens):
        return False  # kubectl exec / debug … or helm --post-renderer run any code
    if any(re.match(r"(oci|https?)://", t) for t in tokens):
        return False  # a chart from the network
    return not any(t.split("=", 1)[0] in REDIRECT_FLAGS or t.startswith("-auto-approve") for t in tokens)


def analyse_command(command, cwd, depth=0):
    hits, exported = [], {}
    if depth < 3:
        # `echo $(cat terraform.tfstate)`, `diff <(terraform output -json) x`: check the inner commands too
        unquoted = re.sub(r"'[^']*'", "''", command)  # `git commit -m 'do not run $(x)'` runs nothing
        for inner in re.findall(r"\$\(([^()]*)\)|<\(([^()]*)\)|`([^`]*)`", unquoted):
            hits.extend(analyse_command(next(part for part in inner if part), cwd, depth + 1))
        inline_code_reads_state(command, cwd)
    segments = [seg.strip() for seg in SEGMENT_SPLIT.split(command) if seg.strip()]
    for segment in segments:
        # `export KUBECONFIG=...; kubectl ...` must use the exported file for the later segments.
        exported.update(exported_vars(segment, cwd))
        hits.extend(analyse_segment(segment, cwd, depth, exported))
        tokens, _ = peel(tokenize(segment))
        if tokens[:1] == ["cd"] and len(tokens) == 2:
            cwd = os.path.join(cwd, os.path.expanduser(tokens[1]))  # `cd envs/prod && cat *`
    passed_on(segments, cwd)
    return hits


INTERPRETERS = {"python", "python3", "python2", "node", "perl", "ruby", "php", "deno", "bun"}
CODE_FLAGS = {"-c", "-e", "-E", "-r", "-p", "--eval", "--print"}


def inline_code_reads_state(command, cwd):
    """`python3 -c "import json; print(open('terraform.tfstate').read())"`: the segment split cuts the code
    at `;`, so the whole code string is checked here."""
    tokens = tokenize(command)
    for i, tok in enumerate(tokens[:-2]):
        if re.split(r"[\\/]", tok)[-1] in INTERPRETERS and tokens[i + 1] in CODE_FLAGS:
            if names_state_file(tokens[i + 2], cwd):
                raise Blocked(f"{tok} {tokens[i + 1]} code that opens a Terraform state or plan file")


def find_reaches_state(find_args, cwd):
    """True when `find <dirs>` without a name filter lists a state file."""
    if any(t in FIND_FILTERS for t in find_args):
        return False
    roots = []
    for tok in find_args:
        if tok.startswith(("-", "(", "!")):
            break
        roots.append(tok)
    return state_files_under(roots, [], cwd)


def passed_on(segments, cwd):
    """A state file name given to another command: `find -name '*.tfstate' | xargs cat`,
    `find . -type f | xargs cat`, `f=x.tfstate; cat $f`, `cat $(find . -type f)`."""
    listed, state_vars = False, set()
    for segment in segments:
        tokens = tokenize(segment)
        body, env = peel(tokens)
        state_vars |= {key for key, value in env.items() if names_state_file(value, cwd)}
        if not body:
            continue
        base = re.split(r"[\\/]", body[0])[-1]
        reader = base not in STATE_FILE_SAFE and base != "find"
        if base in ("xargs", "parallel", "while", "read") and listed:
            raise Blocked(f"Terraform state file names piped to {base} (state holds every value in clear text)")
        if reader and any(re.search(r"\$\{?" + re.escape(var) + r"\b", t) for var in state_vars for t in body[1:]):
            raise Blocked("a variable that holds a Terraform state file name (state holds every value in clear text)")
        for inner in re.findall(r"\$\(\s*find\s([^()]*)\)", segment):
            if reader and find_reaches_state(tokenize(inner), cwd):
                raise Blocked(f"{base} on files listed by find, which include a Terraform state file")
        if any(names_state_file(t, cwd) for t in body[1:]) or (base == "find" and find_reaches_state(body[1:], cwd)):
            listed = True


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
    original = command
    command = strip_heredocs(command)
    try:
        hits = analyse_command(command, cwd)
    except Blocked as exc:
        respond("deny", (
            f"devops-ai-kit: blocked: {exc}. The kit denies this command in any flag order. "
            "Do not try another way to run it; give the exact command to the user to run."
        ))
        return
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
            "devops-ai-kit: mutating command against a production target is blocked "
            "(the default; DEVOPS_KIT_BLOCK_PROD=0 turns it off): " + " | ".join(prod_targets) +
            ". Prepare the change as a GitOps PR or give the exact command to the user to run."
        )
    elif dev_only(hits, original):
        decision = "allow"
        reason += " (dev target matches DEVOPS_KIT_DEV_PATTERN: no confirmation)"
    else:
        decision = "ask"
    respond(decision, reason)


def dev_only(hits, command):
    """Opt-in: one plain kubectl/helm/terraform call whose context or workspace is a dev target.

    `command` is the original text (before heredoc bodies were dropped). No word of
    it may look like production, and it must not point to another server or user.
    """
    if not DEV_PATTERN or len(hits) != 1 or not single_simple_command(command):
        return False
    _, names, readonly = hits[0]
    tokens, env = peel(tokenize(command))
    words = [part for word in tokens + list(env.values()) for part in word.split("=")]  # -var-file=prod.tfvars
    try:
        return (not readonly and not is_prod(*names) and not is_prod(*words) and bool(names) and bool(names[0])
                and re.search(DEV_PATTERN, names[0], re.IGNORECASE) is not None)
    except re.error:
        return False


def respond(decision, reason):
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
