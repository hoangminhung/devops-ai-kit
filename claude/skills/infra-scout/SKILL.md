---
name: infra-scout
description: Onboard an infrastructure repo — read its Terraform (folders, backends, workspaces, provider versions), Helm charts and values, Argo CD Applications, Ansible inventories and playbooks, manifests and CI, then create or update a short project CLAUDE.md with the Environment registry, stack and versions, repo layout, conventions, common commands and docs settings. Marks each value as found (✅) or inferred (⚠️) and asks the user to confirm the inferred ones. Use once per repo before other work, and again when the repo changes a lot.
when_to_use: Use when starting work in an infrastructure repo that has no CLAUDE.md, or when its CLAUDE.md is out of date. Vietnamese triggers — "onboard repo này", "tạo CLAUDE.md cho repo", "khảo sát repo hạ tầng".
argument-hint: "[repo folder] [--recon <context> ...]"
disable-model-invocation: true
---

# /infra-scout — Onboard an infrastructure repo

<!-- devops-ai-kit · Last reviewed: 2026-10-31 -->

Request: $ARGUMENTS

The project's CLAUDE.md is what every later session reads first (`00-core` §9). A short, correct one prevents most "wrong cluster" and "wrong convention" mistakes. This skill writes it from evidence, not from guesses.

## Rules

- **Read-only.** Read files only. Do not run `terraform init`, `helm dependency update` or anything that changes state. Cluster access happens only in step 3, only if the user agrees, and only through `infra-recon`.
- **No secrets.** Never open `*.tfstate*`, `.env*`, private keys or kubeconfig contents. In tfvars and values files, read names and structure, not secret values. Write only the names of secrets and where they are stored.
- **Mark every value**: ✅ found (in the repo or cluster; say where in a few words) or ⚠️ inferred. Unknown → `<to fill in: ...>`.
- **Keep CLAUDE.md under ~100 lines.** Do not repeat what the kit's rules already say (safety rules, Terraform / Helm standards). Write only what is specific to this repo.
- Ask before you write any file.

## Steps

1. **Start.**
   - Repo root: the argument, or `git rev-parse --show-toplevel`.
   - Read what exists: `CLAUDE.md` (or `.claude/CLAUDE.md`), `README*`, `PROGRESS.md`, `Makefile`, `docs/` index. If a CLAUDE.md exists, you are in **update mode** (step 6).
2. **Explore the repo.** Follow `references/detectors.md`: which files to look for per technology, and what to take from them. For big repos, list the folders first, then read a few files per folder; do not read everything.
3. **Optional live recon (ask first).**
   - If the user passed `--recon <context>`, or the registry has ⚠️ values that only the cluster can confirm, offer to run the subagent `infra-recon` on the contexts the user names.
   - Give it only those contexts. It must stay read-only and must not switch the current context.
   - Values confirmed by recon become ✅ (cluster).
4. **Draft CLAUDE.md** from `templates/project-CLAUDE.md`. Fill in:
   - Purpose; **Environment registry** (env ↔ kube context / kubeconfig file ↔ namespace ↔ cloud scope ↔ Terraform dir / workspace ↔ who makes changes);
   - Stack & versions; Repo layout; Project conventions (what the repo does differently from common practice); Common commands (from Makefile / scripts / CI); Documentation settings.
   - Keep the template's "Start of every session" and "Standing rules" sections.
5. **Confirm the ⚠️ values** with the user. Use the `grill-me` way of asking: short rounds, each question with your recommended answer. Change confirmed values to ✅ (user). Leave values the user does not know as `<to fill in: ...>`.
6. **Update mode** (CLAUDE.md already exists):
   - Keep everything the user wrote. Only add missing sections and update values you found evidence for.
   - Show a unified diff of the change. Never delete or rewrite a line without asking.
7. **Show the full draft in the chat** (or the diff in update mode), then **write** CLAUDE.md after the user agrees. If there is no progress file, offer to create `PROGRESS.md` from `templates/PROGRESS.md`.
8. **Next step.** Suggest `/infra-rulebook` to make the kit's rules load for every infrastructure file in this repo.
