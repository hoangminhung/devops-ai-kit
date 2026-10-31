# 05 — A Vietnamese request starts infra-docs

- **Layer:** repo only
- **Kit features:** skill `infra-docs` (Vietnamese trigger phrases in `when_to_use`), `01-language.md` (`--lang`)

## Prompt

```prompt
Viết tài liệu về Longhorn cho người mới vào team, giải thích nó hoạt động thế nào.
```

## Expect

- [ ] The `infra-docs` skill is used (concept note).
- [ ] Headings, placeholders and field labels stay in English; the content follows `--lang` (Vietnamese with `--lang vi`, English with `--lang en`).
- [ ] Has `Applies to:` and `Updated:` lines, and marks claims with ✅ / 📖 / ⚠️.

## Headless check

Headless flags: `--permission-mode acceptEdits`

```check
skills_used | grep -q infra-docs || fail "infra-docs not used"
```

## Findings

- 2026-10-31 (installed kit 1.1.0, `--lang vi`, claude-opus-5-5, headless, ~$0.70): PASS — `infra-docs` used; concept note `docs/concepts/longhorn.md` with English headings and labels (`Applies to:`, `Updated:`), Vietnamese content, ✅ / 📖 / ⚠️ markers, and a note that nothing was checked on a real cluster.
