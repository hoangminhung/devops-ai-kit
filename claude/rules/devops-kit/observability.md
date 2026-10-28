---
paths:
  - "**/*.alloy"
  - "**/alloy/**"
  - "**/prometheus/**"
  - "**/alertmanager/**"
  - "**/loki/**"
  - "**/grafana/**"
  - "**/dashboards/**"
  - "**/monitoring/**"
  - "**/observability/**"
  - "**/*rules*.{yaml,yml}"
  - "**/*alert*.{yaml,yml}"
---

# Observability standards (metrics, logs, alerts)

<!-- devops-ai-kit · Last reviewed: 2026-10-28 · To deploy the whole stack: see skill `playbook-monitoring-stack`. -->

## Metrics (Prometheus)

- **SHOULD** Use Prometheus Operator CRDs (`ServiceMonitor`, `PodMonitor`, `PrometheusRule`, `ScrapeConfig`) instead of editing raw scrape config.
- **MUST** Do not use high-cardinality values as labels: `user_id`, IP, `request_id`, timestamp, URL path with IDs. Good labels: `env`, `cluster`, `namespace`, `service`, `status_code_class`.
- **MUST** Set `retention` **and** `retentionSize` for Prometheus, so the TSDB does not fill the PVC.
- **SHOULD** Use recording rules for heavy queries that dashboards / alerts use often.

## Logs (Loki + Grafana Alloy)

- **MUST** The collector is **Grafana Alloy**. Do not use Grafana Agent (EOL 2025-11-01) or Promtail (EOL 2026-03-02) for new setups. If a system still runs them, note the risk and suggest a migration (`alloy convert` helps convert the config).
- **MUST** Loki labels are minimal and low-cardinality: `cluster`, `namespace`, `app` / `container`, `job`. High-cardinality fields (`trace_id`, `user_id`, `request_id`) stay in the log content or structured metadata, never as labels.
- **SHOULD** Apps write JSON logs to stdout / stderr. Query them with `| json` in LogQL.
- **CONTEXT** Alloy can read Kubernetes logs in two ways:
  - Through the Kubernetes API (`loki.source.kubernetes`): simpler, but adds load on the API server.
  - Reading `/var/log/pods` files from a DaemonSet: better for big clusters.

  Choose on purpose and write down why.
- Alloy config (`.alloy`): check the syntax with `alloy fmt`. See the state of each component in the Alloy UI (HTTP, default port 12345).

## Alerting

- **MUST** Every alert has a `severity` label and `summary`, `description`, `runbook_url` annotations. The linked runbook must exist.
- **SHOULD** Alerts for user-facing services are based on SLOs (burn rate). For infrastructure, threshold alerts are OK when they match a real impact: disk almost full (`predict_linear`), certificate about to expire, backup failed, replication lag. Avoid alerts that fire only because CPU is high.
- **SHOULD** Use a sensible `for:` to avoid flapping alerts.
- **MUST** Have a "heartbeat" alert (Watchdog) sent to an external dead man's switch service, so someone knows when the alerting system itself is down.

## Dashboards

- **SHOULD** Dashboards are code (JSON in Git, provisioned by a ConfigMap sidecar or Grafana provisioning). If you edit in the production UI, export the change back to Git.

## Verification gates

```bash
promtool check rules <rules.yaml>        # PrometheusRule (CRD) file: extract the .spec part before the check
promtool test rules <tests.yaml>         # if there are unit tests for alerts
amtool check-config <alertmanager.yaml>
alloy fmt <file>.alloy                   # check Alloy config syntax
```
