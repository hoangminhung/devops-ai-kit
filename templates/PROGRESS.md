# PROGRESS — <project name>

<!-- Claude reads this at the start of a session and updates it after each task (devops-ai-kit 00-core §9);
     `/handoff` updates it before you /clear.
     PROGRESS.md is the long-term, project-level view: goals, overall state, decisions, and ONE line per task
     with a link to its task folder. The details of a change (plan, steps, logs, verification) live only in
     its task folder (docs/changes/<date>-<slug>/). Do not copy them here.
     "Current state" and "Next steps" describe now: rewrite them, do not append. Other parts: newest first.
     Keep it short: under ~200 lines. Move old lines out of "Done log" when it grows.
     No secrets here. -->

Last updated: <YYYY-MM-DD HH:MM> · branch <name> @ <short sha>

## Current state

<!-- Rewritten at each update. A fact about the live state keeps the date it was last checked by a command. -->

- <environment>: <one line about what is running / what is broken right now> (checked: <YYYY-MM-DD>)

## Next steps

<!-- Rewritten at each update. Step 1 is a concrete action the next session can start with: a file, a command or a question. -->

1. <exact next action>

## Open items

- [ ] <task> — <next step> (task folder: `docs/changes/<YYYY-MM-DD>-<slug>/` if any)

## Decisions

- <YYYY-MM-DD>: <decision> — <why, in one line>

## Dead ends — do not retry

<!-- Approaches that failed. Keep the ones that still apply; delete a line only when its "revisit if" came true. -->

- <YYYY-MM-DD>: <approach> — failed because <reason> · revisit if: <what would make it worth trying again>

## Done log

- <YYYY-MM-DD>: <what was done> (<link to change record / PR>)
