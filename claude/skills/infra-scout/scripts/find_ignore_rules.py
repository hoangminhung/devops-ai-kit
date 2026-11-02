#!/usr/bin/env python3
"""List the places where a repo tells its tools to ignore live changes (devops-ai-kit).

In a running system the code is not always the truth. Terraform `ignore_changes`,
Argo CD `ignoreDifferences`, an HPA that owns `replicas`, Argo CD apps without
selfHeal: in all these cases the live value can differ from the code and the tool
does not report it. Before you trust the code, read these fields live.

The script reads only regular `*.tf`, `*.yaml`, `*.yml` and `*.tpl` files (never
state, .env or keys, never symlinks or devices) and prints values only: file and
line, resource kinds, names and field paths, each checked against a strict pattern.
It never prints free text from the files. Comments are ignored.

Usage:
  find_ignore_rules.py [REPO_DIR] [--json]
Exit code: 0 (also when nothing is found), 2 when REPO_DIR is not a folder.
"""
import argparse
import json
import os
import re
import stat
import sys

SKIP_DIRS = {".git", ".terraform", "node_modules", "vendor", ".venv", "__pycache__"}
MAX_FILE_BYTES = 2_000_000
MAX_LINE = 2000  # longer lines are not YAML or HCL anyone writes by hand

# Strict patterns: a value that does not match is shown as <not shown>.
K8S_NAME = re.compile(r"[a-z0-9](?:[-a-z0-9.]{0,61}[a-z0-9])?")
KIND = re.compile(r"[A-Z][A-Za-z0-9]{0,62}")
GROUP = re.compile(r"[a-z0-9](?:[-a-z0-9.]{0,99})?")
POINTER = re.compile(r"/[A-Za-z0-9_.~/-]{0,120}")
MANAGER = re.compile(r"[a-z0-9](?:[-a-z0-9.:_]{0,61}[a-z0-9])?")
TF_TYPE = re.compile(r"[a-z][a-z0-9_]{0,63}")
TF_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,63}")
TF_ATTR = re.compile(r'[a-z_][a-z0-9_]{0,63}(?:\[(?:\d{1,4}|"[A-Za-z0-9_./-]{1,40}")\]|\.[a-z_][a-z0-9_]{0,63}){0,8}')
CM_KEY = re.compile(r"[A-Za-z0-9.-]{0,100}_[A-Za-z][A-Za-z0-9]{0,62}|all")

TF_BLOCK = re.compile(r'^\s*(resource|data|module)\s+"([^"]{1,100})"(?:\s+"([^"]{1,100})")?')
TF_IGNORE = re.compile(r"\bignore_changes\s*=")
KEY_LINE = re.compile(r"([A-Za-z0-9_.\-/]{1,253}):(?:\s+(.*))?$")
HELM_LOOKUP = re.compile(r"\blookup\s+\"")
FLOW_FIELD = re.compile(r"\b(name|kind|selfHeal|prune):\s*([^,}\s]{1,100})")

# What each finding means, in the kit's own words (never text from the repo).
MEANING = {
    "ignore_changes": "Terraform never plans these attributes; compare the .tf value with the live value",
    "ignoreDifferences": "Argo CD does not report these fields as OutOfSync; read them live",
    "RespectIgnoreDifferences": "Argo CD also keeps the live value of ignored fields when it syncs",
    "argocd-cm ignoreDifferences": "Argo CD ignores these fields for every app of this kind",
    "argocd-cm exclusions": "Argo CD does not watch these resources at all",
    "no automated sync": "Argo CD syncs only by hand: live can differ from git until someone syncs",
    "selfHeal off": "Argo CD does not undo manual changes on the cluster",
    "prune off": "resources removed from git stay on the cluster",
    "IgnoreExtraneous": "Argo CD ignores live resources that are not in git",
    "ServerSideApply": "other field managers can own fields; check managedFields before you change them",
    "HorizontalPodAutoscaler": "the HPA owns replicas of the target; the replicas in git are not live",
    "ScaledObject": "KEDA owns replicas of the target; the replicas in git are not live",
    "VerticalPodAutoscaler": "the VPA changes container requests of the target",
    "resource-policy keep": "Helm does not delete this resource on uninstall or when it leaves the chart",
    "helm lookup": "the template reads live cluster state: rendered output depends on the cluster",
    "kustomize overlay": "the declared value is the rendered overlay (kustomize build), not the base",
}


def safe(value, pattern):
    value = (value or "").strip().strip("'\"")
    if "{{" in value:
        return "<templated>"
    return value if pattern.fullmatch(value) else "<not shown>"


def finding(path, line, tool, rule, detail):
    return {"file": path, "line": line, "tool": tool, "rule": rule, "meaning": MEANING[rule], "detail": detail}


# --- Terraform -------------------------------------------------------------

def hcl_code(text):
    """The lines with comments (`#`, `//`, `/* */`) replaced by spaces; line numbers stay the same."""
    out, i, quote = [], 0, False
    while i < len(text):
        ch = text[i]
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < len(text):
                out.append(text[i + 1])
                i += 1
            elif ch in ('"', "\n"):
                quote = False
        elif ch == '"':
            quote = True
            out.append(ch)
        elif ch == "#" or text.startswith("//", i):
            end = text.find("\n", i)
            end = len(text) if end < 0 else end
            out.append(" " * (end - i))
            i = end
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = len(text) if end < 0 else end + 2
            out.append(re.sub(r"[^\n]", " ", text[i:end]))
            i = end
            continue
        else:
            out.append(ch)
        i += 1
    return "".join(out).split("\n")


def scan_terraform(rel, text):
    found, block = [], "?"
    lines = hcl_code(text)
    i = 0
    while i < len(lines):
        match = TF_BLOCK.match(lines[i])
        if match:
            kind, first, second = match.groups()
            if kind == "module":
                block = "module." + safe(first, TF_NAME)
            else:
                block = ("data." if kind == "data" else "") + safe(first, TF_TYPE) + "." + safe(second, TF_NAME)
        ignore = TF_IGNORE.search(lines[i])
        if ignore:
            start, value = i, lines[i][ignore.end():]
            while value.count("[") > value.count("]") and i + 1 < len(lines) and i - start < 200:
                i += 1
                value += " " + lines[i]
            value = value.strip()
            if value.startswith("all"):
                attrs = ["all"]
            else:
                inner = value[value.find("[") + 1:value.rfind("]")] if "[" in value else value
                attrs = [safe(a, TF_ATTR) for a in re.split(r"[,\s]+", inner) if a.strip()]
            found.append(finding(rel, start + 1, "terraform", "ignore_changes", f"{block}: {', '.join(attrs) or '<empty>'}"))
        i += 1
    return found


# --- YAML ------------------------------------------------------------------

def yaml_code(line):
    """A YAML line without its comment (a `#` at the start or after a space, outside quotes)."""
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
    return line.rstrip()


def yaml_nodes(lines, offset):
    """One node per key or list item: {line, path, value, item}. Indent-based, no regex on the whole text."""
    nodes, stack = [], []  # stack of (indent, key)
    for n, raw in enumerate(lines):
        text = yaml_code(raw[:MAX_LINE].replace("\t", "  "))
        body = text.strip()
        if not body or body.startswith(("---", "%")):
            continue
        indent = len(text) - len(text.lstrip())
        item = body == "-" or body.startswith("- ")
        if item:
            body = body[1:].strip()
        # a list may sit at its key's own indent: `ignoreDifferences:` / `- kind: Deployment`
        while stack and (stack[-1][0] > indent or (stack[-1][0] == indent and (not item or stack[-1][1] == "[]"))):
            stack.pop()
        match = KEY_LINE.match(body)
        where = offset + n + 1
        if item:
            stack.append((indent, "[]"))  # the keys of this item sit under it
            nodes.append({"line": where, "path": tuple(k for _, k in stack), "value": "" if match else body, "item": True})
        if match:
            stack.append((indent + 2 if item else indent, match.group(1)))
            nodes.append({"line": where, "path": tuple(k for _, k in stack), "value": (match.group(2) or "").strip(), "item": False})
    return nodes


def value_at(nodes, path):
    return next((nd["value"] for nd in nodes if nd["path"] == path and not nd["item"]), None)


def flow_field(value, field):
    """`{ prune: true, selfHeal: true }` → the value of one field."""
    match = next((m for m in FLOW_FIELD.finditer(value or "") if m.group(1) == field), None)
    return match.group(2) if match else None


def ignore_entries(nodes, base):
    """The entries of an ignoreDifferences list at path `base`."""
    entries, current = [], None
    for nd in nodes:
        rest = nd["path"][len(base):]
        if nd["path"][:len(base)] != base or not rest:
            continue
        if rest == ("[]",):
            current = {}
            entries.append(current)
        if current is None or len(rest) < 2:
            continue
        field, value = rest[1], nd["value"]
        if field in ("kind", "name", "group", "namespace") and len(rest) == 2 and value:
            current[field] = safe(value, {"kind": KIND, "group": GROUP}.get(field, K8S_NAME))
        elif rest[-1] == "[]" and value and field == "jsonPointers":
            current.setdefault("paths", []).append(safe(value, POINTER))
        elif rest[-1] == "[]" and value and field == "jqPathExpressions":
            current.setdefault("paths", []).append("<jq expression>")
        elif rest[-1] == "[]" and value and field == "managedFieldsManagers":
            current.setdefault("managers", []).append(safe(value, MANAGER))
    return entries


def scan_argocd_app(rel, nodes, kind, name, first):
    found = []
    spec = ("spec",) if kind == "Application" else ("spec", "template", "spec")
    for nd in nodes:
        if nd["path"] == spec + ("ignoreDifferences",) and not nd["item"]:
            for entry in ignore_entries(nodes, nd["path"]) or [{}]:
                parts = [f"{k}={v}" for k, v in entry.items() if isinstance(v, str)]
                parts += [f"{k}={','.join(v)}" for k, v in entry.items() if isinstance(v, list)]
                found.append(finding(rel, nd["line"], "argocd", "ignoreDifferences",
                                     f"app {name}: " + (" ".join(parts) or "<see file>")))
    policy_path = spec + ("syncPolicy",)
    policy = [nd for nd in nodes if nd["path"][:len(policy_path)] == policy_path]
    if any("{{" in nd["value"] for nd in policy):
        return found  # templated: check the rendered app instead
    automated = next((nd for nd in policy if nd["path"] == policy_path + ("automated",) and not nd["item"]), None)
    if automated is None:
        return found + [finding(rel, first, "argocd", "no automated sync", f"app {name}")]
    for field, rule in (("selfHeal", "selfHeal off"), ("prune", "prune off")):
        nested = value_at(policy, policy_path + ("automated", field))
        value = nested if nested is not None else flow_field(automated["value"], field)
        if (value or "").lower() != "true":
            found.append(finding(rel, automated["line"], "argocd", rule, f"app {name}"))
    return found


def scan_yaml_doc(rel, lines, offset):
    nodes = yaml_nodes(lines, offset)
    if not nodes:
        return []
    found = []
    raw_kind = value_at(nodes, ("kind",))
    kind = safe(raw_kind, KIND) if raw_kind else ""
    name = value_at(nodes, ("metadata", "name")) or flow_field(value_at(nodes, ("metadata",)), "name")
    name = safe(name, K8S_NAME) if name else "?"
    first = nodes[0]["line"]
    label = f"{kind or '?'} {name}"

    for nd in nodes:
        value, path = nd["value"], nd["path"]
        if path[-2:] == ("syncOptions", "[]"):
            if value == "RespectIgnoreDifferences=true":
                found.append(finding(rel, nd["line"], "argocd", "RespectIgnoreDifferences", label))
            elif value == "ServerSideApply=true":
                found.append(finding(rel, nd["line"], "argocd", "ServerSideApply", label))
        if path[:2] == ("metadata", "annotations") and len(path) == 3:
            key = path[2]
            if key == "argocd.argoproj.io/compare-options" and "IgnoreExtraneous" in value:
                found.append(finding(rel, nd["line"], "argocd", "IgnoreExtraneous", label))
            if key == "argocd.argoproj.io/sync-options" and "Prune=false" in value:
                found.append(finding(rel, nd["line"], "argocd", "prune off", label))
            if key == "argocd.argoproj.io/sync-options" and "ServerSideApply=true" in value:
                found.append(finding(rel, nd["line"], "argocd", "ServerSideApply", label))
            if key == "helm.sh/resource-policy" and "keep" in value:
                found.append(finding(rel, nd["line"], "helm", "resource-policy keep", label))

    if kind in ("Application", "ApplicationSet"):
        found += scan_argocd_app(rel, nodes, kind, name, first)

    if kind == "ConfigMap" and name in ("argocd-cm", "<templated>"):
        for nd in nodes:
            if nd["path"][:1] == ("data",) and len(nd["path"]) == 2:
                key = nd["path"][1]
                if key.startswith("resource.customizations.ignoreDifferences."):
                    found.append(finding(rel, nd["line"], "argocd", "argocd-cm ignoreDifferences",
                                         safe(key.split(".", 3)[-1], CM_KEY)))
                elif key in ("resource.exclusions", "resource.customizations.ignoreResourceUpdates.all"):
                    found.append(finding(rel, nd["line"], "argocd", "argocd-cm exclusions", key))

    if kind in ("HorizontalPodAutoscaler", "ScaledObject", "VerticalPodAutoscaler"):
        ref = ("spec", "targetRef") if kind == "VerticalPodAutoscaler" else ("spec", "scaleTargetRef")
        tkind = value_at(nodes, ref + ("kind",)) or flow_field(value_at(nodes, ref), "kind") or "Deployment"
        tname = value_at(nodes, ref + ("name",)) or flow_field(value_at(nodes, ref), "name")
        detail = f"{name} → {safe(tkind, KIND)}/{safe(tname, K8S_NAME) if tname else '?'}"
        if kind == "VerticalPodAutoscaler":
            mode = (value_at(nodes, ("spec", "updatePolicy", "updateMode")) or "Auto").strip("'\"")
            if mode == "Off":
                return found  # recommendations only
            detail += f" (updateMode {safe(mode, KIND)})"
        found.append(finding(rel, first, "kubernetes", kind, detail))
    return found


def scan_yaml(rel, lines, in_templates):
    found, start = [], 0
    for n, line in enumerate(lines + ["---"]):
        if line.startswith("---"):
            found += scan_yaml_doc(rel, lines[start:n], start)
            start = n + 1
    if in_templates:
        for n, line in enumerate(lines):
            if HELM_LOOKUP.search(line[:MAX_LINE]):
                found.append(finding(rel, n + 1, "helm", "helm lookup", "template"))
    if os.path.basename(rel) in ("kustomization.yaml", "kustomization.yml"):
        for nd in yaml_nodes(lines, 0):
            if len(nd["path"]) == 1 and nd["path"][0] in (
                    "patches", "patchesStrategicMerge", "patchesJson6902", "replicas", "images", "components"):
                found.append(finding(rel, nd["line"], "kustomize", "kustomize overlay", nd["path"][0]))
    return found


# --- walk ------------------------------------------------------------------

def regular_file(path):
    """Only plain files: no symlinks (they can point outside the repo), FIFOs or devices."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and info.st_size <= MAX_FILE_BYTES


def is_worktree(folder):
    """A git worktree inside the repo (`.git` file → `…/worktrees/<name>`): a copy, so its findings repeat."""
    marker = os.path.join(folder, ".git")
    if not regular_file(marker):
        return False
    try:
        with open(marker, encoding="utf-8", errors="replace") as fh:
            return "/worktrees/" in fh.read(500)
    except OSError:
        return False


def scan(repo):
    results = []
    for folder, dirs, files in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not is_worktree(os.path.join(folder, d)))
        for name in sorted(files):
            if not name.endswith((".tf", ".yaml", ".yml", ".tpl")):
                continue
            path = os.path.join(folder, name)
            if not regular_file(path):
                continue
            rel = os.path.relpath(path, repo)
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            if name.endswith(".tf"):
                results += scan_terraform(rel, text)
            else:
                results += scan_yaml(rel, text.splitlines(), "templates" in rel.split(os.sep))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a Markdown table")
    args = parser.parse_args()
    if not os.path.isdir(args.repo):
        print(f"error: {args.repo} is not a folder", file=sys.stderr)
        return 2
    results = scan(args.repo)
    if args.json:
        print(json.dumps(results, indent=2))
        return 0
    if not results:
        print("No ignore rules or live-owned fields found.")
        return 0
    print("| File:line | Tool | Rule | Detail | What it means |")
    print("|---|---|---|---|---|")
    for item in results:
        print(f"| {item['file']}:{item['line']} | {item['tool']} | {item['rule']} | {item['detail']} | {item['meaning']} |")
    print(f"\n{len(results)} finding(s). Read these fields live; the tools do not report them as drift.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
