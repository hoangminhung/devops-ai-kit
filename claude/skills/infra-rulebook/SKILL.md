---
name: infra-rulebook
description: Map an infrastructure repo's files to the devops-ai-kit technology rules (Terraform, Ansible, Kubernetes, Helm, Argo CD, Dockerfile, observability), report which files the kit's default paths already cover, and create small project-level rule files that add the missing paths and point to the kit rule. Never copies the standards. Use after /infra-scout when onboarding a repo, or when infrastructure files live in folders the kit does not match (e.g. manifests in deploy/).
when_to_use: Use when the kit's rules do not load for some infrastructure files, when manifests, charts or Argo CD apps are in non-standard folders, or right after /infra-scout. Vietnamese triggers — "rule của kit không nạp cho thư mục này", "manifest nằm trong deploy/", "phủ rule cho repo".
argument-hint: "[repo folder]"
disable-model-invocation: true
---

# /infra-rulebook — Make the kit's rules load for every infrastructure file

<!-- devops-ai-kit · Last reviewed: 2026-10-31 -->

Request: $ARGUMENTS

The kit's technology rules load only for files that match their `paths` (e.g. `**/k8s/**`). Many repos keep files in other folders (`deploy/`, `chart/`, `apps/*/app.yaml`), so Claude edits them without the standards. This skill finds those files and adds the missing paths at project level.

## Rules

- **The kit is the only source of the standards.** A project rule file contains `paths` and a pointer to the kit rule, nothing else. Never copy standards into the repo.
- **No `@import` to the kit.** Claude Code does not load imports of files outside the project (checked with Claude Code 2.1.x), so the file uses a "read this rule file" line instead.
- Write only under `<repo>/.claude/rules/`. Never edit the kit's own rule files.
- Ask before you write or change any file.

## Steps

1. **Find the repo and the kit.**
   - Repo root: the argument, or `git rev-parse --show-toplevel`.
   - Kit rules: `${CLAUDE_CONFIG_DIR:-~/.claude}/rules/devops-kit/`. If it is missing, stop and tell the user to install the kit.
2. **Measure coverage.** Run the script that comes with this skill (it is in this skill's base directory):

   ```bash
   python3 <skill base directory>/scripts/coverage.py report --repo <repo root>
   ```

   - It finds infrastructure files **by content** (e.g. YAML with `apiVersion` + `kind`, Argo CD `Application`, Ansible playbooks), not only by name.
   - Use `--json` if you need the full list. Existing `.claude/rules/devops-kit-paths-<tech>.md` files count as coverage.
3. **Report to the user**: a table per technology (files / covered / uncovered), the uncovered files (up to 10 each) and the suggested paths.
4. **Agree on the paths.** For each technology with uncovered files:
   - show the suggested globs and say what they match;
   - check that a glob does not also match files of another technology (e.g. `apps/**/*.yaml` would also match the Kubernetes manifests next to `app.yaml`); prefer narrow globs;
   - ask the user to accept, change or skip each one (rounds like `grill-me`, recommendation first).
5. **Show the files, then write them.** Generate each file with:

   ```bash
   python3 <skill base directory>/scripts/coverage.py emit <tech> --repo <repo root> --path "<glob>" [--path "<glob>" ...]
   ```

   - If `.claude/rules/devops-kit-paths-<tech>.md` exists, show a diff against it; `emit` without `--path` keeps the existing paths and adds the suggestions.
   - Write the files only after the user agrees.
6. **Check.** Run `report` again. Every file should be covered, or the user chose to skip it; say which.
7. **Tell the user**:
   - commit `.claude/rules/devops-kit-paths-*.md` so the whole team gets it;
   - for people without the kit the files are harmless: they only point to a file they do not have;
   - run `/infra-rulebook` again when new folders appear.
