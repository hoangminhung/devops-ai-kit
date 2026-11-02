#!/usr/bin/env python3
"""List the places where a repo tells its tools to ignore live changes (devops-ai-kit).

In a running system the code is not always the truth. Terraform `ignore_changes`,
Argo CD `ignoreDifferences`, an HPA that owns `replicas`, Argo CD apps without
selfHeal: in all these cases the live value can differ from the code and the tool
does not report it. Before you trust the code, read these fields live.

The script reads only `*.tf`, `*.yaml`, `*.yml` and `*.tpl` files (never state,
.env or keys) and prints values only: file and line, resource kinds, names and
field paths. It never prints free text from the files.

Usage:
  find_ignore_rules.py [REPO_DIR] [--json]
Exit code: 0 (also when nothing is found), 2 when REPO_DIR is not a folder.
"""
import argparse
import json
import os
import re
import sys

SKIP_DIRS = {".git", ".terraform", "node_modules", "vendor", ".venv", "__pycache__"}
SAFE_VALUE = re.compile(r"[A-Za-z0-9_./\[\]\"*=:~{}$-]{1,120}")
MAX_FILE_BYTES = 2_000_000

TF_BLOCK = re.compile(r'^\s*(resource|data|module)\s+"([^"]+)"(?:\s+"([^"]+)")?')
TF_IGNORE = re.compile(r"\bignore_changes\s*=\s*(.*)")
YAML_KEY = re.compile(r"^(\s*)(-\s+)?([A-Za-z0-9_.\-/]+):\s*(.*?)\s*$")
HELM_LOOKUP = re.compile(r"\blookup\s+\"")

# What each finding means, in the kit's own words (never text from the repo).
MEANING = {
    "ignore_changes": "Terraform does not plan changes to these attributes; read them live (plan -refresh-only)",
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


def safe(value):
    """Keep a value only when it looks like a name or a path; drop everything else."""
    value = value.strip().strip("'\"")
    return value if SAFE_VALUE.fullmatch(value) else "<not shown>"


def finding(path, line, tool, rule, detail):
    return {"file": path, "line": line, "tool": tool, "rule": rule, "meaning": MEANING[rule], "detail": detail}


def scan_terraform(rel, lines):
    found, block = [], "?"
    i = 0
    while i < len(lines):
        match = TF_BLOCK.match(lines[i])
        if match:
            block = ".".join(p for p in match.groups()[1:] if p)
            if match.group(1) != "resource":
                block = f"{match.group(1)}.{block}"
        ignore = TF_IGNORE.search(lines[i])
        if ignore:
            start, text = i, ignore.group(1)
            while text.count("[") > text.count("]") and i + 1 < len(lines):
                i += 1
                text += " " + lines[i]
            text = text.split("#")[0].strip()
            if text.startswith("all"):
                attrs = ["all"]
            else:
                attrs = [safe(a) for a in re.split(r"[,\s]+", text.strip("[] ")) if a.strip()]
            found.append(finding(rel, start + 1, "terraform", "ignore_changes", f"{safe(block)}: {', '.join(attrs)}"))
        i += 1
    return found


def block_lines(lines, start, indent):
    """Lines under the key at `start` (more indented than `indent`)."""
    out = []
    for j in range(start + 1, len(lines)):
        text = lines[j]
        if not text.strip() or text.lstrip().startswith("#"):
            continue
        depth = len(text) - len(text.lstrip())
        # a list may sit at the key's own indent: `ignoreDifferences:` / `- kind: Deployment`
        if depth < indent or (depth == indent and not text.lstrip().startswith("- ")):
            break
        out.append((j, text))
    return out


def scan_yaml_doc(rel, lines, offset):
    found = []
    text = "\n".join(lines)
    kind = re.search(r"^kind:\s*([A-Za-z]+)", text, re.MULTILINE)
    kind = kind.group(1) if kind else ""
    name = re.search(r"^metadata:\s*\n(?:\s+.*\n)*?\s+name:\s*(\S+)", text + "\n", re.MULTILINE)
    name = safe(name.group(1)) if name else "?"

    for n, line in enumerate(lines):
        where = offset + n + 1
        # options written as list items (`- RespectIgnoreDifferences=true`) or annotation values
        if "RespectIgnoreDifferences=true" in line:
            found.append(finding(rel, where, "argocd", "RespectIgnoreDifferences", f"app {name}"))
        if "ServerSideApply=true" in line:
            found.append(finding(rel, where, "argocd", "ServerSideApply", f"{kind or '?'} {name}"))
        if "IgnoreExtraneous" in line and "compare-options" in line:
            found.append(finding(rel, where, "argocd", "IgnoreExtraneous", f"{kind or '?'} {name}"))
        if "Prune=false" in line and "sync-options" in line:
            found.append(finding(rel, where, "argocd", "prune off", f"{kind or '?'} {name}"))
        match = YAML_KEY.match(line)
        if not match:
            continue
        indent, key, value = len(match.group(1)) + len(match.group(2) or ""), match.group(3), match.group(4)
        if key == "ignoreDifferences" and kind in ("Application", "ApplicationSet"):
            entries, current = [], {}
            for _, sub in block_lines(lines, n, indent):
                item = YAML_KEY.match(sub)
                if item and item.group(2) and current:
                    entries.append(current)
                    current = {}
                if item and item.group(3) in ("kind", "name", "group", "namespace"):
                    current[item.group(3)] = safe(item.group(4))
                elif re.match(r"^\s*-\s+[\"']?[/.]", sub):
                    current.setdefault("paths", []).append(safe(sub.strip()[1:]))
                elif re.match(r"^\s*-\s+\S+$", sub) and "managers" in current:
                    current["managers"].append(safe(sub.strip()[1:]))
                elif item and item.group(3) == "managedFieldsManagers":
                    current["managers"] = []
            if current:
                entries.append(current)
            for entry in entries or [{}]:
                parts = [f"{k}={v}" for k, v in entry.items() if isinstance(v, str)]
                parts += [f"{k}={','.join(v)}" for k, v in entry.items() if isinstance(v, list) and v]
                found.append(finding(rel, where, "argocd", "ignoreDifferences", f"app {name}: " + " ".join(parts)))
        elif key.startswith("resource.customizations.ignoreDifferences"):
            found.append(finding(rel, where, "argocd", "argocd-cm ignoreDifferences", safe(key.split(".", 3)[-1])))
        elif key in ("resource.exclusions", "resource.customizations.ignoreResourceUpdates.all"):
            found.append(finding(rel, where, "argocd", "argocd-cm exclusions", safe(key)))
        elif key == "helm.sh/resource-policy" and "keep" in value:
            found.append(finding(rel, where, "helm", "resource-policy keep", f"{kind or '?'} {name}"))

    if kind == "Application":  # block or flow style: `automated: { prune: true, selfHeal: true }`
        if not re.search(r"\bautomated:", text):
            found.append(finding(rel, offset + 1, "argocd", "no automated sync", f"app {name}"))
        else:
            if not re.search(r"\bselfHeal:\s*true", text):
                found.append(finding(rel, offset + 1, "argocd", "selfHeal off", f"app {name}"))
            if not re.search(r"\bprune:\s*true", text):
                found.append(finding(rel, offset + 1, "argocd", "prune off", f"app {name}"))
    if kind in ("HorizontalPodAutoscaler", "ScaledObject", "VerticalPodAutoscaler"):
        target = re.search(r"(?:scaleTargetRef|targetRef):\s*\n((?:\s+.*\n?)+?)(?=^\S|\Z)", text + "\n", re.MULTILINE)
        tkind = re.search(r"kind:\s*(\S+)", target.group(1)) if target else None
        tname = re.search(r"name:\s*(\S+)", target.group(1)) if target else None
        detail = f"{name} → {safe(tkind.group(1)) if tkind else '?'}/{safe(tname.group(1)) if tname else '?'}"
        mode = re.search(r"updateMode:\s*\"?(\w+)", text)
        if kind == "VerticalPodAutoscaler":
            if mode and mode.group(1) == "Off":
                return found  # recommendations only
            detail += f" (updateMode {safe(mode.group(1)) if mode else 'Auto'})"
        found.append(finding(rel, offset + 1, "kubernetes", kind, detail))
    return found


def scan_yaml(rel, lines, in_templates):
    found, start = [], 0
    for n, line in enumerate(lines + ["---"]):
        if line.startswith("---"):
            found += scan_yaml_doc(rel, lines[start:n], start)
            start = n + 1
    if in_templates:
        for n, line in enumerate(lines):
            if HELM_LOOKUP.search(line):
                found.append(finding(rel, n + 1, "helm", "helm lookup", "template"))
    if os.path.basename(rel) in ("kustomization.yaml", "kustomization.yml", "Kustomization"):
        for n, line in enumerate(lines):
            match = YAML_KEY.match(line)
            if match and not match.group(1) and match.group(3) in (
                    "patches", "patchesStrategicMerge", "patchesJson6902", "replicas", "images", "components"):
                found.append(finding(rel, n + 1, "kustomize", "kustomize overlay", match.group(3)))
    return found


def scan(repo):
    results = []
    for folder, dirs, files in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            if not name.endswith((".tf", ".yaml", ".yml", ".tpl")):
                continue
            path = os.path.join(folder, name)
            rel = os.path.relpath(path, repo)
            try:
                if os.path.getsize(path) > MAX_FILE_BYTES:
                    continue
                with open(path, encoding="utf-8", errors="replace") as fh:
                    lines = fh.read().splitlines()
            except OSError:
                continue
            if name.endswith(".tf"):
                results += scan_terraform(rel, lines)
            else:
                in_templates = "templates" in rel.split(os.sep)
                results += scan_yaml(rel, lines, in_templates)
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
