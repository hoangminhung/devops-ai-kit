#!/usr/bin/env python3
"""devops-ai-kit installer.

Copies rules, skills, agents and hooks into the Claude Code user config dir
(~/.claude, or $CLAUDE_CONFIG_DIR) and merges permission rules + the hook into
settings.json. Everything it adds is recorded in a manifest so that a re-install
(update) or an uninstall removes exactly what the kit added and nothing else.

Usage:
  kit.py install   [--dry-run] [--no-settings] [--lang en|vi] [--env KEY=VALUE ...]
  kit.py uninstall [--dry-run]
  kit.py check
"""

import argparse
import datetime as dt
import json
import os
import shutil
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):  # Windows consoles default to a legacy code page
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

KIT_DIR = Path(__file__).resolve().parent.parent
SRC = KIT_DIR / "claude"
DEFAULT_CLAUDE_DIR = Path.home() / ".claude"
CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", DEFAULT_CLAUDE_DIR)).expanduser()
MANIFEST = CLAUDE_DIR / ".devops-kit-manifest.json"
SETTINGS = CLAUDE_DIR / "settings.json"
HOOK_MARKER = "hooks/devops-kit/infra-context-guard.py"
LANGS = ("en", "vi")
DEFAULT_LANG = "en"
LANG_RULE = Path("rules/devops-kit/01-language.md")  # inside a kit-owned dir, so update/uninstall remove it
GUIDE = "docs/en/guide.md"
VERSION = (KIT_DIR / "VERSION").read_text().strip() if (KIT_DIR / "VERSION").exists() else "unknown"

TOOLS = [
    ("kubectl", "core"), ("helm", "core"), ("terraform", "core / or tofu"),
    ("python3", "hook + installer"), ("git", "core"), ("jq", "handy for recon"),
    ("tflint", "terraform gate"), ("trivy", "terraform/image gate"),
    ("kubeconform", "k8s/helm gate"), ("ansible-lint", "ansible gate"),
    ("promtool", "prometheus rules gate"), ("amtool", "alertmanager gate"),
    ("alloy", "alloy config gate"), ("hadolint", "dockerfile gate"),
    ("infracost", "cost gate"), ("az", "azure"), ("argocd", "gitops (optional)"),
    ("velero", "backup (optional)"), ("helm-diff", "helm plugin: helm diff"),
]


class Ops:
    """Filesystem operations that honour --dry-run and log what they do."""

    def __init__(self, dry_run):
        self.dry_run = dry_run

    def log(self, msg):
        print(("[dry-run] " if self.dry_run else "") + msg)

    def remove(self, path):
        if not path.exists() and not path.is_symlink():
            return
        self.log(f"remove   {path}")
        if self.dry_run:
            return
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()

    def backup(self, path, backup_root):
        dest = backup_root / path.relative_to(CLAUDE_DIR)
        self.log(f"backup   {path} -> {dest}")
        if self.dry_run:
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dest))

    def copy(self, src, dest):
        self.log(f"install  {dest}")
        if self.dry_run:
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(src, dest)

    def write_json(self, path, data):
        self.log(f"write    {path}")
        if self.dry_run:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)


def kit_items():
    """(source, destination-relative-to-CLAUDE_DIR) pairs owned by the kit."""
    items = [(SRC / "rules" / "devops-kit", Path("rules/devops-kit")),
             (SRC / "hooks" / "devops-kit", Path("hooks/devops-kit"))]
    items += [(p, Path("skills") / p.name) for p in sorted((SRC / "skills").iterdir()) if p.is_dir()]
    items += [(p, Path("agents") / p.name) for p in sorted((SRC / "agents").glob("*.md"))]
    return items


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        sys.exit(f"ERROR: {path} is not valid JSON ({exc}). Fix it first; nothing was changed.")


def python_launcher():
    """Command that starts Python 3 inside a hook, on this OS.

    Hooks run through bash (Git Bash on Windows) or PowerShell, so the result
    must work in both: `py -3` (Windows launcher) or an unquoted absolute path.
    """
    if os.name == "nt":
        if shutil.which("py"):
            return "py -3"
        exe = Path(sys.executable).as_posix()
        if " " in exe:
            print(f"WARNING: Python path contains spaces ({exe}); the hook may not start. "
                  "Install the Python launcher (py.exe) or Python in a path without spaces.")
            return f'"{exe}"'
        return exe
    return "python3"


def settings_fragment():
    raw = (SRC / "settings.devops-kit.json").read_text(encoding="utf-8")
    claude_dir = CLAUDE_DIR.as_posix()
    if CLAUDE_DIR == DEFAULT_CLAUDE_DIR:
        rule_dir = "~/.claude"
    else:
        # Absolute paths in permission rules use a leading "//"
        rule_dir = "/" + claude_dir if claude_dir.startswith("/") else claude_dir
    fragment = json.loads(raw.replace("__CLAUDE_DIR_RULE__", rule_dir))
    for entry in fragment["hooks"]["PreToolUse"]:
        for hook in entry["hooks"]:
            hook["command"] = (hook["command"]
                               .replace("__PYTHON__", python_launcher())
                               .replace("__CLAUDE_DIR__", claude_dir))
    return fragment


def remove_settings_additions(settings, added, include_env=True):
    perms = settings.get("permissions", {})
    for kind, rules in (added.get("permissions") or {}).items():
        current = perms.get(kind, [])
        perms[kind] = [r for r in current if r not in set(rules)]
        if not perms[kind]:
            perms.pop(kind, None)
    if not perms:
        settings.pop("permissions", None)
    if added.get("hook"):
        pre = settings.get("hooks", {}).get("PreToolUse", [])
        kept = []
        for entry in pre:
            hooks = [h for h in entry.get("hooks", []) if HOOK_MARKER not in h.get("command", "")]
            if hooks:
                entry["hooks"] = hooks
                kept.append(entry)
        if kept:
            settings["hooks"]["PreToolUse"] = kept
        elif "hooks" in settings:
            settings["hooks"].pop("PreToolUse", None)
            if not settings["hooks"]:
                settings.pop("hooks")
    for key, previous in ((added.get("env") or {}) if include_env else {}).items():
        env = settings.setdefault("env", {})
        if previous is None:
            env.pop(key, None)
        else:
            env[key] = previous
        if not env:
            settings.pop("env", None)
    return settings


def add_settings(settings, fragment, env_pairs):
    added = {"permissions": {}, "hook": False, "env": {}}
    perms = settings.setdefault("permissions", {})
    for kind in ("deny", "ask", "allow"):
        current = perms.setdefault(kind, [])
        new = [r for r in fragment["permissions"].get(kind, []) if r not in current]
        current.extend(new)
        if new:
            added["permissions"][kind] = new
        if not current:
            perms.pop(kind)
    pre = settings.setdefault("hooks", {}).setdefault("PreToolUse", [])
    already = any(HOOK_MARKER in h.get("command", "") for e in pre for h in e.get("hooks", []))
    if not already:
        pre.extend(fragment["hooks"]["PreToolUse"])
        added["hook"] = True
    for pair in env_pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            sys.exit(f"ERROR: --env expects KEY=VALUE, got: {pair}")
        env = settings.setdefault("env", {})
        added["env"][key] = env.get(key)
        env[key] = os.path.expanduser(value)
    return settings, added


def install(args):
    ops = Ops(args.dry_run)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = CLAUDE_DIR / ".devops-kit-backup" / ts
    suffix = 1
    while backup_root.exists():  # two installs in the same second must not overwrite a backup
        backup_root = CLAUDE_DIR / ".devops-kit-backup" / f"{ts}-{suffix}"
        suffix += 1
    manifest = load_json(MANIFEST, {})
    previous_items = {Path(p) for p in manifest.get("items", [])}
    # Without --lang on a re-install, keep the language chosen earlier.
    lang = args.lang or manifest.get("lang") or DEFAULT_LANG

    print(f"devops-ai-kit {VERSION} → {CLAUDE_DIR} (output language: {lang})")
    # 1. Remove what a previous install of the kit put there.
    for rel in sorted(previous_items):
        ops.remove(CLAUDE_DIR / rel)

    # 2. Copy kit items; anything foreign already at a destination is backed up.
    items = kit_items()
    for src, rel in items:
        dest = CLAUDE_DIR / rel
        if (dest.exists() or dest.is_symlink()) and rel not in previous_items:
            ops.backup(dest, backup_root)
        elif (dest.exists() or dest.is_symlink()) and args.dry_run:
            pass  # would have been removed in step 1
        ops.copy(src, dest)
    ops.copy(SRC / "lang" / f"{lang}.md", CLAUDE_DIR / LANG_RULE)
    hook = CLAUDE_DIR / "hooks/devops-kit/infra-context-guard.py"
    if not args.dry_run and hook.exists():
        hook.chmod(0o755)

    # 3. Settings: undo the previous additions, then add the current set.
    added = {}
    # Backup of the user's settings.json from the first install (None: the kit created it).
    settings_original = manifest.get("settings_original", "" if manifest else None)
    if not args.no_settings:
        settings = load_json(SETTINGS, {})
        if not manifest and SETTINGS.exists():
            settings_original = str(backup_root / "settings.json")
        if SETTINGS.exists():
            ops.log(f"backup   {SETTINGS} -> {backup_root / 'settings.json'}")
            if not args.dry_run:
                backup_root.mkdir(parents=True, exist_ok=True)
                shutil.copy2(SETTINGS, backup_root / "settings.json")
        previous = manifest.get("settings", {})
        # Without --env on a re-install, keep the env vars an earlier install added.
        replace_env = bool(args.env)
        settings = remove_settings_additions(settings, previous, include_env=replace_env)
        settings, added = add_settings(settings, settings_fragment(), args.env or [])
        if not replace_env and previous.get("env"):
            added["env"] = previous["env"]
        ops.write_json(SETTINGS, settings)
        counts = {k: len(v) for k, v in added["permissions"].items()}
        print(f"settings: added permission rules {counts or '{}'}; hook added: {added['hook']}; env: {list(added['env']) or '[]'}")
    elif manifest.get("settings"):
        added = manifest["settings"]  # keep tracking what an earlier install added

    ops.write_json(MANIFEST, {
        "kit_version": VERSION,
        "kit_dir": str(KIT_DIR),
        "installed_at": ts,
        "lang": lang,
        "items": [str(rel) for _, rel in items],
        "settings": added,
        "settings_original": settings_original,
    })
    print("\nDone. Next steps:")
    print("  1. Close running `claude` sessions and start a new one.")
    print("  2. In the new session check: /context (rules), /skills, /agents, /permissions, /hooks")
    print(f"  3. Optional: build a read-only kubeconfig for AI → see {GUIDE} (section 3)")
    print(f"  Backups of anything replaced: {backup_root if backup_root.exists() else '(none)'}")


def restore_settings(ops, settings, original):
    """Write settings.json after uninstall; give back the user's exact file when nothing else changed.

    original: path of the first-install backup, None if the kit created settings.json,
    "" if unknown (manifest from an older kit version).
    """
    if original is None and not settings:
        ops.remove(SETTINGS)
        return
    if original:
        backup = Path(original)
        try:
            same = backup.exists() and json.loads(backup.read_text(encoding="utf-8")) == settings
        except ValueError:
            same = False
        if same:
            ops.log(f"restore  {SETTINGS} <- {backup}")
            if not ops.dry_run:
                shutil.copy2(backup, SETTINGS)
            return
    ops.write_json(SETTINGS, settings)


def uninstall(args):
    ops = Ops(args.dry_run)
    manifest = load_json(MANIFEST, None)
    if not manifest:
        sys.exit(f"No manifest at {MANIFEST}: nothing to uninstall.")
    for rel in manifest.get("items", []):
        ops.remove(CLAUDE_DIR / rel)
    for parent in sorted({(CLAUDE_DIR / rel).parent for rel in manifest.get("items", [])}, reverse=True):
        if not ops.dry_run and parent != CLAUDE_DIR and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
    if manifest.get("settings") and SETTINGS.exists():
        settings = remove_settings_additions(load_json(SETTINGS, {}), manifest["settings"])
        restore_settings(ops, settings, manifest.get("settings_original", ""))
    ops.remove(MANIFEST)
    print("Uninstalled. Backups (if any) remain in", CLAUDE_DIR / ".devops-kit-backup")


def check(_args):
    ok = True
    manifest = load_json(MANIFEST, None)
    print(f"Claude config dir : {CLAUDE_DIR}")
    if not manifest:
        print("Kit               : NOT INSTALLED (run ./install.sh)")
        ok = False
    else:
        missing = [p for p in manifest.get("items", []) if not (CLAUDE_DIR / p).exists()]
        print(f"Kit               : v{manifest.get('kit_version')} installed {manifest.get('installed_at')}"
              + (f" — MISSING: {missing}" if missing else ""))
        ok &= not missing
        lang_ok = (CLAUDE_DIR / LANG_RULE).exists()
        print(f"Output language   : {manifest.get('lang', DEFAULT_LANG)}"
              + ("" if lang_ok else f" — MISSING {LANG_RULE}"))
        ok &= lang_ok
    settings = load_json(SETTINGS, {})
    hook_ok = any(HOOK_MARKER in h.get("command", "")
                  for e in settings.get("hooks", {}).get("PreToolUse", []) for h in e.get("hooks", []))
    print(f"Context-guard hook: {'registered' if hook_ok else 'NOT registered'}")
    kubeconfig = settings.get("env", {}).get("KUBECONFIG")
    if kubeconfig:
        exists = Path(kubeconfig).expanduser().exists()
        print(f"AI KUBECONFIG     : {kubeconfig} ({'exists' if exists else 'MISSING — kubectl in Claude sessions will fail'})")
        ok &= exists
    else:
        print(f"AI KUBECONFIG     : not set (Claude uses your normal kubeconfig — see {GUIDE} §3)")
    print("\nTools used by verification gates:")
    for tool, purpose in TOOLS:
        if tool == "helm-diff":
            plugins = Path.home() / ".local/share/helm/plugins"
            found = any(p.name.startswith("helm-diff") or p.name == "diff" for p in plugins.glob("*")) if plugins.exists() else False
        else:
            found = shutil.which(tool) is not None
        print(f"  {'✔' if found else '✘'} {tool:<13} {purpose}")
    return 0 if ok else 1


def main():
    parser = argparse.ArgumentParser(description="devops-ai-kit installer")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_inst = sub.add_parser("install")
    p_inst.add_argument("--dry-run", action="store_true")
    p_inst.add_argument("--no-settings", action="store_true", help="do not touch settings.json")
    p_inst.add_argument("--lang", choices=LANGS,
                        help=f"output language for docs and reports (default {DEFAULT_LANG}; a re-install keeps the earlier choice)")
    p_inst.add_argument("--env", action="append", metavar="KEY=VALUE",
                        help="add an env var to settings.json (e.g. KUBECONFIG=~/.kube/ai-config); repeatable")
    p_un = sub.add_parser("uninstall")
    p_un.add_argument("--dry-run", action="store_true")
    sub.add_parser("check")
    args = parser.parse_args()
    if args.cmd == "install":
        install(args)
    elif args.cmd == "uninstall":
        uninstall(args)
    else:
        sys.exit(check(args))


if __name__ == "__main__":
    main()
