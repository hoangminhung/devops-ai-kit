# Hetzner (Cloud + Dedicated)

<!-- Last reviewed: 2026-10-28 -->

## Baseline
- **MUST** Hetzner Cloud Firewall blocks all inbound traffic by default. Open only 80/443 on the Load Balancer. SSH (22) only through VPN / bastion / IP allowlist.
- **SHOULD** Internal traffic goes through a Hetzner Cloud Network (private network), e.g. range `10.0.0.0/16` — check that it does not overlap with VPN / on-prem networks.
- **SHOULD** Hetzner Load Balancer with TLS (Let's Encrypt managed certificate), or terminate TLS in the cluster with cert-manager.

## Production
- **SHOULD** Connect Dedicated Servers to Cloud Servers through a vSwitch (tagged VLAN) attached to the Cloud Network.
- **CONTEXT** Apps that need high IOPS run on the local NVMe of a dedicated server (Local Path Provisioner / `strict-local`), **only when** the app replicates its own data (e.g. PostgreSQL with replicas through an operator). A local volume is lost together with its node.
- **SHOULD** Kubernetes: use the hcloud cloud-controller-manager and CSI driver for Cloud Volumes / LB.
- **MUST** Offsite backup: Hetzner Storage Box (Borg / Restic) or external object storage (Cloudflare R2, S3). Do not keep backups only in the same project / same datacenter.
