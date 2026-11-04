# Contributing

Thanks for helping. The kit guards real infrastructure, so changes are reviewed for safety first.

## Before a pull request

```bash
python3 -m unittest discover -s tests      # unit and contract tests (CI runs them)
python3 scripts/validate.py                # structure, links, settings, pinned safety phrases
shellcheck -S warning ./*.sh scripts/*.sh setup/k8s/*.sh sandbox/*.sh scenarios/*.sh
```

- One topic per pull request; never commit tokens, kubeconfigs, state or plan files.
- Content is in English; `docs/vi/` and `README.vi.md` are updated in Vietnamese to match.
- A change that alters what the kit allows, asks or denies needs a test in `tests/test_hook.py` or `tests/test_validate.py`, and a line in `CHANGELOG.md`.

## Larger changes: RFC first

For a new feature, a change of default behaviour or anything that touches the hook, write an RFC in `docs/proposals/000N-<name>.md`: the problem with numbers, the chosen and rejected options, changes per file, risks, and **acceptance criteria that are commands with an expected result**.

## Benchmark claims

Scenarios (`scenarios/`) have **outcome** checks (`fail_o`) and **process** checks (`fail_p`); report them separately. A claim that the kit makes something safer needs outcome numbers with n ≥ 3 and intervals, not a process score. Runs cost tokens: say the estimated cost in the pull request.

## Agents for developing the kit

`.claude/agents/` in this repo (not installed for kit users) holds three agents that load when you run Claude Code in a checkout of this repo:

| Agent | Use |
|---|---|
| `kit-investigator` | measure and read docs for one work item; writes a report to `.work/investigations/` |
| `kit-proposal-reviewer` | independent red-team review of an RFC; verdict APPROVE / CHANGES REQUIRED / BLOCK |
| `kit-verifier` | runs the RFC's acceptance commands and returns their real output; verdict PASS / PARTIAL / FAIL |

The session that wrote an RFC or the code never reviews or verifies it itself.
