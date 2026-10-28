---
name: playbook-monitoring-stack
description: Playbook for deploying, upgrading or extending a self-hosted Kubernetes observability stack — kube-prometheus-stack (Prometheus Operator, Prometheus, Alertmanager, Grafana), Loki, Grafana Alloy as the collector, persistent storage on Longhorn or cloud disks, retention and capacity sizing, alert routing, dashboards as code, and migrating off Promtail/Grafana Agent. Use whenever the task is to build, change, scale, upgrade or troubleshoot monitoring, logging or alerting infrastructure, even if only one component (e.g. just Loki or just Alloy) is mentioned.
when_to_use: Use when building, upgrading, extending or debugging a monitoring / logging / alerting system (Prometheus, Grafana, Loki, Alloy, Alertmanager), even if only one component is mentioned. Vietnamese triggers — "xây dựng, nâng cấp, mở rộng hoặc debug hệ thống monitoring / logging / alerting", "kể cả khi chỉ nhắc một thành phần".
---

# Playbook: Observability stack on Kubernetes

<!-- devops-ai-kit · Last reviewed: 2026-10-28 · Detailed config standards: rules `observability.md`, `helm.md`; storage: skill `k8s-storage`. -->

This playbook is a **checklist that the plan must answer**. It does not replace the official docs: field names, deployment modes and defaults change between chart versions, so ask `infra-researcher` to check them for the version you use.

## 1. Design questions (the plan must answer each one)

**Scope & placement**

- [ ] What to collect: infrastructure metrics, app metrics, logs, (traces?), from how many clusters?
- [ ] Where the stack runs: inside the monitored cluster, or in a separate monitoring cluster? If the cluster dies, who sends the alert?

**Components & versions**

- [ ] Which charts and versions (pin exact versions):
  - kube-prometheus-stack;
  - Loki (chart `grafana/loki`);
  - Alloy (chart `grafana/alloy`, or the combined chart `grafana/k8s-monitoring`);
  - Grafana (bundled with kube-prometheus-stack, or separate).
- [ ] Does the old system have Promtail / Grafana Agent? Both are EOL, so add the move to Alloy to the scope (`alloy convert` helps convert the config) or record it as a follow-up.

**Loki**

- [ ] Deployment mode: monolithic / single-binary for small log volume; other modes for bigger scale. Choose based on the Loki docs for the **exact version**, because the recommended mode has changed between versions.
- [ ] Loki storage: filesystem on a PVC is only for single-binary. To scale you need object storage (Azure Blob, S3, GCS or self-hosted S3-compatible). For a self-hosted option, check the product's maintenance / license status before you choose it.

**Alloy**

- [ ] Collect logs through the Kubernetes API (`loki.source.kubernetes`), or read `/var/log/pods` files with a DaemonSet. Big clusters should prefer file-based, so the API server does not get extra load.
- [ ] Does Alloy also collect metrics (taking over part of the scraping), or only logs?

**Capacity**

- [ ] Retention: how many days for metrics, how many days for logs. Set both `retention` **and** `retentionSize` for Prometheus.
- [ ] Estimate the size:
  - Prometheus ≈ `retention_seconds × samples/second × 1–2 bytes/sample`;
  - Loki ≈ `GB of logs/day × days ÷ compression ratio`;
  - then multiply by the replication factor of the app **and** of Longhorn.

  Write the calculation in the plan.
- [ ] Longhorn: which StorageClass for Prometheus / Loki / Alertmanager / Grafana. For components that already run HA (Prometheus with 2 replicas, Loki replication), think about a lower `numberOfReplicas` (see `k8s-storage`).

**Access & security**

- [ ] Grafana: SSO / OIDC; the admin password comes from a Secret through ESO (not in values).
- [ ] Prometheus / Alertmanager UI are not public.
- [ ] Do you need tenants / permissions per team?

**Alerting**

- [ ] Alertmanager receivers: Slack / Teams / email / Telegram / PagerDuty. Webhook credentials come through ESO.
- [ ] Routing by `severity`, `team`.
- [ ] Watchdog goes to an external dead man's switch.

**Content**

- [ ] Dashboards and alert rules are code: which folder in Git, and how they are provisioned (sidecar label `grafana_dashboard`, PrometheusRule).

**Deployment through GitOps**

- [ ] Argo CD with `ServerSideApply=true` for the large CRDs of kube-prometheus-stack.
- [ ] Sync waves: CRDs / operator → stack → dashboards / rules.

## 2. Common risks

| Risk | How to avoid it |
|---|---|
| Prometheus PVC is full → Prometheus crash loop | `retentionSize` < PVC size (keep ~15–20% free); `predict_linear` alert on the disk |
| kube-prometheus-stack chart upgraded but CRDs are old | Read the upgrade notes for each major; apply CRDs first as the notes say |
| Cardinality explosion makes Prometheus run out of RAM | Review the labels of new ServiceMonitors; watch `prometheus_tsdb_head_series` |
| Loki rejects logs (rate limit / stream limit) | Set `limits_config` from real volume; keep labels minimal |
| Alerts reach nobody and nobody knows | Watchdog + dead man's switch; test receivers after every change |
| The monitoring stack dies together with the monitored cluster | Heartbeat to an outside service; think about a separate monitoring cluster when there are many clusters |

## 3. Suggested deployment order

1. Namespace (+ PSA labels), StorageClass (if a new one is needed), secrets through ESO.
2. Prometheus Operator CRDs, then kube-prometheus-stack.
3. Loki, then Alloy (logs into Loki).
4. Grafana datasources (Prometheus, Loki), dashboards, PrometheusRules.
5. Alertmanager receivers, then send a test alert.
6. For an old stack (Promtail / Agent): run both side by side, compare, then remove the old one.

## 4. Verification checklist (put it in section 8 of the plan)

| Check | Suggested command | Expected |
|---|---|---|
| Pods healthy | `kubectl -n <ns> get pods` | All Running/Ready, restarts not going up |
| PVC | `kubectl -n <ns> get pvc` | Bound, correct StorageClass and size |
| Longhorn volumes | `kubectl -n longhorn-system get volumes.longhorn.io` | robustness `healthy` |
| Scrape targets | Query `count(up == 0)` through the Prometheus API / Grafana | 0, or only targets known to be not needed |
| Rules load | Query `count(ALERTS)` + check the Rules page / `promtool` before | No evaluation errors |
| Logs reach Loki | Query `{namespace="<ns>"}` for the last 5 minutes | New log lines |
| Alerts reach receivers | Send a test alert (`amtool alert add` or wait for Watchdog) | Message arrives in the right channel |
| Dead man's switch | Check the heartbeat service | It is receiving signals |
| Retention | Check the running args / config | Same values as in the plan |
| Grafana | Log in with SSO, datasource "Test" | Works |

## 5. Docs to leave behind

- A runbook for each main component (Prometheus, Loki, Alloy, Alertmanager): alert → action, how to add capacity, how to upgrade.
- A concept note "How a log line / a metric travels from a pod to Grafana" for newcomers.
- An ADR if there are architecture choices (Loki mode, where the stack runs, object storage).
