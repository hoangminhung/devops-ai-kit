---
name: disaster-recovery
description: Backup and disaster-recovery standards — defining RTO/RPO, 3-2-1 and offsite copies, immutable backups (S3 Object Lock, Azure immutable blob storage, GCS retention), backup layers for Kubernetes objects, volumes and databases (GitOps, Velero, Longhorn, pgBackRest), restore drills, and backup monitoring. Use whenever designing backups, before any stateful or irreversible change, when defining RTO/RPO for a service, or when planning or reviewing restore procedures and DR drills.
when_to_use: Use when designing backups, before any stateful / irreversible change, when defining RTO/RPO, or when writing / reviewing restore procedures and DR drills. Vietnamese triggers — "thiết kế backup", "thay đổi stateful / không đảo ngược", "xác định RTO/RPO", "lập / review quy trình restore và diễn tập DR".
---

# Backup & disaster recovery standards

<!-- devops-ai-kit · Last reviewed: 2026-10-28 -->

Basic rule: **a backup that has never been test-restored is not a backup.**

## 1. RTO / RPO

- **MUST** Each production service has an RTO (the longest time allowed to recover) and an RPO (the most data you accept to lose), written in the service's runbook or ADR.
- **MUST** The backup design must meet the written RPO (for example: with an RPO of 5 minutes, a nightly backup is not enough; you need WAL archiving / PITR).

## 2. Layers to back up

| Layer | Recommended method |
|---|---|
| Kubernetes objects | The GitOps repo is the source of truth. **CONTEXT** Velero when some objects are not in Git |
| Volumes | Longhorn backup to object storage, or CSI snapshot + Velero data mover |
| Databases | DB-level backup (pgBackRest via PGO, Barman via CNPG) with PITR, preferred over volume snapshots |
| Cloud infrastructure | IaC code in Git + a state backend with versioning |
| Secrets | Key Vault / Secrets Manager with soft-delete and purge protection; know how to recover |

## 3. Storage location & immutability

- **SHOULD** 3-2-1: at least 3 copies, on 2 types of media / systems, 1 copy in another place (another account / subscription / region).
- **SHOULD** Production: immutable backups, to protect against ransomware or a stolen admin account:
  - AWS: S3 Object Lock.
  - Azure: immutable storage for Blob (time-based retention).
  - GCP: GCS bucket retention policy / lock.
- **CONTEXT** Compliance mode / a locked policy cannot be shortened or removed, not even by the root account. Test first with governance / unlocked mode, and calculate the storage cost carefully before you lock.
- **MUST** The credential that writes backups cannot delete old backups (when the platform lets you split these permissions).

## 4. Restore drills

- **MUST** Before any L3 change that touches data: test-restore the latest backup into a separate environment and check the data. Write the result in the plan's prerequisites.
- **SHOULD** Run drills regularly. Ideal: an automatic weekly pipeline: take the latest backup → restore into a sandbox → run data integrity smoke tests → report the result → delete the sandbox. Minimum: a manual drill every quarter.
- **SHOULD** Measure the real restore time and compare it with the RTO. If they do not match, update the RTO or improve the process.

## 5. Backup monitoring

- **MUST** Alert when a backup fails **and** when "there is no successful backup in N hours". A problem like "the job did not run" never creates a failure event.
- Example metrics (depends on the tool):
  - Velero: `velero_backup_last_successful_timestamp`;
  - pgBackRest / Longhorn: use the metrics of the matching exporter — check the metric names for the version that is running.

## 6. Drill report template (write it in the runbook)

| Date | Backup source | Restored into | Restore time | Data check | Result | Problems found |
|---|---|---|---|---|---|---|
