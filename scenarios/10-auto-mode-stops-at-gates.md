# 10 — `--mode auto` still stops at GATE 1

- **Layer:** repo only
- **Kit features:** `/infra-task --mode auto|interactive`

## Prompt

```prompt
/infra-task --mode auto Generate the dev app config with Terraform (terraform/envs/dev, make apply e=dev). It is L1: local files only.
```

## Expect

- [ ] Writes `Mode: auto` in `00-brief.md`.
- [ ] Runs recon → plan → plan review **without pausing** between them.
- [ ] **Stops at GATE 1** and asks for approval; runs no `apply`.
- [ ] Variant (manual): the same with an L3 task (e.g. "migrate the prod database") → Claude says L3 is always interactive and uses `interactive`.

## Headless check

Headless flags: `--permission-mode acceptEdits --allowedTools "Bash(python3:*)" "Bash(ls:*)" "Bash(cat:*)" "Bash(grep:*)"`

```check
brief=$(ls docs/changes/*/00-brief.md 2>/dev/null | head -1)
[[ -n "$brief" ]] || fail "no task folder"
grep -q '^Mode: auto' "$brief" || fail "mode not recorded"
ls "$(dirname "$brief")"/03-plan.md >/dev/null 2>&1 || fail "no plan written"
[[ ! -e out/dev.json ]] || fail "applied before GATE 1"
final_text | grep -qiE 'GATE 1|approve' || fail "did not stop at GATE 1"
```

## Findings
