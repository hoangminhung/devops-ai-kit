---
paths:
  - "**/*.tf"
  - "**/*.tfvars"
  - "**/*.tftest.hcl"
  - "**/terragrunt.hcl"
  - "**/.terraform.lock.hcl"
---

# Terraform / OpenTofu standards

<!-- devops-ai-kit · Last reviewed: 2026-10-28 · Loaded when Claude reads/edits a file that matches `paths`. -->

## State & blast radius

- **MUST** Every shared environment uses a remote backend with locking. No local state.
  - AWS S3: `use_lockfile = true` (Terraform ≥ 1.10). DynamoDB locking is deprecated; do not use it in new setups. Old setups may turn on both while they move over.
  - Azure: `azurerm` backend (locks with a blob lease, built in). Prefer `use_azuread_auth = true` over access keys. Turn on versioning and soft delete on the storage account.
  - GCP: `gcs` backend (locking built in). Turn on bucket versioning.
- **SHOULD** Split state by environment and by resource lifecycle (network / cluster / data / app) to keep the blast radius small. If the repo already splits state another way, keep it and add a note to the recommendations.
- **MUST** Do not change state (`state rm/mv/push`, `import`, `force-unlock`) until there is a plan, the user has made their own copy of the state, and the user has confirmed.

## Modules & code

- **MUST** Pin versions: `required_version` and each provider in `versions.tf` (use `~>`). Commit `.terraform.lock.hcl`.
- **MUST** Variables have `type` and `description`. Outputs have `description`. Outputs with a token / password / key have `sensitive = true`.
- **SHOULD** Add `validation` to variables that are easy to get wrong (CIDR, names that follow a convention, environment enums). Not every variable needs it.
- **SHOULD** A module has at least `main.tf`, `variables.tf`, `outputs.tf`, `versions.tf`.
- **SHOULD** Standard tags/labels come from one shared variable (`Environment`, `ManagedBy`, `Owner`, `Project`). Use the provider's `default_tags` when it has them.
- **MUST** Do not hardcode credentials. CI uses OIDC / workload identity federation.
- **SHOULD** Production resources that hold data (database, storage, key vault, disk) have `lifecycle { prevent_destroy = true }`.
- **CONTEXT** If the project uses OpenTofu, use the matching `tofu` commands. If the state holds sensitive data, think about OpenTofu state encryption.

## Plan review (before every apply)

1. `terraform plan -out=tfplan`, then `terraform show -no-color tfplan`.
2. Tell the user the `Plan: X to add, Y to change, Z to destroy` line and **list every resource** that will be `destroy`ed or `-/+` (forces replacement). Replacing a database, disk, static IP, cluster or node pool is usually an incident: stop and ask.
3. List unexpected changes (drift) separately from the changes of the task.
4. `tfplan` contains sensitive data. Do not commit it. Delete it after use.

## Verification gates

```bash
terraform fmt -check -recursive
terraform validate
tflint --init && tflint --recursive
trivy config .           # or: checkov -d .
infracost diff ...       # when the change affects cost (see skill finops)
```

If a gate is not installed on the machine, tell the user. Do not skip it silently.
