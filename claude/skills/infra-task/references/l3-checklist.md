# Extra checklist for L3 changes

Use it when writing and when reviewing an L3 plan (stateful, cannot be undone, network, IAM).

## Data
- [ ] The latest backup was **test-restored successfully** (not only "the backup job is green"). The time and place of the restore are written in the plan.
- [ ] You know the real RPO if you had to restore right now (how old the backup is, whether WAL/PITR is continuous).
- [ ] There is a way to compare data after the change (row count, checksum, number of objects, size).
- [ ] The point of no return and the conditions to pass it are clearly defined.

## Availability
- [ ] The user accepts the expected downtime. There is a maintenance window if needed.
- [ ] There is a write freeze plan if data is moved.
- [ ] DNS TTL was lowered earlier if an endpoint changes.
- [ ] PDB / replica count does not block the planned drain/rollout.

## Access & network
- [ ] The IAM/RBAC change does not lock the operators out (there is a backup way in: break-glass account, console, OOB).
- [ ] The network/firewall change has a way back (e.g. keep the old rule in parallel, or an automatic undo command after N minutes if the connection is lost).
- [ ] The new CIDR does not overlap with peered / VPN / on-prem networks.

## Execution
- [ ] Every step has a measurable stop condition.
- [ ] A person (not the AI) decides on rollback and knows the time limit for that decision.
- [ ] Monitoring/alerts for the new component work **before** traffic/data is moved.
- [ ] Mutating steps on production are run by the user or go through a GitOps PR.
