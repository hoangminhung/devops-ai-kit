# GCP

<!-- Last reviewed: 2026-10-28 -->

## Baseline
- **MUST** Terraform state in the `gcs` backend (has locking), with bucket versioning turned on.
- **MUST** CI uses Workload Identity Federation. Do not download service account JSON keys.
- **SHOULD** VMs / nodes have no external IP. Outbound traffic goes through Cloud NAT. Turn on Private Google Access on the subnet.
- **SHOULD** Budget + alerts per billing account / project.

## Production
- **SHOULD** GKE: prefer Autopilot when you do not need deep node customization. With Standard: Shielded Nodes, node auto-repair, auto-upgrade by release channel, maintenance window.
- **MUST** Pods access GCP through Workload Identity Federation for GKE.
- **SHOULD** Dataplane V2 (based on Cilium / eBPF) for NetworkPolicy and network observability.
- **SHOULD** Least privilege with the smallest predefined role that is enough. Use IAM Conditions when you need limits by time / resource.

## Enterprise landing zone
- Hierarchy `Organization` → `Folders` → `Projects`. Organization Policy (allowed regions, no external IPs, no service account key creation).
- Shared VPC: the host project manages the network, service projects run the workloads.
- Security Command Center at Organization level.
