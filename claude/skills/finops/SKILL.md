---
name: finops
description: Cloud cost-control standards — cost estimation gates for Terraform changes (Infracost), NAT and data-transfer costs, orphaned resources, Kubernetes right-sizing, storage and log-ingestion costs (including Azure Log Analytics), and non-production savings. Use whenever a change adds or resizes cloud resources, when designing networking that affects data transfer, when reviewing monitoring/logging volume, or when the user asks why the bill is high or how to cut costs.
when_to_use: Use when a change adds or resizes cloud resources, when network design affects data transfer cost, when reviewing log/metric volume, or when the user asks about cost. Vietnamese triggers — "tăng/đổi kích thước tài nguyên cloud", "chi phí truyền dữ liệu", "review lượng log/metric", "hỏi về chi phí".
---

# FinOps & cost control standards

<!-- devops-ai-kit · Last reviewed: 2026-10-28 -->

## 1. Estimate before you create

- **SHOULD** Terraform changes that affect cost: run `infracost diff` and put the number (monthly increase / decrease) in the plan.
- **CONTEXT** Automatic blocking thresholds in CI (for example, an increase > 200 USD/month needs Lead / Finance approval and no auto-merge) follow the organization's policy.
- **SHOULD** Costs that are hard to see must be estimated in words if the tool cannot calculate them: data transfer, log ingestion, object storage requests, number of snapshots.

## 2. Network & data transfer

- **SHOULD** Non-prod: one shared NAT Gateway (or a NAT instance) instead of one per AZ.
- **SHOULD** For large data volumes, prefer keeping internal traffic in the same zone (topology-aware routing) to avoid cross-AZ fees.
- **SHOULD** AWS: use Gateway Endpoints for S3 / DynamoDB (free) instead of going through NAT.
- **SHOULD** Use cross-region backup / replication only when the RPO / RTO really needs it; write the cost in the ADR.

## 3. Logs & metrics (often a surprise cost)

- **SHOULD** Azure: Log Analytics / Container Insights charge per GB ingested. Collect only the namespaces / tables you need (data collection rule), consider a cheaper log plan for logs that are rarely queried, and set retention on purpose.
- **SHOULD** Self-hosted (Loki / Prometheus): the cost is in storage and replication. Size = ingest volume × retention × replication factor (of the app **and** of the storage, see `k8s-storage`).
- **MUST** Do not turn on debug logs in production without a time to turn them off.

## 4. Kubernetes

- **SHOULD** Requests decide how many nodes you pay for. Regularly compare requests with real usage (`kubectl top`, Prometheus metrics) and adjust them. Inflated requests are the most common waste.
- **CONTEXT** Spot / preemptible nodes for workloads that can handle interruptions; on-demand for infrastructure node pools.
- **CONTEXT** Stop dev clusters outside working hours (for example `az aks stop` for a dev AKS) if the team agrees.
- **CONTEXT** OpenCost / Kubecost when you need to split cost by namespace / team.

## 5. Orphaned resources — scan regularly

- Disks not attached to a VM / node (Azure Managed Disk, EBS).
- Public IPs / Elastic IPs not assigned.
- Old snapshots past retention.
- Load Balancers with no healthy backend.
- PVs in `Released` state because of `reclaimPolicy: Retain`: review them, then delete in a controlled way. Do not delete them automatically, because they may hold data that must be kept.

## 6. Long-term commitments

- **CONTEXT** Reserved Instances / Savings Plans / Azure Reservations for a stable base load for ≥ 1 year. Decide based on at least a few months of real usage.
