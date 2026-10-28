# Longhorn — operations & configuration

<!-- Last reviewed: 2026-10-28 · Setting / field names can change between versions: compare with the Longhorn docs for the version that is running (`kubectl -n longhorn-system get settings.longhorn.io` shows the real settings). -->

## Mental model

Each Longhorn volume has:

- one **engine** (runs on the node where the pod has the volume attached);
- N **replicas** placed on different nodes.

The engine writes to all replicas at the same time. If one replica breaks, Longhorn rebuilds it on another node from the other replicas.

## Node requirements

- **MUST** `open-iscsi` (iscsid) runs on every node; RWX also needs an NFSv4 client.
- **SHOULD** A separate disk for Longhorn data (default `/var/lib/longhorn`), not shared with the OS disk: a full OS disk takes the whole node down.
- **SHOULD** Check before install / upgrade with the preflight / environment check tool of the exact Longhorn version.

## Important StorageClass parameters

| Parameter | Meaning | Recommendation |
|---|---|---|
| `numberOfReplicas` | Copies per volume | 3 for data that the app does not replicate. **CONTEXT** 1–2 for apps that replicate themselves (PG with replicas, Loki / Prometheus HA) |
| `dataLocality` | Keep one replica on the node that runs the pod or not | `best-effort` for latency-sensitive workloads. **CONTEXT** `strict-local` with 1 replica when the app replicates itself |
| `reclaimPolicy` | What happens when the PVC is deleted | `Retain` on production |
| `fsType` | File system | `ext4` (default) or `xfs` if the app needs it |

Create a separate StorageClass for each group of needs (e.g. `longhorn-3r`, `longhorn-1r-local`) instead of changing the default StorageClass.

## Capacity

- Real usage = volume size × number of replicas + snapshots. Old snapshots quietly take more space.
- **SHOULD** Set `storage-over-provisioning-percentage` and `storage-minimal-available-percentage` on purpose; alert when a node disk passes the threshold.
- **SHOULD** Recurring jobs have a sensible `retain`, so snapshots do not grow forever.

## Backup

- **MUST** Set the backup target to object storage (S3-compatible / Azure Blob) or NFS **outside the cluster**; check that the backup target is available.
- **SHOULD** Use `RecurringJob` (CRD) for scheduled snapshots and backups, attached to volumes through groups / labels.
- **MUST** Regularly test-restore a backup into a new volume and check the data (see `disaster-recovery`).
- Databases: Longhorn backup is only an extra layer; the main layer is the database-level backup.

## Upgrades

- **MUST** Read the release notes and upgrade guide of the target version. Longhorn usually supports upgrades only from the previous minor version, so you must upgrade one minor at a time.
- **MUST** All volumes are `healthy` before the upgrade, and the latest backup succeeded.
- **SHOULD** Upgrade volume engines as planned (automatic or manual, depending on the setting), and watch each group of volumes.
- This is an L3 change on production.

## Quick debug

```bash
kubectl -n longhorn-system get pods                       # manager, engine/instance manager, csi
kubectl -n longhorn-system get volumes.longhorn.io        # state / robustness
kubectl -n longhorn-system get replicas.longhorn.io | grep -v running
kubectl -n longhorn-system get nodes.longhorn.io          # node schedulable? disk full?
kubectl -n longhorn-system logs -l app=longhorn-manager --tail=100
```

| Symptom | Common cause | Check |
|---|---|---|
| Volume `degraded` | A node / disk with a replica broke, rebuild in progress | replicas.longhorn.io, nodes.longhorn.io |
| PVC stuck `Pending` / not attaching | iscsid not running, node not schedulable, disk full | `systemctl status iscsid`, Longhorn node conditions |
| Slow writes | Replicas over a slow network, too many replicas, many snapshots | `dataLocality`, replica count, snapshot count |
