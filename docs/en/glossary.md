# Glossary

Terms used consistently across the kit's rules, skills, agents and docs. The Vietnamese column is the term used in `docs/vi`.

## Risk and change control

| Term | Meaning | Vietnamese |
|---|---|---|
| **L0 – L3** | Risk levels. L0 read-only · L1 dev/sandbox, reversible · L2 shared environment, stateless · L3 stateful / irreversible / network / IAM. See `00-core` §3. | cấp rủi ro L0 – L3 |
| **Read-only command** | A command that does not change state (get, describe, logs, diff, plan, `--check`, `--dry-run` …). | lệnh read-only |
| **Mutating command** | A command that changes state (apply, delete, patch, scale, terraform apply, `git push` to GitOps …). | lệnh mutating |
| **What / Target / Reversible? / Undo** | The 4 lines written immediately before every mutating command. | Làm gì / Tác động lên / Đảo ngược được? / Hoàn tác |
| **Preview** | A non-mutating dry run of a change: `terraform plan`, `kubectl diff`, `helm diff`, `ansible-playbook --check --diff`. | preview |
| **Target** | Where a command acts: kube context + namespace, terraform workspace/backend, cloud subscription/account/project. | nơi tác động / mục tiêu |
| **Blast radius** | How much breaks if a change goes wrong. | blast radius (phạm vi ảnh hưởng) |
| **Point of no return (PONR)** | The step after which rolling back means losing or reconciling new data. | point of no return (PONR) |
| **Write freeze** | Stopping all writes to the source before cutover. | write freeze (ngừng ghi) |
| **Cutover** | Switching traffic/connections from the old system to the new one. | cutover |
| **Approval gate** | A step in `/infra-task` where the workflow stops until the user approves. | cổng duyệt |
| **Verification gate** | A lint/validate/scan tool that must pass (or be reported missing) before a change is considered ready. | verification gate |

## Standards

| Term | Meaning | Vietnamese |
|---|---|---|
| **MUST** | Always applies. | MUST |
| **SHOULD** | Default for production; deviation allowed if the reason is recorded. | SHOULD |
| **CONTEXT** | Applies only when its stated condition is true. | CONTEXT |
| **Brownfield rule** | Follow the conventions already in the repo/cluster; record deviations under *Recommendations* instead of fixing them outside scope. | quy tắc brownfield |
| **Recommendations** | The report section where out-of-scope deviations and suggestions are recorded. | Đề xuất |
| **Extra cleanup** | Renames, refactors or version upgrades outside the agreed scope. Not allowed. | "dọn dẹp tiện tay" |

## Evidence

| Marker | Meaning | Vietnamese |
|---|---|---|
| ✅ | Checked with a command. | đã kiểm chứng bằng lệnh |
| 📖 | From the docs (with link). | theo tài liệu (kèm link) |
| ⚠️ | Guess, not checked. | suy luận chưa kiểm chứng |
| **"Done" needs proof** | A "done" report includes the commands run and short output. | "Xong" nghĩa là có bằng chứng |

## Documents

| Term | Meaning | Vietnamese |
|---|---|---|
| **Change record** | What was changed, where, how it was verified, how to undo it. Required for L1+. | change record |
| **Concept note** | An explainer for a tool or stack the user is new to. | concept note |
| **Runbook** | Step-by-step operating procedure. | runbook |
| **ADR** | Architecture decision record. | ADR |
| **Postmortem** | Blameless incident review. | postmortem |
| **Task folder** | The per-task folder created by `/infra-task`, which lets work resume across sessions and machines. | thư mục task |
| **Progress file** | `PROGRESS.md`: current state, open items, decisions and done log of a project. Read at session start, updated after each task. | file tiến độ |
| **Standing rules** | Lasting rules the user gave in chat, kept in the project's `CLAUDE.md` so they apply in every session. | quy tắc thường trực |
| **Context brief** | The short summary `grill-me` writes at the end: decisions, facts found, open questions, assumptions. | bản tóm tắt ngữ cảnh |
