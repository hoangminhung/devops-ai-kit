# RFC 0001 — `/handoff` and `/pickup`: disposable sessions, durable state

- **Status:** Trial — a minimal version is implemented (see §9 and §10); the rest waits for the trial results
- **Author:** devops-ai-kit maintainer (drafted with Claude)
- **Affects:** new skill `handoff`; `templates/PROGRESS.md` (+ the copy in `infra-scout`); `00-core` §9; guide §5.6 (en + vi); scenario 13
- **Updated:** 2026-11-04

> Sections 1–8 are the original draft. Section 9 records what the review changed, section 10 how the trial is judged. Where they differ, sections 9 and 10 win.

## 1. Problem

A common way of working is to keep **one Claude Code session alive for days or weeks** and run `/compact` whenever context reaches ~50–60%. This has five failure modes:

1. **Summary of a summary.** Each compaction summarises the previous summary plus new work. After dozens of compactions, details are lost and the model cannot tell what was dropped. It acts confidently on a drifted summary.
2. **Kitchen-sink sessions.** Unrelated tasks pile up in one context. The official Claude Code best practices list this as a failure pattern and recommend `/clear` between unrelated tasks.
3. **Context rot.** Model quality degrades as input grows, long before the window is full (Chroma, *Context Rot*, 2025: all 18 tested models degraded). With a 1M-token window, "60 %" is ~600k tokens — far past the useful zone. Percent-based thresholds mislead on large windows.
4. **Early mistakes get locked in.** A wrong assumption from day 3 survives every compaction.
5. **State lives in the weakest place.** Knowledge exists only inside one session (or in the clipboard, in the "copy summary → /clear → paste" habit). It is lost if the session breaks, and it does not travel between machines or surfaces (VS Code Remote-SSH ↔ Claude Desktop SSH).

## 2. Goal

Make the right habit a single command:

> **Write durable state to a file → let the user check it → `/clear` → start the next session from the file.**

Success means:

- a fresh session can continue correctly from the file alone;
- the file stays small;
- nothing load-bearing exists only in a session.

## 3. Non-goals

- Replacing `/compact`. It stays useful **inside** one task when context gets heavy.
- Replacing `/infra-task` task folders. They remain the source of truth for a single infrastructure change.
- Automating `/clear`. Claude cannot run built-in slash commands; the user does.

## 4. Proposal

### 4.1 Two skills

| Skill | When | What it does |
|---|---|---|
| `/handoff [note]` | End of a task or phase, before switching machines, when the user leaves for the day, or when symptoms of context rot appear | Gathers state from the session, proposes an update to `PROGRESS.md` (diff), writes it after confirmation, checks for uncommitted changes, prints a one-line pickup prompt, and tells the user to `/clear` |
| `/pickup` | First thing in a new session | Reads `PROGRESS.md` and the active task folder, checks freshness against git (and optionally live state, read-only), summarises "where we are", and **asks the user to confirm before doing anything** |

Both are `disable-model-invocation: true`: they write files or set direction, so they run only when the user asks.

**Naming.** The working name was `/checkpoint`. It was dropped because Claude Code already has a built-in *checkpointing* feature (`/rewind`), and the overlap would confuse users. `handoff` matches the kit's vocabulary: the next session is treated like a colleague taking over. Reviewers should confirm that neither `/handoff` nor `/pickup` collides with a built-in command or a common plugin.

### 4.2 Where state lives — one source of truth per level

| Level | File | Contains |
|---|---|---|
| Stable project facts | `CLAUDE.md` | Environment registry, conventions — rarely changes |
| Project progress (many tasks) | `PROGRESS.md` | Goal, current state, decisions, dead ends, open questions, next steps — **short** |
| One infrastructure change | `docs/changes/<task>/` | Brief, plan with step checkboxes, logs, verification |
| Reusable lessons | rules / skills / CLAUDE.md | Promoted from `PROGRESS.md` when they apply beyond this project |

When an `/infra-task` is active:

- `/handoff` updates the **task folder** (status line, plan checkboxes, "Changes during execution");
- `PROGRESS.md` gets only a pointer to that folder;
- `/pickup` hands over to `/infra-task resume <folder>`.

No detail is written twice.

### 4.3 `PROGRESS.md` format

See `claude/skills/handoff/references/progress-format.md`. Key rules:

- **Replace, don't append** for "Current state" and "Next steps". Those sections describe *now*, not history.
- **Append, newest first** for "Decisions" and "Dead ends", with a cap. Older entries roll up into "History", or into `docs/progress-archive/<YYYY-MM>.md`.
- **"Dead ends — do not retry"** is mandatory. After `/clear`, the most expensive loss is re-trying an approach that already failed.
- **Evidence markers** follow the kit convention: ✅ checked by command, ⚠️ unverified.
- **Size budget:** target ≤ 150 lines. `PROGRESS.md` must not become the new context bloat.
- **Header** carries the last handoff time, git branch and commit, and the surface/machine it was written from.

### 4.4 Lesson promotion

At each handoff, Claude lists items that look reusable beyond this project. For example: "Longhorn volume expansion needs the pod restarted in version X", or "this repo keeps manifests under `deploy/`". For each, it proposes a target (rule, skill reference, project `CLAUDE.md`). It **does not edit** those files without approval.

This turns daily work into improvements of the kit itself.

### 4.5 Cadence (documented in the guide)

**Run `/handoff` when:**

- a task or phase ends;
- before switching machines (office ↔ home);
- at the end of the day;
- when symptoms appear: Claude forgets agreed decisions, repeats a fixed mistake, or contradicts a constraint.

**Inside a task:** use `/compact` with focus instructions instead.

**Never:** carry unrelated tasks in one session.

## 5. Phase 2 (optional, needs review): hooks

1. **`PreCompact` hook: archive the raw transcript.**
   - Before any compaction, copy the transcript file (path from the hook input) to a local, git-ignored archive.
   - Effect: nothing compacted away is truly lost; it stays searchable with grep.
   - Concerns: disk size, retention, and secrets inside transcripts. The archive must stay out of git and have rotation.
   - Verify the event name and input fields against current Claude Code docs before building.
2. **Gentle reminder.** A `UserPromptSubmit` hook that adds a one-line note when `PROGRESS.md` has not been updated for N hours of active work.
   - Concern: reminder fatigue — the same problem the kit criticises in approval prompts.
   - Default off; consider only after phase 1 has been used for a few weeks.

## 6. Risks and counter-arguments

| Risk | Mitigation |
|---|---|
| `PROGRESS.md` becomes a confident but wrong source of truth | User reviews the diff before write; `/pickup` cross-checks git log/status and flags staleness by timestamp; evidence markers |
| Ceremony fatigue: handoff feels slow, user skips it | One confirmation, target < 1 minute; `--quick` mode updates only "Current state" and "Next steps" |
| Model-written summary has the same weakness as `/compact` | Structured sections, focused on what the *next* session needs; human-reviewed; persistent and diffable in git |
| Secrets or customer data written into `PROGRESS.md` and committed | Kit secret rule applies; handoff never copies command output verbatim, only conclusions; option to keep a git-ignored `PROGRESS.local.md` for client repos |
| Two sessions (VS Code + Desktop) write `PROGRESS.md` at once | Re-read the file right before writing; show a diff against the current content; git as backstop |
| The file grows without bound | Size budget, roll-up into History / archive, `validate.py` warning above the budget |

## 7. How to evaluate (add to `scenarios/`)

1. **Continuity.** Work on a task in the sandbox, run `/handoff`, `/clear`, `/pickup`. Claude must correctly state the next action, the agreed decisions and the dead ends. Compare with a session that only used `/compact`.
2. **No retry of dead ends.** A failed approach recorded in `PROGRESS.md` is not proposed again after pickup.
3. **Size.** After 20 handoffs, `PROGRESS.md` stays within budget and History is rolled up.
4. **Secrets.** After a task that printed a secret-like value, `PROGRESS.md` contains no such value (gitleaks clean).
5. **Cross-surface.** Handoff in VS Code Remote-SSH, pickup in Claude Desktop (SSH) on the same server.
6. **`/infra-task` interplay.** With an active task folder, handoff updates the folder and adds only a pointer to `PROGRESS.md`; pickup routes to `/infra-task resume`.

## 8. Open questions for reviewers

1. Should `PROGRESS.md` live at the repo root, in `.claude/`, or be configurable? Should it be committed by default?
2. Is the 150-line budget right? Should it be enforced by `validate.py` or only warned?
3. Should `00-core.md` get one always-on line ("use `/handoff` at task boundaries; do not mix unrelated tasks in one session"), or is that too costly for always-loaded context?
4. Should `/pickup` run an optional read-only recon of live targets, or stay git-only by default?
5. Is phase 2 (transcript archive) worth the privacy and maintenance cost?

## 9. Review outcome (2026-11-04): what the trial implements

An independent review returned **CHANGES REQUIRED**. Checked facts (Claude Code 2.1.316 CLI, 2.1.314 VS Code extension):

- `/handoff` and `/pickup` are not built-in commands; `/checkpoint` is an alias of `/rewind`, so dropping that name was right.
- `/clear` cannot be run by Claude.
- `PreCompact` exists and receives `transcript_path`, but compaction does **not** shorten the transcript: a week-long session kept all its messages across 3 compactions. Transcripts are deleted after `cleanupPeriodDays` (default 30). So the phase-2 transcript archive would only add a second copy that can hold secrets.

The trial implements the smallest version that can be measured:

| Kept | Changed or deferred |
|---|---|
| One progress file format: `templates/PROGRESS.md` gains **Next steps** and **Dead ends — do not retry** (each with `revisit if:`); live facts carry `checked: <date>`. Open items and Done log stay, because `/infra-task` writes to them. | No second format (`progress-format.md` dropped); no History part. |
| `/handoff`, quick version: rebuilds Current state and Next steps, adds new dead ends, asks once. | No `--full`, no lesson promotion, no commit proposal beyond one line. |
| Task folders are **read only**, through `plan_status.py status`. | The draft let `/handoff` edit the `Status:` line and tick plan steps; that would skip `/infra-task`'s rule "tick only after verify passed". |
| Hash check (`sha256sum`) right before writing, so two sessions (VS Code and the Desktop app on the same server) do not overwrite each other. | "Re-read before writing" alone left a gap of minutes while the user reads the diff. |
| Guide: short task → `/clear` only; long task, a dead end, or a machine / interface switch → `/handoff` first. | `/pickup` deferred: `00-core` §9 already reads the progress file at session start. |
| Scenario 13 measures `/compact` vs `/handoff` (tokens, dead-end retries, right next step). | No hooks. If the trial shows that people forget to read the file, consider a `SessionStart` hook that prints **one line** pointing to it, never its content. |

Answers to section 8: (1) the path the project's CLAUDE.md names, else the repo root, as `00-core` §9 says; whether to commit it is the project's choice (not in this trial: one shared file for all git worktrees). (2) one budget, the existing ~200 lines, warned by `/handoff`'s own count, not by `validate.py` (which checks the kit repo, not projects). (3) no new always-on line: the existing §9 bullet now names `/handoff`. (4) not decided: `/pickup` is deferred. (5) no.

## 10. Trial

Two weeks of real use, from the day this version is installed. Keep a tally in your own notes (not in the repo):

| Count | What counts |
|---|---|
| **Dead end stopped a retry** | A new session read a "Dead ends" line and did not try that approach again, or said so when it was about to. |
| **Wrong file at pickup** | The next session acted on, or nearly acted on, a line of the progress file that was no longer true (old `checked:` date, a step already done, a wrong next step). |
| **Handoff skipped because it was a chore** | You ran `/clear` (or kept compacting) after long work and did not run `/handoff`, because it felt too slow or too many questions. |

Also note the number of `/handoff` runs, to read the counts against.

Decide after the trial, together with the result of scenario 13:

- **Keep and extend** (consider `/pickup`, then the one-line `SessionStart` hook) if dead ends stopped retries more than once, and skipped handoffs are fewer than about one in three.
- **Change** the format if wrong-file cases happened: find which part was stale and why.
- **Drop** `/handoff` (keep the template changes) if it saved nothing and was skipped most of the time: then the habit "one task per session, `/clear` between tasks" is the whole answer.

