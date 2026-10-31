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
draft="$(final_text; written_text)"   # the draft may be shown in the chat or saved outside the repo
grep -qi 'environment registry' <<<"$draft" || fail "no Environment registry in the draft"
grep -q 'terraform/envs/prod' <<<"$draft" || fail "prod Terraform root not found"
grep -q 'sandbox-prod' <<<"$draft" || fail "Argo CD destination not used"
[[ ! -e CLAUDE.md ]] || fail "wrote CLAUDE.md without asking"
```

## Findings

- 2026-10-31 (installed kit 1.1.0 + `infra-scout` from the branch, claude-opus-5-5, headless, ~$0.39): PASS — read-only, draft with Environment registry (dev / prod, `sandbox-prod`), questions in rounds with recommendations, CLAUDE.md not written without consent. It also found a real mismatch: `deploy/web` Service selects `app: web` but the chart labels pods `app: <release>`.
- 2026-10-31 first run: FAIL caused by the test setup, not the skill — skills were linked with symlinks pointing outside the project, which Claude Code does not read, and the check looked only at the final message. Fixed: `prepare.sh` copies skills; the check also reads written files; the skill now says to show the draft in the chat.
