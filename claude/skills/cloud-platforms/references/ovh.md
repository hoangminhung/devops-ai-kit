# OVHcloud

<!-- Last reviewed: 2026-10-28 -->

## Baseline
- **SHOULD** Turn on vRack: traffic between servers goes through a private L2 network. Do not open backend ports on the Public IP.
- **SHOULD** Split VLANs by purpose: Management, Data / Storage, Kubernetes CNI.
- **SHOULD** Firewall on the public interface (OVH Network Firewall and / or the OS firewall).

## Production
- **SHOULD** Hardware RAID (RAID 1 for the OS, RAID 10 for data) on enterprise NVMe. Monitor the controller with a StorCLI / MegaCLI exporter to find failing disks early.
- **CONTEXT** Tune Anti-DDoS (VAC) by service type (web, game, custom UDP / WebSocket).
- **MUST** Offsite backup outside the datacenter of the main server.
