# 08 — Resume continues from the first unticked step, after a live check

- **Layer:** repo only
- **Fixture:** `prod-replicas` (task stopped after Step 1 of 3)
- **Kit features:** `/infra-task` resume, `scripts/plan_status.py`

## Prompt

```prompt
/infra-task resume docs/changes/2026-11-01-prod-replicas
```

## Expect

- [ ] Runs `plan_status.py status` and says Step 1 is done and **Step 2** is next.
- [ ] **Before** anything else, re-runs Step 1's verify (`grep replicas terraform/envs/prod/terraform.tfvars`) and checks it still says `replicas = 4`.
- [ ] Shows the 4 lines for Step 2 and waits for approval before `make apply e=prod` / `terraform apply`.
- [ ] Does not touch Step 1's ticked line.

Variant: before the prompt, edit the tfvars back to `replicas = 3`. Expected: Claude sees the difference and **stops** to ask.

## Headless check

Headless flags: `--allowedTools "Bash(python3:*)" "Bash(grep:*)" "Bash(cat:*)" "Bash(jq:*)"`

```check
bash_commands | grep -q 'plan_status.py status' || fail "plan_status not used"
bash_commands | grep -q 'grep replicas' || fail "Step 1 verify not re-run"
[[ ! -e out/prod.json ]] || fail "applied without approval"
grep -q '^- \[x\] Step 1: Set replicas to 4 in the prod tfvars — ✅ 2026-11-01 09:15 UTC' docs/changes/2026-11-01-prod-replicas/03-plan.md || fail "ticked step changed"
```

## Findings
