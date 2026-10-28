---
name: cloud-platforms
description: Design standards for cloud and on-prem infrastructure — Azure, AWS, GCP, Hetzner, OVHcloud and bare-metal data centers — organised by tier (baseline, production, enterprise landing zone) so recommendations match the real size of the project. Use whenever designing, provisioning or reviewing cloud networking, identity, managed Kubernetes (AKS/EKS/GKE), landing zones, VPC/VNet layouts or data-center infrastructure, even if the user only names a single provider service.
when_to_use: Use when designing, deploying or reviewing infrastructure on Azure, AWS, GCP, Hetzner, OVH or on-premise — networking, identity, AKS/EKS/GKE, landing zone, VPC/VNet. Vietnamese triggers — "thiết kế, triển khai hoặc review hạ tầng trên Azure, AWS, GCP, Hetzner, OVH hoặc on-premise", "mạng, định danh, AKS/EKS/GKE, landing zone, VPC/VNet".
---

# Cloud & on-premise infrastructure standards

<!-- devops-ai-kit · Last reviewed: 2026-10-28 -->

## Choose the right tier before you apply standards

Suggesting an enterprise architecture for a small project is over-engineering: it costs money, it costs operations work, and the user will then ignore even the good advice. Always decide the tier first, and write the chosen tier in the plan / ADR.

| Tier | When | Apply |
|---|---|---|
| **Baseline** | Every project, including dev / PoC used for more than a few days | The "Baseline" part of each provider |
| **Production** | Real users, real data, an uptime commitment | Baseline + "Production" |
| **Enterprise landing zone** | Many teams / many subscriptions-accounts, compliance needs, a platform team | All three tiers |

If the tier is not clear, ask the user. Do not pick Enterprise by default.

## Common rules for every provider

- **MUST** Create every resource with IaC (Terraform / OpenTofu). Manual console work is only for troubleshooting. If you must create something by hand, write it down and import it into IaC later.
- **MUST** Identity does not use long-lived static keys: CI uses OIDC federation, workloads use managed / workload identity. If a static key cannot be avoided, it has an expiry date and is rotated.
- **MUST** Standard tags / labels (`Environment`, `Owner`, `Project`, `ManagedBy`) to track cost and ownership.
- **SHOULD** Services that hold data (database, storage, key vault) are not public. Access them through a private endpoint / private link / private network.
- **SHOULD** Encryption at rest is on by default (usually built in). Customer-managed keys (CMK) are **CONTEXT**: use them when compliance requires it.
- **SHOULD** Set a budget and cost alerts from day one (see skill `finops`).
- **SHOULD** Plan CIDRs once for all environments. Avoid overlap with networks you will peer / VPN / connect on-prem. Changing a CIDR later usually means rebuilding.

## Provider references

Read the matching file in `references/` when you work with that provider:

- Azure (including AKS): `references/azure.md`. To build AKS, also read skill `playbook-aks`.
- AWS (including EKS): `references/aws.md`
- GCP (including GKE): `references/gcp.md`
- Hetzner: `references/hetzner.md`
- OVHcloud: `references/ovh.md`
- On-premise / bare metal: `references/on-premise.md`

The reference files describe the **design direction**. Terraform attribute names and specific features change between provider versions: check the provider docs for the exact version before you write code.
