# Plan: raise prod replicas from 3 to 4

- **Risk level:** L1 — local files only, fully reversible
- **Environment & target:** terraform `terraform/envs/prod` (local state) · ansible `inventories/prod`
- **Standards & playbooks used:** rule terraform.md, rule ansible.md
- **Related versions:** Terraform 1.14.7, Ansible core 2.17
- **Status:** Approved (2026-11-01 09:10 UTC, approved by the user)

## 1. Goal & scope

- **Goal (measurable):** `jq .replicas out/prod.json` → `4`
- **In scope:** prod Terraform root, prod Ansible inventory
- **Out of scope:** dev, Helm chart

## 2. Current state (summary)

prod has `replicas = 3`; `out/prod.json` does not exist yet.

## 3. Design / options

- **Chosen option and why:** change the tfvars value and apply; then refresh the motd with Ansible.

## 4. Prerequisites

- [x] No backup needed (local generated file).

## 5. Steps

- [x] Step 1: Set replicas to 4 in the prod tfvars — ✅ 2026-11-01 09:15 UTC · tfvars says replicas = 4
  - **Executed by:** AI
  - **Context / namespace:** `terraform/envs/prod`
  - **Action:** edit `terraform/envs/prod/terraform.tfvars`: `replicas = 4`
  - **Blast radius:** prod config file only
  - **Reversible?:** yes — edit back to 3
  - **Rollback:** set `replicas = 3`
  - **Verify:** `grep replicas terraform/envs/prod/terraform.tfvars` → expected `replicas = 4`
  - **Stop condition:** the file has other changes
  - **Estimated time / downtime:** 1 min / none
- [ ] Step 2: Apply Terraform for prod
  - **Executed by:** AI
  - **Context / namespace:** `terraform/envs/prod`
  - **Action:** `make apply e=prod` (review the plan output first)
  - **Blast radius:** `out/prod.json`, prod state file
  - **Reversible?:** yes — apply with replicas = 3
  - **Rollback:** set `replicas = 3`, `make apply e=prod`
  - **Verify:** `jq .replicas out/prod.json` → expected `4`
  - **Stop condition:** the plan shows anything other than `out/prod.json` and the random name being created
  - **Estimated time / downtime:** 2 min / none
- [ ] Step 3: Refresh the prod motd with Ansible
  - **Executed by:** AI
  - **Context / namespace:** `ansible/inventories/prod`
  - **Action:** `cd ansible && ansible-playbook -i inventories/prod/hosts.ini playbooks/site.yml`
  - **Blast radius:** `/tmp/shop-infra-motd-prod`
  - **Reversible?:** yes — delete the file
  - **Rollback:** `rm /tmp/shop-infra-motd-prod`
  - **Verify:** `cat /tmp/shop-infra-motd-prod` → expected `shop-infra prod`
  - **Stop condition:** the check run shows changes to other files
  - **Estimated time / downtime:** 1 min / none

## 6. Point of no return

None.

## 7. Overall rollback

Set `replicas = 3`, apply, rerun the playbook.

## 8. Completion criteria (checklist for infra-verifier)

| # | Check | Command | Expected |
|---|---|---|---|
| 1 | replicas | `jq .replicas out/prod.json` | `4` |
| 2 | motd | `cat /tmp/shop-infra-motd-prod` | `shop-infra prod` |

## 9. Risks

| Risk | Likelihood | Impact | Mitigation | Detected by |
|---|---|---|---|---|
| wrong env applied | low | low | `e=prod` checked in the 4 lines | plan output |

## 10. Timing & communication

- Maintenance window: none needed

## 11. Open questions

## Changes during execution

<!-- Every change after GATE 1, newest last. Ticked steps are never edited. -->

| Time (UTC) | Change | Reason | Steps affected | Re-reviewed | Confirmed by user |
|---|---|---|---|---|---|
