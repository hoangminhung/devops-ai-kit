---
name: db-reliability
description: Database reliability engineering standards for PostgreSQL (and MySQL) on Kubernetes — zero-downtime schema changes with expand/contract, safe DDL (lock_timeout, CREATE INDEX CONCURRENTLY, NOT VALID constraints), running migrations as Jobs/PreSync hooks instead of initContainers, connection pooling with PgBouncer, and operator-managed clusters (Crunchy PGO, CloudNativePG). Use whenever writing or reviewing schema migrations, deploying or tuning database clusters on Kubernetes, configuring poolers, or planning database upgrades.
when_to_use: Use when writing/reviewing schema migrations, deploying or tuning database clusters on Kubernetes (PGO, CloudNativePG), configuring PgBouncer, or planning a database upgrade. Vietnamese triggers — "viết/review migration schema", "triển khai hoặc tinh chỉnh cluster database trên Kubernetes", "cấu hình PgBouncer", "lên kế hoạch nâng cấp database".
---

# DBRE (Database Reliability Engineering) standards

<!-- devops-ai-kit · Last reviewed: 2026-10-28 · Moving a database between clusters: see skill `playbook-pg-migration`. -->

## 1. Schema changes without downtime (expand / contract)

- **MUST** Do not rename a column, change a data type or drop a column in **one** release on production. Use three phases:
  1. **Expand:** add the new column / table (nullable or with a default). The app writes to both old and new.
  2. **Backfill:** copy old data to the new place in small batches, with a way to stop / resume. Do not run one huge `UPDATE` that locks the table.
  3. **Contract:** the app uses only the new column. Drop the old column in a **later** release.
- **MUST** PostgreSQL: set `SET lock_timeout = '5s'` (or a suitable value) before DDL on a busy table. A DDL that waits for a lock blocks every query queued behind it, so it is better to fail early and retry than to hang the whole system.
- **MUST** Create indexes on tables that have data with `CREATE INDEX CONCURRENTLY`. This command **cannot run inside a transaction**, so the migration tool must run that step without a transaction. If it fails, the index is left `INVALID`: you must `DROP` it and create it again.
- **SHOULD** Add constraints on big tables with `NOT VALID`, then run `VALIDATE CONSTRAINT` in a separate step.
- **SHOULD** Adding a column with a *volatile* default (for example a function) rewrites the whole table. A constant default is fast (PostgreSQL ≥ 11).
- MySQL: use `ALGORITHM=INPLACE, LOCK=NONE` when supported. For big tables, consider gh-ost / pt-online-schema-change.

## 2. Running migrations on Kubernetes

- **MUST** Do not run migrations in the `initContainers` of a Deployment with `replicas > 1`: pods run at the same time and cause race conditions and deadlocks.
- **MUST** A migration is a separate Kubernetes `Job`, run by an Argo CD `PreSync` hook (with `hook-delete-policy: BeforeHookCreation`) or by a separate CD pipeline step, **before** the app rollout.
- **SHOULD** The Job has a small `backoffLimit`, an `activeDeadlineSeconds`, and enough logs to see at which step the migration stopped.

## 3. Connection pooling

- **MUST** Apps with autoscaling connect to the DB through a pooler (PgBouncer for PostgreSQL, ProxySQL for MySQL), so the number of connections does not go over `max_connections` when the number of pods grows.
- Calculate first: `max pods × pool size per pod` ≤ `PgBouncer pool`, and `default_pool_size × number of database/user pairs` ≤ `max_connections` minus the part kept for admin / replication.
- **CONTEXT** `transaction` pooling mode saves the most connections, but it breaks session features (session `SET`, session advisory locks, `LISTEN/NOTIFY`, prepared statements on old PgBouncer versions). Check the PgBouncer and driver versions before you choose it.
- Operators often include a pooler: PGO (`spec.proxy.pgBouncer` in `PostgresCluster`), CloudNativePG (`Pooler` CRD). Check the fields for the operator version that is running.

## 4. Operator-managed database clusters

- **MUST** Make changes through the operator's CR (`PostgresCluster`, `Cluster`…) in Git. Do not edit the StatefulSet / Pod the operator creates, because the operator will overwrite them.
- **MUST** Production has at least 1 replica, DB-level backup (pgBackRest / Barman) to object storage outside the cluster, working PITR, and a tested restore.
- **SHOULD** Automatic failover (Patroni in PGO, the CNPG mechanism) has been tested at least once in a non-production environment.
- **SHOULD** Upgrade the major version with the operator's own method (PGO has the `PGUpgrade` CRD; CNPG has its own method per version). This is always L3 and needs a backup and a rollback plan.
- Put database PVCs on a suitable StorageClass (see `k8s-storage`). If the operator already keeps DB replicas → consider fewer replicas at the Longhorn level.

## 5. Observability

- **SHOULD** Have metrics and alerts for:
  - replication lag;
  - connections compared with `max_connections`;
  - long-running transactions / idle in transaction;
  - deadlock rate;
  - disk and WAL usage;
  - latest successful backup.
- **SHOULD** Turn on `pg_stat_statements` to find heavy queries.
