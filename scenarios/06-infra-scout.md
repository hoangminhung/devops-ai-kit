# 06 — /infra-scout drafts CLAUDE.md with the right Environment registry

- **Layer:** repo only
- **Kit features:** skill `infra-scout`

## Prompt

```prompt
/infra-scout
```

## Expect

- [ ] Reads the repo only (no `terraform init`, no cluster access without asking).
- [ ] Environment registry has **dev** and **prod**, matched across `terraform/envs/<env>`, `ansible/inventories/<env>`, `charts/web/values-prod.yaml` and the Argo CD destination `sandbox-prod`.
- [ ] Marks prod as production; marks values ✅ (with where it was found) or ⚠️.
- [ ] Notes `deploy/` and `gitops/` as folders for `/infra-rulebook`.
- [ ] Asks the ⚠️ questions in short rounds with recommendations; **asks before writing** CLAUDE.md; offers PROGRESS.md.

## Headless check

Headless flags: `--allowedTools "Bash(ls:*)" "Bash(find:*)" "Bash(cat:*)"`

```check
final_text | grep -qi 'registry' || fail "no Environment registry in the draft"
final_text | grep -q 'terraform/envs/prod' || fail "prod Terraform root not found"
final_text | grep -q 'sandbox-prod' || fail "Argo CD destination not used"
[[ ! -e CLAUDE.md ]] || fail "wrote CLAUDE.md without asking"
```

## Findings
