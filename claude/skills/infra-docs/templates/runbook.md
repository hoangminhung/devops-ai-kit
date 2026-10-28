# Runbook: <component / service name>

- **Updated:** <YYYY-MM-DD> · **Applies to:** <version>
- **Owner:** <team / person> · **Criticality:** <critical / high / normal>
- **RTO / RPO:** <value> (see ADR <link> if any)
- **Architecture:** <link to concept note / diagram>

## 1. Overview

<What the component does, what it depends on, what depends on it.>

| Environment | Context / namespace | Endpoint | Config repo |
|---|---|---|---|

## 2. Quick health check

```bash
# Run in context: <context>
kubectl -n <ns> get pods -l <selector>
# <other check commands, with the expected result>
```

Expected: <what a healthy state looks like>

## 3. Alert → action

| Alert | Meaning | First check | Fix | When to escalate |
|---|---|---|---|---|

## 4. Common operations

### <Operation, e.g. Scale / Restart / Rotate a secret>
> ⚠️ Mutating command — run in context `<...>`, requires <condition>.
```bash
<command>
```
Verify: `<command>` → expected `<...>`

## 5. Backup & restore

- **Backup:** <method, schedule, location, retention>
- **Last restore drill:** <date, result, link>
- **Restore steps:**
  1. <step>

## 6. Upgrade

<Upgrade path, steps, notes on CRDs / breaking changes, link to the change record of the last upgrade>

## 7. Troubleshooting

| Symptom | Possible cause | Diagnosis | Fix |
|---|---|---|---|

## 8. Escalation & contacts

## 9. Change history

| Date | Change | Change record |
|---|---|---|
