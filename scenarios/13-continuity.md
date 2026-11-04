# 13 — Continuity: /handoff vs /compact across three sessions

- **Layer:** repo only
- **Fixture:** `continuity` (`release/tags.yaml`, `tools/bump-tag.sh`, and `docs/RELEASE.md`, which advises `--inplace`, the flag that always fails)
- **Kit features:** `/handoff`, the progress file (`00-core` §9)

A release in three parts, one per session. The order and the versions are given **only in the first prompt**, so a later session knows them only from what was carried over. Part 1 meets a dead end: `docs/RELEASE.md` says `--inplace`, which always fails; `--patch` works.

- **Method A (compact):** one session. Part 1 → `/compact` → part 2 → `/compact` → part 3.
- **Method B (handoff):** part 1 → `/handoff` → confirm → **new session** for part 2 → `/handoff` → confirm → **new session** for part 3.

Run it with `scenarios/benchmark.sh --config-dir <dir> --continuity` (3 runs per method, costs tokens; see README). By hand: run the prompts below in the order of one method.

## Prompt

Part 1:

```prompt
We release three services in this order, one per session: api to 1.4.2, then web to 2.0.1, then worker to 0.9.7. In this session do only api: change its tag the way docs/RELEASE.md says, check release/tags.yaml, and commit with the message "release: api 1.4.2".
```

Parts 2 and 3 (the same text both times):

```prompt-next
Continue the release: do the next service only, check release/tags.yaml, and commit.
```

The answer to `/handoff`'s question (method B):

```confirm
Yes, write it.
```

## Expect

- [ ] Part 1: api is 1.4.2 and committed. If `--inplace` was tried, it failed and `--patch` was used.
- [ ] Part 2: web is 2.0.1, worker is still 0.9.6. Part 3: worker is 0.9.7.
- [ ] Parts 2 and 3 do not run `tools/bump-tag.sh … --inplace` again.
- [ ] Method B: after each `/handoff`, the progress file has the next step and a dead end for `--inplace` with `revisit if:`, and no task folder was edited.

Measured per run: total tokens and cost of all calls, how many times parts 2–3 ran `--inplace` (dead-end retries), and how many of parts 2–3 changed the right service to the right version. A run is **invalid** (not counted) when method A shows no `compact_boundary` after a `/compact`, or method B has no progress file after a handoff.

## Findings

- Not run yet. Estimated cost and the decision to run: see the PR that added this scenario.
