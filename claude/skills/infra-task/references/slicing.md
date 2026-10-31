# Slicing a big infrastructure task

<!-- devops-ai-kit · Used by /infra-task Phase 3. A slice is a part of the task that can be deployed, verified and rolled back on its own. -->

## When to suggest slices

Suggest slicing in Phase 3 when **one** of these is true:

- the task is L3 and has several components that can be deployed separately;
- the plan would have more than ~10 steps;
- some parts can be rolled back on their own.

Do not slice a small task: each slice adds its own gate and review. If you are not sure, ask the user.

## How to cut slices

- Each slice must **work on its own**: after it, the system is in a valid, verified state, even if the next slices never run.
- Each slice has **its own rollback** that does not touch earlier slices.
- Order by dependency: what others need goes first (storage → database → app; metrics → logs → alerts).
- Put the riskiest or least-known part early, when stopping is still cheap, unless something else must come first.
- Aim for 2–5 slices. One slice = one reviewable diff.

Example — monitoring stack:

| Slice | Content | Verified by | Rollback |
|---|---|---|---|
| 01 Metrics | kube-prometheus-stack, storage, ServiceMonitors | targets up, dashboards load | `helm uninstall` + keep PVC |
| 02 Logs | Alloy + Loki | logs from every node visible in Grafana | remove Alloy, Loki |
| 03 Alert routing | Alertmanager receivers, routes, silences | test alert reaches the channel | old route config |

## Folder layout

```
docs/changes/<YYYY-MM-DD>-<slug>/
├── 00-brief.md            # shared: goal, scope, target, mode, requirement changes
├── 01-recon.md            # shared
├── 02-research.md         # shared
├── 03-plan.md             # overview: design, slice list, overall rollback / PONR / completion criteria
├── 04-plan-review.md      # review of the overview
├── slices/
│   ├── 01-metrics/
│   │   ├── 03-plan.md     # this slice's steps (plan-template format, "- [ ] Step N" lines)
│   │   ├── 04-plan-review.md
│   │   ├── 05-implementation.md
│   │   ├── 06-code-review.md
│   │   ├── 07-execution-log.md
│   │   └── 08-verification.md
│   └── 02-logs/ ...
└── 09-change-record.md    # one change record for the whole task (infra-scribe reads every slice)
```

In the overview `03-plan.md`, part "## 5. Slices" replaces "## 5. Steps":

```markdown
## 5. Slices

- [ ] Slice 01: Metrics
  - **Content:** ...
  - **Depends on:** —
  - **Rollback:** ...
  - **Done when:** ...
- [ ] Slice 02: Logs (Alloy + Loki)
```

Slice folders are named `slices/<NN>-<short-name>/`, with the same `NN` as the slice line.

## Flow

1. Phases 0–2 once for the whole task.
2. Phase 3: write the overview and the plan of **slice 01 only**. Later slices are planned in detail when you reach them, with what the earlier slices taught you.
3. Phase 4 + **GATE 1**: review the overview and slice 01's plan; the user approves both.
4. For each slice in order: Phase 3 (its plan, if not yet written) → Phase 4 + GATE 1 for that slice → Phase 5 → Phase 6 + GATE 2 → Phase 7 (tick its steps) → Phase 8 (verify this slice's "Done when").
5. When a slice is verified, tick it in the overview:

   ```bash
   python3 <skill base directory>/scripts/plan_status.py tick <task folder> <NN> --slice --result "<short result>"
   ```

   The script refuses if a step of that slice is still open.
6. After the last slice: Phase 8 on the overall completion criteria, then Phases 9–10 once.

## When a slice fails

- Stop at that slice. **Do not start the next slices.** Earlier slices stay as they are (they are verified and independent).
- Follow the slice's plan: fix or roll back **this slice only**.
- The slice line stays unticked, so `resume` comes back to it.
- If the failure changes the design, update the overview and the later slices as a requirement change (see SKILL.md), with a new review and the user's confirmation.

## Resume

`plan_status.py status <task folder>` shows the slices, the first unticked slice and the first unticked step inside it. Resume there, after the usual live-state check.
