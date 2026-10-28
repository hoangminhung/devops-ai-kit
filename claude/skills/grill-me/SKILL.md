---
name: grill-me
description: Interview the user in short rounds to fill in missing context before acting — goal, scope, target environment, constraints, risk, rollback and completion criteria. Finds facts itself with read-only checks and asks the user only for decisions, each with a recommended answer. Use when a request is vague or key information is missing, before planning an L2/L3 change, or when the user asks to be questioned about a plan.
when_to_use: Use when the request is unclear, when you would otherwise have to guess, or when the user asks you to question them ("grill me") about a plan or idea. Vietnamese triggers — "hỏi tôi cho đủ thông tin", "phỏng vấn tôi", "còn thiếu thông tin gì không", "hỏi lại cho rõ trước khi làm", "grill me".
argument-hint: "<topic or plan>"
---

# grill-me — Fill in missing context before acting

<!-- devops-ai-kit · Last reviewed: 2026-10-28 · Idea adapted from mattpocock/skills (grill-me / grilling, MIT). -->

Topic: $ARGUMENTS

Guessing is a common cause of wrong infrastructure changes. Use this skill to turn a vague request into clear decisions before you plan or run anything.

## Rules

- **Facts: find them yourself.** If a read-only command, a file or the docs can answer it (current version, namespace, what the repo does today), check it instead of asking. Use read-only commands only (`00-core` §2). Mark what you found with ✅ / 📖.
- **Decisions: ask the user.** Goal, scope, allowed downtime, which option to choose. Never decide for the user.
- **Ask in rounds.** One round = every question that does not depend on another open question. Usually 2–4 questions per round and 2–4 rounds in total. Do not ask a question that depends on an answer you do not have yet.
- **Give a recommendation** for every question, with the reason in one short line.
- If the AskUserQuestion tool is available, use it: at most 4 questions per call, the recommended option first with "(Recommended)" in its label. Otherwise use the text format below.
- Stop when the checklist is covered or the user says "enough". Do not ask for the sake of asking.
- If talking cannot answer a question (e.g. "how will it behave under load?"), say so and suggest a dry run, a small test or a prototype instead.

## Text format for one round

```
Round <n> — <short topic>

❓ 1. <title>
<the question, 1–2 lines>
➡️ Recommended: <answer> — <why>

❓ 2. ...
```

The user can answer by number: "1 yes, 2 option B, 3 not sure".

## What to cover (infrastructure)

Ask only what is still unknown and matters for this task.

| Area | Examples |
|---|---|
| Goal | What problem does this solve? How do we know it worked? |
| Scope | What is in and out of scope? Which repos / components? |
| Target | Which environment, cluster / context, namespace, subscription / account, workspace? |
| Constraints | Maintenance window, allowed downtime, cost limit, deadline, who must approve |
| Current state | Things recon cannot see: manual changes, known issues, who else uses it |
| Risk | Risk level (L0–L3), data at risk, point of no return, a backup that was test-restored |
| Rollback | How to undo, how long it may take, who decides |
| Done | Completion criteria and how to check them |
| Docs | What must be written afterwards (change record, runbook, ...) |

## Finish

1. Write a short **Context brief**: decisions (in the user's words), facts found (✅ / 📖), open questions, assumptions.
2. Ask the user to confirm the brief before you act on it.
3. Save it where the next session will find it (`00-core` §9):
   - inside `/infra-task`: in `00-brief.md`;
   - otherwise: add the decisions to the progress file under **Decisions**, with today's date;
   - lasting rules the user stated ("always ...", "never ...") → propose the exact line for **Standing rules** in the project's CLAUDE.md.
