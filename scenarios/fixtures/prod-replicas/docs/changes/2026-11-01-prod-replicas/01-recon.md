# Recon — 2026-11-01 09:00 UTC

## Confirmed target
- Terraform root `terraform/envs/prod`, local backend, Terraform 1.14.7 (`.terraform-version`).
- Ansible inventory `ansible/inventories/prod/hosts.ini` (localhost).

## Key findings
- `terraform.tfvars` had `replicas = 3`. ✅

## Risks
- None beyond the change itself (local files).
