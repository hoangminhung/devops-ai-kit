Status: Phase 7 — Execute (Step 1 done) · Updated: 2026-11-01 09:20 UTC
Mode: interactive

# Brief: raise prod replicas from 3 to 4

- **Request:** "Raise the web replicas on prod from 3 to 4 and roll it out."
- **Goal:** `out/prod.json` says `"replicas": 4`, and the prod motd is refreshed.
- **In scope:** `terraform/envs/prod`, `ansible` prod inventory. **Out of scope:** dev, the Helm chart.
- **Target environment:** prod — `terraform/envs/prod` (local state), `ansible/inventories/prod`.
- **Success criteria:** `jq .replicas out/prod.json` → `4`; `/tmp/shop-infra-motd-prod` exists.
- **Allowed downtime:** none needed (config file only).
- **Rollback expectation:** set `replicas = 3` and apply again; under 5 minutes; the user decides.
- **Risk level:** L1 — local files only, fully reversible.

## Requirement changes

<none yet>
