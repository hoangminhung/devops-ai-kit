# Output language: Vietnamese

<!-- devops-ai-kit · Installed as rules/devops-kit/01-language.md by `./install.sh --lang vi`. -->

- Write handover docs in Vietnamese: concept notes, runbooks, change records, postmortems, ADRs. Agent reports are also in Vietnamese.
- Keep technical terms in English (e.g. rollback, blast radius, PVC, StorageClass, cutover). Do not translate commands, flags, field names or error messages.
- Write README, PR descriptions, commit messages and code comments in English.
- In chat, reply in the language the user writes in.
- Only the content is in Vietnamese. Keep these in English, exactly as the templates write them: headings, placeholders (`<to fill in: ...>`), field labels (`Applies to:`, `Updated:`, `Status:`), file and folder names, and anything one file uses to point to another. Agents find parts of other files by these names.
- The project's CLAUDE.md can override this rule.
