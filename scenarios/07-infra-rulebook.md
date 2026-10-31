# 07 — /infra-rulebook covers deploy/ and gitops/

- **Layer:** repo only
- **Kit features:** skill `infra-rulebook`, `scripts/coverage.py`

## Prompt

```prompt
/infra-rulebook
```

## Expect

- [ ] Runs `coverage.py report`; reports `deploy/web/*.yaml` (Kubernetes) and `gitops/apps/web/app.yaml` (Argo CD) as not covered; Terraform, Ansible and Helm as covered.
- [ ] Suggests narrow paths and asks before writing.
- [ ] After approval, writes `.claude/rules/devops-kit-paths-kubernetes.md` and `…-argocd.md` with only `paths` + a pointer to the kit rule (no copied standards, no `@import`); a second `report` shows everything covered.

## Headless check

Headless flags: `--allowedTools "Bash(python3:*)"`

```check
bash_commands | grep -q 'coverage.py' || fail "coverage script not run"
final_text | grep -q 'deploy/web' || fail "deploy/ not reported"
final_text | grep -q 'gitops/apps/web' || fail "gitops app not reported"
! ls .claude/rules/devops-kit-paths-*.md 2>/dev/null || fail "wrote rule files without asking"
```

## Findings
