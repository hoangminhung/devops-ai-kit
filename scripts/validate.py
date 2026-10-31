#!/usr/bin/env python3
"""Static checks for the kit content that Claude reads.

Checks: frontmatter parses, `name` matches the folder/file name, technology
rules have `paths`, description + when_to_use length, referenced
references/ and templates/ files exist, settings JSON is valid, and no
Vietnamese text is left in English-only files.

Usage: python3 scripts/validate.py      (exit code 1 on any error)
"""
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # CI installs PyYAML; locally it is optional
    yaml = None

KIT_DIR = Path(__file__).resolve().parent.parent
CLAUDE = KIT_DIR / "claude"
MAX_SKILL_TEXT = 1536
ALWAYS_LOADED_RULES = {"00-core.md", "01-language.md"}
# Vietnamese letters that do not appear in normal English text.
VIETNAMESE = re.compile(
    "[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
    "ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ]"
)
# Files Claude reads or that ship as English-only. docs/ is checked by hand.
ENGLISH_ONLY_GLOBS = ["claude/**/*", "templates/*", "setup/**/*", "scripts/*", "*.sh", "README.md", "CHANGELOG.md"]
VIETNAMESE_ALLOWED = {Path("claude/lang/vi.md"), Path("scripts/validate.py")}
REF_PATTERN = re.compile(r"\b((?:references|templates|scripts)/[A-Za-z0-9_.-]+\.(?:md|py))\b")
# Templates that ship both in templates/ (for people) and inside a skill (for Claude): must stay identical.
TEMPLATE_COPIES = [
    ("templates/project-CLAUDE.md", "claude/skills/infra-scout/templates/project-CLAUDE.md"),
    ("templates/PROGRESS.md", "claude/skills/infra-scout/templates/PROGRESS.md"),
]
SKILL_MENTION = re.compile(r"`([a-z0-9-]+)`")

errors = []


def error(path, msg):
    errors.append(f"{path.relative_to(KIT_DIR)}: {msg}")


def split_frontmatter(path):
    """Return (frontmatter dict or None, raw frontmatter text, body)."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None, "", text
    end = text.find("\n---\n", 4)
    if end == -1:
        error(path, "frontmatter is not closed with '---'")
        return None, "", text
    raw, body = text[4:end], text[end + 5:]
    if yaml is None:
        data = {}
        for line in raw.splitlines():
            match = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
            if match:
                data[match.group(1)] = match.group(2)
        return data, raw, body
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        error(path, f"frontmatter is not valid YAML: {exc}")
        return None, raw, body
    if not isinstance(data, dict):
        error(path, "frontmatter is not a mapping")
        return None, raw, body
    return data, raw, body


def check_rules():
    for path in sorted((CLAUDE / "rules" / "devops-kit").glob("*.md")):
        data, _, _ = split_frontmatter(path)
        if path.name in ALWAYS_LOADED_RULES:
            if data and data.get("paths"):
                error(path, "always-loaded rule must not have `paths`")
        elif not data or not data.get("paths"):
            error(path, "technology rule needs `paths` in frontmatter")
    for path in sorted((CLAUDE / "lang").glob("*.md")):
        data, _, _ = split_frontmatter(path)
        if data and data.get("paths"):
            error(path, "language rule must not have `paths`")


def check_skills():
    skill_dirs = {p.name: p for p in (CLAUDE / "skills").iterdir() if p.is_dir()}
    for name, skill_dir in sorted(skill_dirs.items()):
        path = skill_dir / "SKILL.md"
        if not path.exists():
            error(skill_dir, "missing SKILL.md")
            continue
        data, _, body = split_frontmatter(path)
        if not data:
            error(path, "missing frontmatter")
            continue
        if data.get("name") != name:
            error(path, f"name '{data.get('name')}' does not match folder '{name}'")
        if not data.get("description"):
            error(path, "missing description")
        length = len(str(data.get("description", ""))) + len(str(data.get("when_to_use", "")))
        if length > MAX_SKILL_TEXT:
            error(path, f"description + when_to_use is {length} chars (max {MAX_SKILL_TEXT})")
        check_references(path, body, skill_dir, skill_dirs)


def check_references(path, body, skill_dir, skill_dirs):
    for line in body.splitlines():
        for ref in REF_PATTERN.findall(line):
            candidates = [skill_dir / ref]
            candidates += [skill_dirs[s] / ref for s in SKILL_MENTION.findall(line) if s in skill_dirs]
            if not any(c.exists() for c in candidates):
                error(path, f"referenced file not found: {ref}")


def template_copy_errors(kit_dir, pairs=TEMPLATE_COPIES):
    """Messages for template copies that are missing or differ from the original."""
    found = []
    for original, copy in pairs:
        a, b = kit_dir / original, kit_dir / copy
        if not a.exists() or not b.exists():
            found.append(f"{copy}: template copy or original missing ({original})")
        elif a.read_bytes() != b.read_bytes():
            found.append(f"{copy}: differs from {original} (copy the original over it)")
    return found


def check_template_copies():
    errors.extend(template_copy_errors(KIT_DIR))


def check_agents():
    for path in sorted((CLAUDE / "agents").glob("*.md")):
        data, _, _ = split_frontmatter(path)
        if not data:
            error(path, "missing frontmatter")
            continue
        if data.get("name") != path.stem:
            error(path, f"name '{data.get('name')}' does not match file name '{path.stem}'")
        if not data.get("description"):
            error(path, "missing description")


def check_settings():
    path = CLAUDE / "settings.devops-kit.json"
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        error(path, f"not valid JSON: {exc}")


def check_english_only():
    files = set()
    for pattern in ENGLISH_ONLY_GLOBS:
        files.update(p for p in KIT_DIR.glob(pattern) if p.is_file())
    for path in sorted(files):
        rel = path.relative_to(KIT_DIR)
        if rel in VIETNAMESE_ALLOWED or "__pycache__" in rel.parts:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(lines, 1):
            if line.startswith("when_to_use:"):
                continue
            if VIETNAMESE.search(line):
                error(path, f"line {number}: Vietnamese text in an English-only file")
                break


def main():
    if yaml is None:
        print("note: PyYAML not installed, using a simple frontmatter parser", file=sys.stderr)
    check_rules()
    check_skills()
    check_agents()
    check_template_copies()
    check_settings()
    check_english_only()
    for message in errors:
        print(f"ERROR {message}")
    print(f"validate: {len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
