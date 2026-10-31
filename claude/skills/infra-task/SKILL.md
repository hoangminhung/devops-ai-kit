---
name: infra-task
description: Run a risky infrastructure change end-to-end — recon of the live state, version research, a written plan, independent plan and code review, gated execution, evidence-based verification and handover docs. Use for L2/L3 work such as deploying or upgrading platform components (monitoring, storage, ingress), migrating databases or clusters, provisioning cloud environments, and network/IAM/storage changes on shared environments. Also resumes an unfinished task from its task folder.
when_to_use: Use when deploying or upgrading infrastructure components on a shared environment, migrating a database or cluster, building new cloud infrastructure, changing storage / network / IAM, or resuming an unfinished infrastructure task. Vietnamese triggers — "triển khai hoặc nâng cấp thành phần hạ tầng trên môi trường dùng chung", "migrate database hoặc cluster", "dựng hạ tầng cloud mới", "thay đổi storage / network / IAM", "tiếp tục một task hạ tầng đang dở".
argument-hint: "<task description> | resume <task folder>"
disable-model-invocation: true
---

# /infra-task — Controlled infrastructure change workflow

User request: $ARGUMENTS

This workflow exists so that every risky change:

1. Is based on the **real current state**, not on guesses.
2. Has a **plan that is reviewed independently**.
3. Changes state **only after the user approves**.
4. Ends with **proof**.
5. Leaves **enough docs for someone else to take over**.

You (the main session) are the coordinator: you write the plan, implement and execute yourself. You give recon, research, review, verify and docs to subagents. Subagents cannot call other subagents and only return a summary, so every result is saved as a file in the task folder.

## Phase 0 — Start or resume

**New task:**

1. Find the repo root (`git rev-parse --show-toplevel`). If you are not in a git repo, ask the user where to save the task folder.
2. Create the folder `docs/changes/<YYYY-MM-DD>-<short-slug>/`.
3. Write `00-brief.md`. The first line is `Status: Phase 0 — Brief · Updated: <date time>`. The content has:
   - the original request and the goal;
   - **in scope / out of scope**;
   - **the target environment** (env, context, namespace, subscription / account, workspace);
   - **success criteria** (how we know it worked);
   - **allowed downtime** and other constraints (maintenance window, deadline);
   - **rollback expectation** (how far back, how fast, who decides);
   - **the suggested risk level (L1/L2/L3) and why**;
   - an empty `## Requirement changes` part.
4. **If any bold item above is missing or vague, run the `grill-me` interview** (load the `grill-me` skill and follow its rules: check facts yourself, ask only for decisions, short rounds, a recommendation per question). Put its Context brief into `00-brief.md`.
5. Ask the user to confirm the risk level and scope before you continue. For L1 → use the "Short workflow for L1" at the end of this file.
6. If the project has a progress file (`00-core` §9), add **one line** for the task under **Open items**: the goal and a link to the task folder. Details stay in the task folder; do not copy them into the progress file.

**Resume a task (`resume <folder>`):**

1. Read `00-brief.md` (the `Status:` line and the requirement changes) and the files that exist. Tell the user which phase the task is in.
2. If the task is in Phase 7 or later, find where execution stopped:

   ```bash
   python3 <skill base directory>/scripts/plan_status.py status <task folder>
   ```

   It lists the ticked steps and the **first unticked step**: that is where you continue. Old plans without checkboxes are read from `07-execution-log.md`; offer to convert them to the checkbox format.
3. **Before you run anything**, check that the live state still matches the last ticked step. Someone may have changed the system since then. Run that step's `Verify` command (read-only), and for L2/L3 also `infra-recon` in quick mode on the components of the next steps.
4. If anything differs from what the plan and the log expect: **stop**, show the difference, and ask the user. Do not "fix" it yourself.
5. Then continue from the first unticked step, with the same rules as Phase 7.

After each phase, update the `Status:` line in `00-brief.md`.

## Phase 1 — Recon (subagent `infra-recon`)

- Give `infra-recon`: the task folder path, the target environment, the list of components to check.
- Result: `01-recon.md`.
- Read the "Key findings" and "Risks" parts. If the current state is different from what the user expects (version, GitOps owner, storage…), tell the user right away, before planning.

## Phase 2 — Research (subagent `infra-researcher`)

- Required for L3. For L2: required when there is a version upgrade, a tool that is new to the user, or when you are not sure how something behaves in a given version.
- Give `infra-researcher`: the current version (from recon), the target version, the questions to answer.
- Result: `02-research.md`, with source links.

## Phase 3 — Plan (main session)

1. Load the related standards and playbooks from the table below (use the Skill tool, or read `~/.claude/skills/<name>/SKILL.md`).
2. Read `references/plan-template.md` and write `03-plan.md` **exactly** in that format.
3. Every step must have: who runs it, context, blast radius, whether it can be undone, the exact rollback command, the verify command with the expected value, the stop condition.
4. For L3, also check `references/l3-checklist.md`.
5. On production, prefer steps with "Executed by: GitOps PR" or "user" over the AI running mutating commands directly.

| Task type | Skills to load |
|---|---|
| Monitoring / logging / alerting | `playbook-monitoring-stack`, `k8s-storage` |
| PostgreSQL: migrate, upgrade, move cluster | `playbook-pg-migration`, `db-reliability`, `disaster-recovery`, `k8s-storage` |
| Build AKS / Azure infrastructure | `playbook-aks`, `cloud-platforms`, `finops`, `pki-secrets` |
| AWS / GCP / Hetzner / OVH / on-prem infrastructure | `cloud-platforms`, `finops` |
| Ingress / Gateway / CNI / NetworkPolicy | `k8s-networking`, `pki-secrets` |
| Storage / StorageClass / Longhorn | `k8s-storage`, `disaster-recovery` |
| Certificates / secrets / IAM / access | `pki-secrets` |
| Image build / CI security | `container-supply-chain` |
| Any change that touches data | add `disaster-recovery` |

Write the list of loaded skills in the "Standards & playbooks used" part of the plan. The reviewer will read exactly this list.

## Phase 4 — Plan review (subagent `infra-reviewer`, mode `plan`)

1. Give `infra-reviewer`: the task folder path and `mode: plan`.
2. Save the result as-is in `04-plan-review.md`.
3. If the verdict is `CHANGES REQUIRED` or `BLOCK`: fix the plan and review again, at most 2 rounds. If it is still `BLOCK` after 2 rounds, show the disagreement to the user and let them decide.

### ⛔ GATE 1 — User approves the plan

Show a short summary:

- the goal and the risk level;
- the number of steps, and which steps the AI runs / the user runs / go through a PR;
- the points of no return;
- the expected downtime;
- how to roll back;
- open findings from the reviewer;
- open questions.

**Stop.** Go to Phase 5 only when the user clearly agrees ("approved", "ok, go ahead"). If the answer is unclear, ask again.

## Phase 5 — Implement (main session)

1. Write the code / manifests / values / playbooks following the plan and the rules that are loaded.
2. Run all static verification gates for each technology, plus the previews (`terraform plan`, `helm diff`, `kubectl diff`, `--check --diff`).
3. Write `05-implementation.md` with:
   - the list of changed files, `git diff --stat`;
   - short output of each gate;
   - a summary of the preview (for Terraform: list every `destroy` / `-/+`).
4. Do not run any mutating command in this phase.

## Phase 6 — Code review (subagent `infra-reviewer`, mode `diff`)

- Save the result in `06-code-review.md`. Handle findings the same way as Phase 4.

### ⛔ GATE 2 — User approves the changes

Show: a summary of the diff, the preview result, the reviewer's verdict. **Stop** and wait for clear approval.

## Phase 7 — Execute (main session, one step at a time)

For each unticked step in the plan, in order:

1. Check the context / namespace / subscription again. If the target is wrong, stop.
2. Write the 4 lines (What / Target / Reversible? / Undo) from the core rule.
3. Steps with "Executed by: user" or "GitOps PR": give the exact command or create the commit / PR, then wait for the user to report the result.
4. Run it (or get the result), then run the step's `Verify` command.
5. Write to `07-execution-log.md`: time · `Step N` · command · short result · verify command · pass / fail.
6. **Only if the verify passed**, tick the step in `03-plan.md`:

   ```bash
   python3 <skill base directory>/scripts/plan_status.py tick <task folder> <N> --result "<short result>"
   ```

7. If the result is not what you expected, or a stop condition is hit: **stop right away**, leave the step unticked, tell the user, suggest a rollback or a fix. Do not invent new steps outside the plan. If the plan must change, follow "Requirement changes during the task" below.

## Phase 8 — Verify (subagent `infra-verifier`)

1. Give `infra-verifier`: the task folder. The verifier runs the checklist in the "Completion criteria" part of the plan.
2. Result: `08-verification.md`.
3. Verdict `FAIL` or `PARTIAL`: do not say the task is done. Show it to the user and suggest a fix or a rollback.

## Phase 9 — Docs (subagent `infra-scribe`)

- Give `infra-scribe`: the task folder.
- Result:
  - `09-change-record.md`;
  - a new or updated runbook for the related component;
  - a concept note if a technology is new to the user;
  - an ADR if the plan contains an architecture decision.

## Phase 10 — Close the task

1. Report to the user:
   - what was changed;
   - the main proof;
   - remaining risks;
   - follow-ups;
   - docs created.
2. Update to `Status: Done`. If the project has a progress file, move the task's line to **Done log** (one line with a link to the change record) and update **Current state**.
3. If the AI made the same mistake more than once in this task, or the reviewer caught a mistake that a rule should have blocked: suggest the exact line to add to a rule / skill of the kit.

## Requirement changes during the task

When the user changes the request after GATE 1 (new target, new scope, a different version, a new constraint):

1. **Stop** before the next mutating command.
2. Add the change to `## Requirement changes` in `00-brief.md`: date, the user's words, what it changes.
3. Run `plan_status.py status` and list the steps it affects:
   - **ticked steps are history**: never edit them; if one must be undone, that is a new step;
   - edit only unticked steps; add new steps with a letter (`Step 3b`); **never renumber**;
   - update the parts of the plan that depend on them (rollback, point of no return, completion criteria, risks).
4. Give `infra-reviewer` (mode `plan`) the task folder and the list of changed steps, and ask it to review **only those steps** and what they touch. Append the result to `04-plan-review.md` with a date.
5. Add a row to **Changes during execution** in `03-plan.md`: time · change · reason · steps affected · re-reviewed · confirmed by user.
6. Show the user the changed steps and the reviewer's verdict, and **wait for confirmation** (a small GATE 1) before you continue. If files must change too, GATE 2 applies to the new diff.

## Short workflow for L1

1. Write `00-brief.md` (short) and a short `03-plan.md`: steps, rollback, verify criteria.
2. Implement with the static gates, then execute with the 4 lines before each mutating command.
3. Verify with commands in the main session (use `infra-verifier` if there is a lot of output).
4. Write `09-change-record.md` (subagent `infra-scribe`, or write it yourself with the `infra-docs` template).

The reviewer is optional for L1, but you should use it when the change touches something you have never done before.
