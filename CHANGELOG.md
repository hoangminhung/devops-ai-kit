# Changelog

## Unreleased

- `/infra-task --mode auto|interactive`: `auto` runs the paper phases (recon → plan review, implement → code review, verify → docs) without pausing; `interactive` (default) stops after each phase. In both modes GATE 1, GATE 2 and every mutating command wait for the user. L3 is always interactive. The mode is saved in `00-brief.md`.
- `/infra-task` slices: big tasks (L3 with independent parts, or > ~10 steps) can be cut into slices, each with its own plan → gate → execute → verify in `slices/<NN>-<name>/`; a failed slice stops the later ones. New `references/slicing.md`; `plan_status.py` reads slices and `tick --slice` refuses while a slice step is open.
- Tests guard the safety statements in the skill text (`tests/test_skill_contracts.py`).
- `/infra-task`: the workflow stages are now called **Phase 0–10** (they were "Step 0–10", easy to mix up with the plan's steps).
- `/infra-task`: plan steps are checkboxes (`- [ ] Step N: …`); a step is ticked only after its verify passes. `resume` continues from the first unticked step and first checks that the live state still matches the last ticked step. New `scripts/plan_status.py` (`status`, `tick`); old plans without checkboxes are read from `07-execution-log.md`.
- `/infra-task`: "Requirement changes during the task" — ticked steps are never edited, new steps get a letter (`Step 3b`), `infra-reviewer` re-reviews only the changed steps, and the user confirms before execution continues.
- `/infra-task` Phase 0: the brief must state target, success criteria, allowed downtime, scope and rollback expectation; if not, run `grill-me`.
- `PROGRESS.md` vs task folder: the progress file holds one line per task with a link; the details stay in the task folder.
- New skill `/infra-scout`: reads an infrastructure repo (Terraform, Helm, Argo CD, Ansible, manifests, CI) and creates or updates a short project `CLAUDE.md` with the Environment registry; each value is marked ✅ found or ⚠️ inferred, and inferred values are confirmed with the user.
- New skill `/infra-rulebook`: finds infrastructure files by content, reports which ones the kit's rule `paths` cover, and writes `.claude/rules/devops-kit-paths-<tech>.md` files with the missing paths and a pointer to the kit rule (no copied standards, no `@import`). Comes with `scripts/coverage.py`.
- `validate.py`: checks `scripts/` references and that template copies stay identical.
- CI: run once per pull request to `main` (plus manual runs); no more duplicate runs on branch pushes, after merge, or on tags. Older runs of the same PR are cancelled.

## 1.1.0 — 2026-10-28

- README: disclaimer banner at the top.
- New skill `grill-me`: asks the user short rounds of questions (each with a recommended answer) to fill in missing context before acting. Facts are checked with read-only commands; only decisions are asked. Idea adapted from mattpocock/skills (MIT).
- `00-core` §9 "Memory across sessions": where to keep project facts, standing rules, current state and decisions; read the progress file at session start and update it after each task.
- `/infra-task` adds the task to the progress file and moves it to the Done log when it closes; it runs `grill-me` when the brief is unclear.
- Templates: new `templates/PROGRESS.md`; `project-CLAUDE.md` gets "Start of every session" and "Standing rules".

## 1.0.1 — 2026-10-28

- Hook: show the kubeconfig file name (`kubeconfig=kubeconfig.hetzner-live`) when it is not the default one, and use it to detect production targets. Many clusters name their only context `default`, so before this a live cluster was not marked as production.
- Hook: `export KUBECONFIG=...` earlier in the same command (`export ...; kubectl ...`) is now used for the later kubectl / helm / velero calls; relative kubeconfig paths resolve against the session's working folder.
- CI: `actions/checkout` and `actions/setup-python` v7 (Node 24).

## 1.0.0 — 2026-10-28

First public release. Earlier versions were used internally and are not published.

### Kit content

- Rules: `00-core` (always loaded: target check, read-only vs mutating, 4 lines before each mutating command, risk levels L0–L3, brownfield rule, secrets, version-aware knowledge, "done" needs proof) and path-scoped rules for Terraform/OpenTofu, Ansible, Kubernetes, Helm, Argo CD, Dockerfile and observability. Standards use MUST / SHOULD / CONTEXT levels.
- Skills (13): `/infra-task` workflow with two human approval gates and resumable task folders; `infra-docs` with templates for change records, concept notes, runbooks, ADRs and postmortems; 8 design-standard skills; playbooks for a monitoring stack (Prometheus/Grafana/Loki/Alloy on Longhorn), PostgreSQL migration with Crunchy PGO, and AKS with Terraform.
- Subagents (5): `infra-recon`, `infra-researcher`, `infra-reviewer`, `infra-verifier`, `infra-scribe`.
- All content Claude reads is in plain English. Skills keep Vietnamese trigger phrases in `when_to_use`.

### Output language

- `./install.sh --lang en|vi` (default `en`) installs `rules/devops-kit/01-language.md`. With `vi`, handover docs and agent reports are written in Vietnamese; headings, placeholders and file names stay in English. A re-install without `--lang` keeps the earlier choice. `./check.sh` shows the language.

### Guardrails

- Permission rules (deny / ask / allow) merged into `settings.json`.
- `infra-context-guard` PreToolUse hook for the `Bash` and `PowerShell` tools: shows the real target (kube context + namespace, terraform workspace/backend, Azure subscription, AWS profile, GCP project, Ansible inventory, git remote) before every mutating command. Optional `DEVOPS_KIT_BLOCK_PROD=1` blocks production targets. Works on Linux and Windows.
- Read-only RBAC and an AI kubeconfig generator (`setup/k8s/`); guide for read-only cloud identities.

### Installer

- `install` / `uninstall` / `check` with `--dry-run`, backups of replaced files, and a manifest so updates and uninstall remove only what the kit added.
- Uninstall gives back the original `settings.json` byte for byte when it was not changed after install.

### Quality

- `scripts/validate.py`: frontmatter, names, `paths`, description length, referenced files, settings JSON, leftover Vietnamese text.
- Unit tests for the hook and the installer; ShellCheck; GitHub Actions CI.
- Docs in English (`docs/en`) and Vietnamese (`docs/vi`), plus a glossary.
