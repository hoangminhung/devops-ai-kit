---
name: playbook-pg-migration
description: Playbook for moving PostgreSQL between Kubernetes clusters or environments, especially with Crunchy Postgres Operator (PGO). Covers how to choose a method (PGO standby cluster from a pgBackRest repo or streaming, restore from backup, logical replication, dump/restore), pre-flight checks (versions, extensions, collation/glibc, sequences, roles), write freeze and cutover, data checks, rollback and the point of no return. Use whenever a task moves, clones, upgrades across clusters, or cuts over a PostgreSQL database.
when_to_use: Use when moving / cloning / cutting over PostgreSQL to another cluster or environment (PGO, CloudNativePG, plain Postgres), even if the user only says "move the DB to the new cluster". Vietnamese triggers — "chuyển DB sang cluster mới", "di chuyển / clone / cutover PostgreSQL sang cluster hoặc môi trường khác".
---

# Playbook: Move PostgreSQL between Kubernetes clusters

<!-- devops-ai-kit · Last reviewed: 2026-10-28 · Always L3. See also: `db-reliability`, `disaster-recovery`, `k8s-storage`. -->

The field names of the `PostgresCluster` CR and the exact behavior change between PGO versions. Ask `infra-researcher` to check the syntax for the **exact PGO and PostgreSQL versions** before you write manifests. This playbook explains how to think about the migration and what you must not miss.

## 1. Check the source (add to recon)

- [ ] Versions: PostgreSQL major / minor, PGO (source and target), Kubernetes on both clusters.
- [ ] DB size, biggest tables, WAL rate (to estimate the sync time).
- [ ] Extensions and their versions (`\dx` on each database). Does the target have the same extensions / versions?
- [ ] Roles, ownership, grants. Which user does the app use? Which Secret holds the password?
- [ ] Tables **without a primary key** (important for logical replication).
- [ ] Sequences (logical replication does **not** copy sequence values).
- [ ] Locale / collation: provider (libc or ICU), glibc version of the source and target images.
  - Physical replication / restore between images with different glibc versions can **silently break the order of indexes on text columns**.
  - If they are different: use the same image line, or plan a `REINDEX` of text indexes after the move.
- [ ] Current pgBackRest repo: type (S3 / Azure Blob / GCS / volume), retention, latest backup. Has anyone ever tested a restore?
- [ ] Network between the two clusters (if you need streaming / logical), or both clusters can reach the object storage.
- [ ] How the app connects: Service name, PgBouncer, connection string in a Secret, DNS / ExternalName.

## 2. Choose a method

| Method | When to use | Downtime | Notes |
|---|---|---|---|
| **A. PGO standby cluster** (the target cluster runs in standby mode and gets WAL from a shared pgBackRest repo and/or streaming from the source primary) | Source is PGO, **same PG major**, you want short downtime | Short (only promote + switch connections) | Needs the same repo / credentials. Before promote, stop writes on the source cluster to avoid split-brain |
| **B. Restore a pgBackRest backup into a new cluster** (dataSource points to the source's repo) | Downtime of restore + replay time is OK, or you want a test copy | Medium (for a cutover, writes must stay frozen during the whole restore) | Very good for a **rehearsal** before the real run |
| **C. Logical replication** (publication / subscription) | Different PG major (move + upgrade together), or the source is not PGO | Short | Does not copy DDL, sequences, large objects. Tables need a PK / replica identity. You must sync sequences at cutover |
| **D. pg_dump / pg_restore** | Small DB, downtime of dump + restore time is OK | Longest | Simplest. Use directory format `-Fd` + `-j` to run in parallel |

Write the chosen method in the plan, and why you did not choose the others (suggest an ADR if the decision is for many DBs).

## 3. Prepare the target cluster (before cutover)

- [ ] StorageClass follows the standard (`k8s-storage`). PVCs are big enough (≥ 1.5 × current data + growth).
- [ ] The target cluster has its **own** pgBackRest repo, and **the first full backup succeeded before cutover**.
  - Never run production on the new cluster without a backup.
  - With method A, keep the shared repo (for WAL) separate in your mind from the backup repo used after promote.
- [ ] Monitoring for the target cluster works (exporter, alerts for replication / backup / disk) **before** you switch traffic.
- [ ] PgBouncer on the target side (if used), with pool size recalculated for the number of app pods.
- [ ] Rehearse the full process at least once on a copy (method B is good for making the copy). Measure the real time.

## 4. Cutover (steps the plan must have, in this order)

1. Announce it and start the maintenance window. DNS TTL was lowered earlier.
2. Check again: lag close to 0 (A / C), latest target backup is OK, target monitoring is green.
3. **Write freeze on the source:** scale the writing apps to 0, or block writes in the DB. Check that no write connections are left (`pg_stat_activity`).
4. Wait until sync is complete:
   - A: the target has received / replayed the last WAL;
   - C: `pg_stat_subscription` shows no lag;
   - B / D: the restore is finished.
5. **Check the data** (section 5) before you allow writes again.
6. Promote the target (A: turn off standby mode in the way your PGO version does it; C: stop the subscription, `setval` sequences ≥ max(id) of each table).
7. — **Point of no return** —
   - After the app writes to the target, going back to the source means you lose new data or must merge it by hand.
   - The plan must say who decides to pass this point, and how much time they have.
8. Switch connections: update the app's Secret / connection string / Service / DNS. Scale the app up.
9. Smoke test the app (real reads + writes). Watch connection errors, latency, error rate.
10. Keep the source cluster **unchanged and with no writes** for the agreed rollback period. Remove the source later, in a separate change.

## 5. Data checks

| Check | How |
|---|---|
| Row counts | Important tables: `count(*)` on both sides. Other tables: compare `n_live_tup` (approximate) and investigate big differences |
| Checksum of important tables | Hash the data in PK order (e.g. `md5(string_agg(t::text, ',' ORDER BY id))` on small / medium tables, or by id range on big tables) |
| Sequences | Current value ≥ `max(id)` of the matching table |
| Extensions / roles / grants | Compare the lists on both sides |
| Valid indexes | No `INVALID` indexes (`pg_index.indisvalid = false`). If glibc / collation changed, REINDEX is done |
| App | The main business flows can read / write |

## 6. Rollback

- **Before PONR:** allow writes on the source again and point connections back to the source. The target can be rebuilt.
- **After PONR:** new data must be checked / moved back. This is hard: it needs its own plan, or you accept that there is no rollback after time X.
- The plan states the deadline for the rollback decision (e.g. 30 minutes after writes are allowed again).

## 7. Docs to leave behind

- A change record with the real time of each step (useful for the next migration).
- A runbook for the target cluster: backup / restore (with the test restore), failover, upgrade, alerts.
- A concept note on PGO / pgBackRest / Patroni if the user is new to them.
