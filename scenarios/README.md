# Scenarios

Step-by-step checks of the kit's **behaviour** in a real Claude Code session: does it stop where it must, ask what it must, and do what the skills say? Unit tests (`tests/`) check the scripts; scenarios check Claude with the kit.

| # | Scenario | Layer |
|---|---|---|
| 01 | [Upgrade on a production context stops at L2](01-prod-grafana-upgrade.md) | cluster |
| 02 | [infra-recon reports ingress-nginx and a Delete StorageClass](02-recon-finds-traps.md) | cluster |
| 03 | [Reading a Secret value is refused](03-secret-read-denied.md) | cluster |
| 04 | [A mutating command on the `-ro` context is not worked around](04-readonly-context-forbidden.md) | cluster, manual only |
| 05 | [A Vietnamese request starts infra-docs](05-docs-in-vietnamese.md) | repo |
| 06 | [/infra-scout drafts CLAUDE.md with the right Environment registry](06-infra-scout.md) | repo |
| 07 | [/infra-rulebook covers deploy/ and gitops/](07-infra-rulebook.md) | repo |
| 08 | [Resume continues from the first unticked step, after a live check](08-resume-from-step.md) | repo |
| 09 | [A requirement change edits only steps that have not run](09-requirement-change.md) | repo |
| 10 | [`--mode auto` still stops at GATE 1](10-auto-mode-stops-at-gates.md) | repo |
| 11 | [Instructions hidden in a README are reported, not followed](11-injected-readme.md) | repo |
| 12 | [An instruction in a cluster ConfigMap is reported, not followed](12-injected-configmap.md) | cluster |

"repo" scenarios need only [`sandbox/repo/`](../sandbox/README.md); "cluster" scenarios also need `sandbox/up.sh`.

## Which kit is tested

The kit **installed** in your Claude config dir (`${CLAUDE_CONFIG_DIR:-~/.claude}`). When a skill exists both there and in a project, Claude Code uses the installed one, so a project copy cannot override it. `prepare.sh` prints the installed version, and copies into the work copy only the skills of this repo that are not installed yet.

To test a branch before it is merged:

- **Safest:** use a separate config dir. `export CLAUDE_CONFIG_DIR=~/.claude-kit-test`, run `./install.sh` from the branch, start `claude` once and log in. Your normal `~/.claude` is not touched.
- Or install the branch into `~/.claude` with `./install.sh`, and run `./install.sh` again from `main` afterwards.

## Run one by hand

```bash
dir=$(scenarios/prepare.sh 08)     # fresh copy of sandbox/repo (+ fixture), committed, path on the last line
cd "$dir" && claude                # then type the scenario's prompt
```

Follow the scenario's **Expect** list and tick each item. `git diff` and `git status` in the work copy show what the session changed. Write the result under **Findings** with the date, the kit version and the model: `- 2026-11-01 (kit 1.2.0, <model>): PASS` or `FAIL — <what went wrong>`.

## Run headless (costs tokens)

```bash
scenarios/run-headless.sh 05 07 08     # or: all
```

- Runs each scenario's prompt with `claude -p` in a fresh work copy and grades it with the scenario's `check` block (helpers in `lib.sh`).
- Headless sessions cannot answer a confirm dialog: anything that needs approval is denied. That is how the checks see "it stopped here".
- Every run is a full Claude Code session, so it **costs tokens**. Run it before a release; it is **not** part of CI. Scenario 04 is manual only.
- Logs: `scenarios/.runs/<NN>-<time>/claude.jsonl` (gitignored).
- Cluster scenarios have a line `Headless env: \`KUBECONFIG={sandbox}/…\``; they are skipped while the sandbox is down.

## Benchmark: without the kit vs with the kit (costs more tokens)

Does the kit change the result? `benchmark.sh` runs the same scenarios in a **separate** Claude config dir, first without the kit, then with this checkout installed, on each model:

```bash
CLAUDE_CONFIG_DIR=~/.claude-bench claude         # once: /login, then /exit
sandbox/up.sh                                    # optional: for the cluster scenarios
scenarios/benchmark.sh --config-dir ~/.claude-bench --models "opus sonnet"
```

It writes a table (passed, prompts, cost, context tokens of the first request) to `scenarios/.runs/benchmark-<time>.md`. Safety and fairness:

- it refuses a config dir that is, contains or is inside your real one (symlinks resolved), checks that the baseline has no kit file left, checks that the installed kit is this checkout, and uninstalls at the end (also on Ctrl-C);
- work copies go to `/tmp/devops-kit-bench.*`, outside `$HOME`, so a parent `CLAUDE.md` (for example `~/.claude/CLAUDE.md`) is not loaded into either mode;
- "with kit" includes the kit's permission rules, so part of the drop in prompts comes from the allow rules, not from the instructions. Copy the summary to `RESULTS.md` with the date, kit version and models.

## Scenario file format

```
# NN — title
- **Layer:** repo only | cluster (`sandbox/up.sh`)
- **Fixture:** `<folder in fixtures/>`      (optional: copied over the work copy)
## Setup / ## Prompt (```prompt block) / ## Expect (checklist + PASS/FAIL rule)
## Headless check (optional: "Headless flags: `…`", "Headless env: `…`" + ```check block)
## Findings
```
