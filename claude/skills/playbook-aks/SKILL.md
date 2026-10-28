---
name: playbook-aks
description: Playbook for building or reworking an Azure Kubernetes Service (AKS) environment with Terraform — state backend, network and CIDR planning, Azure CNI Overlay, private vs public API server, Entra ID with Azure RBAC, workload identity, system and user node pools, upgrade channels and maintenance windows, monitoring and Log Analytics cost, policy, and a verification checklist. Use whenever the task is to build, extend, upgrade or review AKS or the Azure infrastructure around it.
when_to_use: Use when building, extending, upgrading or reviewing AKS and the Azure infrastructure around it, even if the user only says "build k8s on Azure". Vietnamese triggers — "dựng k8s trên Azure", "dựng, mở rộng, nâng cấp hoặc review AKS và hạ tầng Azure xung quanh nó".
---

# Playbook: Build AKS with Terraform

<!-- devops-ai-kit · Last reviewed: 2026-10-28 · See also: `cloud-platforms` (references/azure.md), `finops`, `pki-secrets`, rule `terraform.md`. -->

Attribute names of `azurerm_kubernetes_cluster` change between major versions of the `azurerm` provider: some attributes were renamed or removed. Ask `infra-researcher` to check them for the **exact provider version** that is pinned before you write code.

## 1. Design questions (the plan must answer them)

**Tier & size**

- [ ] Baseline / Production / Enterprise (see `cloud-platforms`).
- [ ] How many clusters, which environments, which regions. Are Availability Zones needed?

**Terraform**

- [ ] Backend `azurerm`, `use_azuread_auth = true`.
- [ ] Separate state: network / cluster / add-on.
- [ ] Provider `azurerm` pinned with `~>` major.
- [ ] CI logs in with OIDC (workload identity federation).

**Network & CIDR** (hard to change later, decide carefully)

- [ ] VNet and subnet for nodes; pod CIDR (overlay); service CIDR; DNS service IP.
- [ ] **No overlap** with VNets that are or will be peered, VPN, on-prem, and no overlap between clusters that will connect to each other.
- [ ] Network plugin: Azure CNI Overlay is the default choice for new clusters; it avoids running out of subnet IPs. The Azure-managed Cilium dataplane is **CONTEXT** (when you need advanced NetworkPolicy / network observability).
- [ ] Outbound: Load Balancer (default), or NAT Gateway (many outbound connections, fixed IP), or User Defined Routing through a firewall (enterprise).

**API server**

- [ ] Private cluster, or public with an IP limit (authorized IP ranges).
- [ ] If private: how do operators / CI / jump servers reach it (VPN, peering, jump host in the VNet)?

**Identity & access**

- [ ] Entra ID integration + Azure RBAC for Kubernetes; **turn off local accounts** on production.
- [ ] Which Entra groups get which permissions.
- [ ] A break-glass path for when Entra has problems.
- [ ] Turn on OIDC issuer + Workload Identity. Pods use federated credentials, not service principal secrets.

**Node pools**

- [ ] A separate system pool with taint `CriticalAddonsOnly` (only for system add-ons), at least 2–3 nodes, spread across zones.
- [ ] User pool for workloads; separate pools for stateful / GPU if needed.
- [ ] VM SKU, autoscaler min / max, max surge during upgrades, OS disk (ephemeral if the SKU supports it).
- [ ] **CONTEXT** Spot pool for workloads that can handle interruptions.

**Upgrades**

- [ ] Auto-upgrade channel for the cluster and for the node OS image; a maintenance window in low-traffic hours.
- [ ] Who watches the notices about AKS versions that will lose support.

**Storage**

- [ ] The default Azure Disk StorageClass uses `WaitForFirstConsumer` (correct zone).
- [ ] Important data uses a StorageClass with `reclaimPolicy: Retain` (you usually need to create it).

**Observability**

- [ ] Managed Prometheus + Managed Grafana, or self-hosted (see `playbook-monitoring-stack`).
- [ ] Container Insights / diagnostic logs: choose only the tables / namespaces you need. Log Analytics charges per GB.

**Security & policy**

- [ ] Azure Policy add-on (baseline pod security).
- [ ] Images only from allowed ACRs (ACR attached to the cluster with a managed identity, not the ACR admin user).
- [ ] Key Vault + ESO (or Secrets Store CSI driver).
- [ ] Defender for Containers: **CONTEXT**.

**Cost**

- [ ] `infracost` for Terraform; also estimate Log Analytics, egress, public IPs, disks.
- [ ] Budget + alerts.

**GitOps / add-ons**

- [ ] How Argo CD or Flux (AKS extension) is installed.
- [ ] Which add-ons Terraform manages and which GitOps manages. Make the boundary clear so two tools never manage the same thing.

## 2. Common risks

| Risk | How to avoid it |
|---|---|
| CIDR overlap found after peering / VPN | A CIDR plan table in the plan, reviewed before apply |
| An attribute change makes Terraform **replace the whole cluster / node pool** | Read the plan carefully: any `-/+` on a cluster / node pool means stop; many node pool attributes are immutable |
| Private cluster, but CI / jump servers have no way in | Design the access path first; test with `kubectl get nodes` from the right machine |
| Local accounts turned off before the Entra admin group works | Assign and test Entra permissions first; have break-glass |
| Log Analytics bill jumps | Selective data collection rules; watch ingest in the first week |
| Auto-upgrade breaks workloads without PDB / probes | PDB + probes for important workloads; maintenance window |

## 3. Verification checklist

| Check | Suggested command | Expected |
|---|---|---|
| Cluster | `az aks show -g <rg> -n <name> --query "{state:provisioningState,power:powerState.code,k8s:currentKubernetesVersion}"` | `Succeeded` · `Running` · correct version |
| Nodes | `kubectl get nodes -o wide` | Ready; correct number of nodes / zones / pools |
| System pool | `kubectl get nodes -l kubernetes.azure.com/mode=system` + check taints | Has taint `CriticalAddonsOnly` |
| Identity | `kubectl auth can-i` with the Entra groups; local accounts turned off (prod) | Permissions match the design |
| Workload Identity | A test pod uses a ServiceAccount with a federated credential and reads Key Vault | Works, no secret needed |
| Network | A test pod resolves internal / external DNS, reaches the needed egress endpoints | Works; outbound IP matches the design |
| Storage | Create a test PVC on each StorageClass, mount it in a pod, write / read, delete | Bound in the right zone; data can be read back |
| Monitoring | Cluster metrics / logs show up in the observability system | New data arrives |
| Terraform | `terraform plan` right after apply | `No changes` |

## 4. Docs to leave behind

- A CIDR plan table (ADR or runbook).
- A cluster runbook: access (VPN / jump host), upgrade, scaling node pools, rotating credentials, break-glass.
- A concept note on AKS networking (CNI Overlay, outbound) if the user is new to it.
