# Azure

<!-- Last reviewed: 2026-10-28 -->

## Baseline
- **MUST** Terraform state in the `azurerm` backend, with Entra ID auth (`use_azuread_auth = true`). The state storage account has versioning + soft delete, and no public blob access.
- **MUST** Workloads on Azure use Managed Identity / Workload Identity. Do not use service principal secrets when there is another option.
- **MUST** Key Vault uses RBAC authorization, with soft-delete and purge protection turned on.
- **SHOULD** PaaS that holds data (Azure SQL / PostgreSQL Flexible Server, Storage Account, Key Vault): Private Endpoint + Private DNS Zone, public network access turned off.
- **SHOULD** NSGs are attached at subnet level. Do not open SSH/RDP to the Internet (use Bastion / VPN / JIT).
- **SHOULD** Budget + alerts at subscription or resource group level.

## Production
- **SHOULD** Use Availability Zones for important parts (AKS node pools, databases, LB).
- **SHOULD** Diagnostic settings send logs to Log Analytics, but **choose carefully**: Log Analytics ingestion is often the biggest surprise cost (see `finops`).
- **SHOULD** Azure Backup / app-level backup with tested restores (see `disaster-recovery`).
- **CONTEXT** Microsoft Defender for Cloud, depending on security needs and budget.
- **AKS:** see skill `playbook-aks` (CNI Overlay, Workload Identity, Entra ID + Azure RBAC, separate system node pool).

## Enterprise landing zone (only with many teams / subscriptions)
- Management Group hierarchy: `Root` → `Platform` (Identity, Management, Connectivity) → `Landing Zones` (Corp, Online) → subscriptions per workload.
- Hub-spoke network (Azure Firewall, VPN / ExpressRoute Gateway in the hub; spokes peered to the hub), or Virtual WAN with many regions / many branches.
- Azure Policy assigned at Management Group level: required tags, allowed regions / SKUs, no public IPs in the Corp landing zone.
- Subscription vending (create standard subscriptions with IaC) when there are many subscriptions.
