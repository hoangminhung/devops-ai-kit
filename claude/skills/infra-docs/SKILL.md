---
name: infra-docs
description: Write infrastructure documentation based on real evidence — change records of what was changed and why, concept/learning notes that explain how a tool or stack works, runbooks for operating a component, ADRs for architecture decisions, and blameless postmortems. Use whenever the user wants to document something, write handover or onboarding material, explain how a technology works for learning or for new team members, record a change, or write a runbook, ADR or postmortem.
when_to_use: Use when the user needs docs, handover / onboarding material, an explanation of how a tool or tech stack works, a record of a change that was made, a runbook, ADR or postmortem — even if they just say "write docs" or "explain how this works". Vietnamese triggers — "viết tài liệu", "giải thích cái này hoạt động thế nào", "tài liệu bàn giao / hướng dẫn người mới", "giải thích công cụ hoặc tech stack hoạt động thế nào", "ghi lại thay đổi đã làm", "viết runbook, ADR, postmortem".
---

# Infrastructure documentation

Docs are for three readers:

- **The user today**, to understand what the AI just did and what the risks are.
- **The same user in 6 months**, when they need to operate, debug or upgrade.
- **A new person**, who needs to learn and take over.

Write so that all three can understand without asking again.

## Choose the type of doc

| Type | When | Answers the question | Template | Default location |
|---|---|---|---|---|
| Change record | Every task at L1 or higher | What changed, why, impact, risk, how to undo, proof | `templates/change-record.md` | `docs/changes/<task>/09-change-record.md` |
| Concept note | A tool / stack that is new to the user or new in the project | How it works, why it is designed this way, what happens when it breaks | `templates/concept-note.md` | the personal KB folder if CLAUDE.md defines one, otherwise `docs/concepts/` |
| Runbook | Every component that is deployed / operated | How to operate, debug, backup/restore, upgrade | `templates/runbook.md` | `docs/runbooks/<component>.md` |
| ADR | A choice between options with long-term effects | Why we chose this | `templates/adr.md` | `docs/adr/NNNN-<slug>.md` |
| Postmortem | After an incident | What happened, why, what we do so it does not happen again | `templates/postmortem.md` | `docs/postmortems/<YYYY-MM-DD>-<slug>.md` |

Read the matching template before you write, and keep its structure.

## General rules

1. **Mark where information comes from.** Every important technical claim has one of three marks:
   - ✅ checked with a command (with the command or short output, or a link to the task's log file);
   - 📖 from the official docs (with the link and the docs version);
   - ⚠️ guess / not checked.

   This stops an AI guess from becoming wrong "knowledge" for the whole team after a few handovers.
2. **Write the version and the date.** Infrastructure docs go out of date fast. Each doc has `Applies to: <tool> <version>` and `Updated: <date>`.
3. **No secrets.** No passwords, tokens, private keys, or connection strings with credentials. Point to where the secret is stored (Key Vault / secret name), not the value.
4. **Commands must work.** Commands in a runbook can be copied and pasted, use clear placeholders like `<namespace>`, and say which context to run them in. Each mutating command has a warning right before it.
5. **Use Mermaid for diagrams** so they render directly on GitHub/GitLab. Use a diagram when 3 or more components work together.
6. **Write for someone who was not there.** Explain each abbreviation the first time it appears. Do not write "as said above" without pointing to the section.
7. **Language.** Follow the output language rule (`01-language.md`, set at install time with `--lang`). The project's CLAUDE.md can override it. Keep template headings as they are.

## Concept notes (learning docs)

The goal is that the reader **builds a correct mental model**, not a copy of the official docs.

- Start with a comparison to something the reader already knows.
- Explain the data flow / control loop with a diagram.
- Point out what new people often get wrong, dangerous defaults, and how the system breaks.
- End with a few self-check questions for new people.
- Prefer examples from the user's own system (from recon / task logs) over generic examples. Mark them ✅ when checked on the real system.

## ADRs

- Once an ADR is `Accepted`, **do not edit the decision**. When the decision changes, write a new ADR with `Supersedes: ADR-NNNN` and change the old ADR's status to `Superseded by ADR-MMMM`.
- Do not put operating details in an ADR; link to the runbook.
- Number them in order: look at the highest file in `docs/adr/` to get the next number.

## Postmortems

- Blameless: describe the system and the decisions, do not blame a person.
- Include a "Lessons for the AI rules" section: which rule / skill in devops-ai-kit should be added or changed so the AI does not repeat the problem (if the AI was involved).
