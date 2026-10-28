---
name: k8s-storage
description: Kubernetes storage standards — choosing CSI drivers and access modes, StorageClass settings (reclaim policy, binding mode, expansion), Longhorn operations (replicas, data locality, backups, recurring jobs, upgrades), snapshots vs backups, and avoiding double replication for apps that replicate themselves. Use whenever creating or changing StorageClasses, PVCs for databases or monitoring, Longhorn configuration, volume backups, or when planning stateful workloads on Kubernetes.
when_to_use: Use when creating/changing a StorageClass, PVCs for a database or monitoring, Longhorn config, volume backups, or when planning stateful workloads on Kubernetes. Vietnamese triggers — "tạo/đổi StorageClass", "PVC cho database hoặc monitoring", "cấu hình Longhorn", "backup volume", "workload stateful trên Kubernetes".
---

# Kubernetes storage standards

<!-- devops-ai-kit · Last reviewed: 2026-10-28 -->

## Choose the storage type & access mode

- **MUST** Databases (PostgreSQL, MySQL…): block storage with `ReadWriteOnce` or `ReadWriteOncePod`. Do not use NFS / RWX for a database engine. This includes Longhorn RWX, which runs through an NFS share-manager.
- **SHOULD** Shared data (uploads, shared assets): prefer moving the app to object storage (S3 API). RWX through NFS CSI / CephFS / Longhorn RWX is **CONTEXT**, for when the app cannot be changed.
- **SHOULD** Apps that replicate their own data (PostgreSQL with replicas, Loki / Prometheus HA, Kafka, Elasticsearch): think about fewer replicas at the storage layer. Avoid "replication on top of replication": 3 Longhorn copies × 3 app replicas = 9 copies of the data, 3 times the disk cost and the write latency.

## StorageClass

- **MUST** Production uses `reclaimPolicy: Retain` for important data. The default `Delete` means deleting the PVC also deletes the data.
- **SHOULD** `allowVolumeExpansion: true`.
- **CONTEXT** `volumeBindingMode: WaitForFirstConsumer`:
  - **required** for zonal disks (Azure Disk, EBS, Persistent Disk), so the volume is created in the same zone as the pod;
  - not required for Longhorn (its volumes can attach from any node).
- **MUST** You cannot change the `storageClassName` of a PVC in use in place: you must create a new PVC and move the data. This is an L3 change.

## Snapshot ≠ backup

- **MUST** A snapshot lives on the same storage system (same failure domain). It counts as a backup only after the data is copied to **independent object storage**, best in a different account / subscription / region.
- **SHOULD** Databases use app-level backups (pgBackRest through PGO, with PITR) instead of relying only on volume snapshots, so the data is consistent.
- **SHOULD** Kubernetes objects are restored from the GitOps repo. Use Velero when you need to back up both objects and volumes (data mover / CSI snapshot). Details in the skill `disaster-recovery`.

## Longhorn

Read `references/longhorn.md` when you configure, upgrade or debug Longhorn.

## Verify after a storage change

```bash
kubectl get storageclass
kubectl get pvc -A | grep -v Bound            # expected: no Pending/Lost PVCs
kubectl -n longhorn-system get volumes.longhorn.io \
  -o custom-columns=NAME:.metadata.name,STATE:.status.state,ROBUSTNESS:.status.robustness
# Expected: robustness = healthy (not degraded/faulted)
```
