#!/usr/bin/env python3
"""Rule coverage for /infra-rulebook (devops-ai-kit).

Finds the infrastructure files in a repo by their content, checks which ones the
`paths` of the kit's technology rules already match, and proposes project-level
rule files for the rest. Standard library only, so it runs without PyYAML.

Usage:
  coverage.py report [--repo DIR] [--rules-dir DIR] [--json]
  coverage.py emit TECH [--repo DIR] [--rules-dir DIR] [--path GLOB ...]

`report` prints coverage per technology and suggested globs for uncovered files.
`emit` prints the content of `.claude/rules/devops-kit-paths-<TECH>.md` (it never
writes files: the skill shows the result and asks the user first).
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

TECHS = ("terraform", "ansible", "kubernetes", "helm", "argocd", "dockerfile", "observability")
TECH_TITLES = {
    "terraform": "Terraform / OpenTofu", "ansible": "Ansible", "kubernetes": "Kubernetes",
    "helm": "Helm", "argocd": "Argo CD", "dockerfile": "Dockerfile", "observability": "observability",
}
PROJECT_RULE_PREFIX = "devops-kit-paths-"
SKIP_DIRS = {".git", ".terraform", "node_modules", ".venv", "venv", "__pycache__", ".claude", "vendor", ".tox"}
YAML_SUFFIXES = (".yaml", ".yml")
MAX_READ = 64 * 1024

ARGO_KINDS = {"Application", "ApplicationSet", "AppProject"}
OBSERVABILITY_KINDS = {"PrometheusRule", "ServiceMonitor", "PodMonitor", "Probe", "AlertmanagerConfig",
                       "GrafanaDashboard", "GrafanaDatasource"}
ANSIBLE_ROLE_PARTS = {"tasks", "handlers", "defaults", "vars", "meta"}


# --- globs ------------------------------------------------------------------

def glob_to_regex(glob):
    """Translate a Claude Code `paths` glob (`**`, `*`, `?`, `{a,b}`) to a regex."""
    out, i = [], 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        elif glob[i] == "{":
            end = glob.find("}", i)
            if end == -1:
                out.append(re.escape("{"))
                i += 1
                continue
            options = glob[i + 1:end].split(",")
            out.append("(?:" + "|".join(re.escape(o) for o in options) + ")")
            i = end + 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def matches_any(rel_path, globs):
    return any(glob_to_regex(g).match(rel_path) for g in globs)


# --- rule files ---------------------------------------------------------------

def read_paths(rule_file):
    """`paths` list from a rule's frontmatter (simple YAML list, no PyYAML needed)."""
    try:
        text = rule_file.read_text(encoding="utf-8")
    except OSError:
        return []
    if not text.startswith("---\n"):
        return []
    end = text.find("\n---", 4)
    paths, in_paths = [], False
    for line in text[4:end].splitlines():
        if re.match(r"^paths:\s*$", line):
            in_paths = True
        elif in_paths and re.match(r"^\s+-\s+", line):
            paths.append(line.split("-", 1)[1].strip().strip("'\""))
        elif line.strip() and not line.startswith(" "):
            in_paths = False
    return paths


def kit_rule_paths(rules_dir):
    return {tech: read_paths(rules_dir / f"{tech}.md") for tech in TECHS}


def project_rule_paths(repo):
    found = {}
    for rule in sorted((repo / ".claude" / "rules").glob(f"{PROJECT_RULE_PREFIX}*.md")):
        tech = rule.stem[len(PROJECT_RULE_PREFIX):]
        if tech in TECHS:
            found[tech] = read_paths(rule)
    return found


# --- classification -------------------------------------------------------------

def read_head(path):
    try:
        with open(path, "rb") as fh:
            return fh.read(MAX_READ).decode("utf-8", "replace")
    except OSError:
        return ""


def yaml_kinds(text):
    """(apiVersion, kind) pairs of the top-level YAML documents."""
    pairs = []
    for doc in re.split(r"(?m)^---\s*$", text):
        api = re.search(r"(?m)^apiVersion:\s*['\"]?([^\s'\"]+)", doc)
        kind = re.search(r"(?m)^kind:\s*['\"]?([^\s'\"]+)", doc)
        if api and kind:
            pairs.append((api.group(1), kind.group(1)))
    return pairs


def is_ansible_playbook(text):
    if not re.search(r"(?m)^-\s", text):
        return False
    return bool(re.search(r"(?m)^(-\s+|\s+)(hosts|import_playbook):\s", text))


def chart_dirs(files):
    return {f.parent for f in files if f.name == "Chart.yaml"}


def in_chart(rel, charts):
    return any(c == rel.parent or c in rel.parents for c in charts)


def classify(rel, text, charts):
    """Set of technologies a file belongs to. `rel` is a relative Path."""
    name, techs = rel.name, set()
    if name.endswith((".tf", ".tfvars", ".tftest.hcl")) or name in ("terragrunt.hcl", ".terraform.lock.hcl"):
        techs.add("terraform")
    if (name in ("Dockerfile", "Containerfile", ".dockerignore") or name.startswith("Dockerfile.")
            or name.endswith((".dockerfile", ".Dockerfile"))):
        techs.add("dockerfile")
    if name.endswith(".alloy"):
        techs.add("observability")
    if name == "ansible.cfg" or any(p in ("group_vars", "host_vars") for p in rel.parts[:-1]):
        techs.add("ansible")
    parts = rel.parts
    for i, part in enumerate(parts[:-2]):
        if part == "roles" and parts[i + 2] in ANSIBLE_ROLE_PARTS:
            techs.add("ansible")
    if name in ("Chart.yaml", "Chart.lock") or name.startswith("helmfile"):
        techs.add("helm")
    elif in_chart(rel, charts) and (name.startswith("values") or "templates" in parts):
        techs.add("helm")
    if name.endswith(".json") and '"panels"' in text and '"schemaVersion"' in text:
        techs.add("observability")
    if name.endswith(YAML_SUFFIXES) and "helm" not in techs:
        if name in ("kustomization.yaml", "kustomization.yml"):
            techs.add("kubernetes")
        for api, kind in yaml_kinds(text):
            if api.startswith("argoproj.io/") and kind in ARGO_KINDS:
                techs.add("argocd")
            elif kind in OBSERVABILITY_KINDS:
                techs.update(("observability", "kubernetes"))
            else:
                techs.add("kubernetes")
        if not techs and is_ansible_playbook(text):
            techs.add("ansible")
    if name in ("hosts", "hosts.ini") or (name.endswith(".ini") and "inventor" in str(rel.parent)):
        techs.add("ansible")
    return techs


def repo_files(repo):
    for root, dirs, names in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(names):
            yield (Path(root) / name).relative_to(repo)


# --- report ----------------------------------------------------------------------

def suffix_pattern(name):
    if name.endswith(YAML_SUFFIXES):
        return "*.{yaml,yml}"
    suffix = Path(name).suffix
    return f"*{suffix}" if suffix else name


def suggest_globs(uncovered):
    """Narrow globs that cover the uncovered files, grouped by top-level folder."""
    groups = {}
    for rel in uncovered:
        top = rel.parts[0] if len(rel.parts) > 1 else ""
        groups.setdefault((top, suffix_pattern(rel.name)), []).append(rel)
    globs = []
    for (top, pattern), files in sorted(groups.items()):
        if not top:
            globs.extend(sorted({f.name for f in files}))
            continue
        common = Path(os.path.commonpath([str(f.parent) for f in files])).as_posix()
        names = {f.name for f in files}
        if len(files) > 1 and len(names) == 1:
            pattern = names.pop()  # e.g. every Argo CD app is apps/<x>/app.yaml: do not match the manifests next to it
        globs.append(f"{common}/**/{pattern}")
    return globs


def build_report(repo, rules_dir):
    repo = repo.resolve()
    kit = kit_rule_paths(rules_dir)
    project = project_rule_paths(repo)
    files = list(repo_files(repo))
    charts = chart_dirs(files)
    report = {t: {"files": 0, "covered": 0, "uncovered": [], "project_rule": t in project} for t in TECHS}
    for rel in files:
        text = read_head(repo / rel) if rel.name.endswith(YAML_SUFFIXES + (".json",)) else ""
        for tech in classify(rel, text, charts):
            entry = report[tech]
            entry["files"] += 1
            globs = kit[tech] + project.get(tech, [])
            if matches_any(rel.as_posix(), globs):
                entry["covered"] += 1
            else:
                entry["uncovered"].append(rel)
    for entry in report.values():
        entry["suggested_paths"] = suggest_globs(entry["uncovered"])
        entry["uncovered"] = [p.as_posix() for p in entry["uncovered"]]
    return report


def print_report(report):
    print(f"{'Technology':<14} {'Files':>5} {'Covered':>7}  Uncovered")
    for tech, e in report.items():
        if not e["files"]:
            continue
        print(f"{tech:<14} {e['files']:>5} {e['covered']:>7}  {len(e['uncovered'])}")
        for path in e["uncovered"][:10]:
            print(f"{'':<29}- {path}")
        if len(e["uncovered"]) > 10:
            print(f"{'':<29}  ... {len(e['uncovered']) - 10} more")
        if e["suggested_paths"]:
            print(f"{'':<29}suggested paths: {', '.join(e['suggested_paths'])}")


# --- emit ------------------------------------------------------------------------

def rule_pointer(rules_dir, tech):
    target = (rules_dir / f"{tech}.md").expanduser()
    home = Path.home()
    try:
        return "~/" + target.relative_to(home).as_posix()
    except ValueError:
        return target.as_posix()


def emit_rule(tech, globs, rules_dir):
    lines = ["---", "paths:"] + [f'  - "{g}"' for g in globs] + ["---", ""]
    lines += [
        f"# devops-ai-kit: {TECH_TITLES[tech]} files in this repo",
        "",
        "<!-- Generated by /infra-rulebook (devops-ai-kit). This file lists paths only; the standards stay in the kit.",
        "     Run /infra-rulebook again to update it. -->",
        "",
        f"The files that match these paths are {TECH_TITLES[tech]} files. Before you edit them, read "
        f"`{rule_pointer(rules_dir, tech)}` and follow it.",
        "That kit rule is the only source of these standards: do not copy them into this repo.",
        "",
    ]
    return "\n".join(lines)


def default_rules_dir():
    base = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    return Path(base).expanduser() / "rules" / "devops-kit"


def main(argv=None):
    parser = argparse.ArgumentParser(description="devops-ai-kit rule coverage")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("report", "emit"):
        p = sub.add_parser(name)
        p.add_argument("--repo", default=".", type=Path)
        p.add_argument("--rules-dir", type=Path, default=None)
        if name == "report":
            p.add_argument("--json", action="store_true")
        else:
            p.add_argument("tech", choices=TECHS)
            p.add_argument("--path", action="append", dest="paths", help="glob to include (repeatable)")
    args = parser.parse_args(argv)
    rules_dir = (args.rules_dir or default_rules_dir()).expanduser()
    if not (rules_dir / "00-core.md").exists():
        print(f"devops-ai-kit rules not found in {rules_dir} (install the kit or pass --rules-dir)", file=sys.stderr)
        return 2
    if args.cmd == "report":
        report = build_report(args.repo, rules_dir)
        if args.json:
            json.dump(report, sys.stdout, indent=2)
            print()
        else:
            print_report(report)
        return 0
    globs = args.paths
    if not globs:
        report = build_report(args.repo, rules_dir)
        existing = project_rule_paths(args.repo.resolve()).get(args.tech, [])
        globs = existing + [g for g in report[args.tech]["suggested_paths"] if g not in existing]
    if not globs:
        print(f"nothing to add: every {args.tech} file is already covered", file=sys.stderr)
        return 1
    sys.stdout.write(emit_rule(args.tech, globs, rules_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
