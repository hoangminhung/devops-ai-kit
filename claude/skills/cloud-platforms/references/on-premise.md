# On-premise / bare metal

<!-- Last reviewed: 2026-10-28 -->

## Baseline
- **MUST** The hardware management network (IPMI / iDRAC / iLO) is on a separate Out-of-Band range that cannot be reached from the production network.
- **SHOULD** Install the OS automatically (PXE + cloud-init, MAAS, Tinkerbell) instead of by hand.
- **SHOULD** Monitor hardware with the Prometheus IPMI exporter and SNMP exporter (switches, PDUs, UPS).

## Production
- **CONTEXT** Spine-Leaf architecture (25 GbE / 100 GbE) when the number of racks is big enough.
- **MUST** Turn on Jumbo Frames (MTU 9000) for the storage / CNI network only after you **confirm the MTU is the same end to end** (NIC, bond, VLAN, switch, overlay). Mismatched MTU is a classic cause of random errors that are hard to troubleshoot. Verify with `ping -M do -s 8972 <ip>`.
- **CONTEXT** Announce LoadBalancer IPs with BGP to the ToR switch (MetalLB BGP mode or Cilium BGP Control Plane). Small clusters can use L2 mode.
- **Distributed storage:**
  - Rook-Ceph: separate public network and cluster network; replication 3; dedicated SSD / NVMe for OSDs and BlueStore DB / WAL.
  - **CONTEXT** Longhorn is a lighter choice than Ceph for small and medium clusters (see skill `k8s-storage`).
- **MUST** Have backups outside the site (cloud object storage or a second site).
