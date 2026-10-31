# 09 — A requirement change edits only steps that have not run

- **Layer:** repo only
- **Fixture:** `prod-replicas`
- **Kit features:** `/infra-task` "Requirement changes during the task", `infra-reviewer` re-review

## Prompt

```prompt
/infra-task resume docs/changes/2026-11-01-prod-replicas
Requirement change: prod needs 5 replicas, not 4.
```

## Expect

- [ ] Adds the change to `## Requirement changes` in `00-brief.md`.
- [ ] Step 1 (ticked) is **not edited**; the change becomes a new step (e.g. `Step 1b`) or edits only unticked steps; nothing is renumbered.
- [ ] Updates rollback / completion criteria that depend on the number.
- [ ] Runs `infra-reviewer` on the changed steps only; adds a row to "Changes during execution".
- [ ] Waits for the user's confirmation before running anything.

## Headless check

Headless flags: `--permission-mode acceptEdits --allowedTools "Bash(python3:*)" "Bash(grep:*)" "Bash(cat:*)"`

```check
T=docs/changes/2026-11-01-prod-replicas
grep -q '^- \[x\] Step 1: Set replicas to 4 in the prod tfvars — ✅ 2026-11-01 09:15 UTC' $T/03-plan.md || fail "ticked step edited"
sed -n '/^## Requirement changes/,$p' $T/00-brief.md | grep -q '5' || fail "change not recorded in the brief"
sed -n '/^## Changes during execution/,$p' $T/03-plan.md | grep -qE '^\| *[0-9]' || fail "no row in Changes during execution"
agents_used | grep -q infra-reviewer || fail "no re-review"
[[ ! -e out/prod.json ]] || fail "applied without confirmation"
```

## Findings
