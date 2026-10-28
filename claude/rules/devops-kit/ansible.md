---
paths:
  - "**/roles/**"
  - "**/playbooks/**"
  - "**/inventory/**"
  - "**/inventories/**"
  - "**/group_vars/**"
  - "**/host_vars/**"
  - "**/molecule/**"
  - "**/ansible.cfg"
  - "**/site.yml"
  - "**/site.yaml"
---

# Ansible standards

<!-- devops-ai-kit · Last reviewed: 2026-10-28 -->

## Idempotency

- **MUST** When a playbook runs a second time on the same host, it must give `changed=0`.
- **MUST** If a module exists, use the module, not `shell` / `command`.
- **MUST** When you must use `shell` / `command`: set `creates` / `removes`, or a specific `changed_when` and `failed_when`.
- **SHOULD** Use the full module name (FQCN), e.g. `ansible.builtin.template`.

## Structure

- **SHOULD** Put reusable logic in a role (`tasks/`, `handlers/`, `defaults/`, `templates/`, `meta/`).
- **CONTEXT** A short one-time playbook (a few tasks) can be flat, without a role.
- **MUST** Put values that change per environment in `group_vars/` / `host_vars/`, not in the role. Role defaults go in `defaults/main.yml`.
- **MUST** Restart / reload services through `handlers` when the config changes. Do not write a direct restart task.

## Safe runs

- **MUST** Tasks that handle secrets have `no_log: true`. Store secrets with ansible-vault or SOPS. No plaintext secrets in the repo.
- **MUST** Always limit the scope with `--limit` for test runs. Do not run a mutating playbook on all production hosts until the user confirms.
- **SHOULD** Production uses `serial` (rolling) and `max_fail_percentage`, so one failure does not spread to the whole fleet.
- Note: `--check` is not accurate for tasks that depend on the result of an earlier task, and `shell` / `command` tasks are skipped in check mode. Say this clearly when you report check results.

## Verification gates

```bash
ansible-lint <playbook-or-dir>
ansible-playbook <playbook> --syntax-check
ansible-playbook <playbook> --check --diff --limit <test-host>
# Idempotency: run for real a 2nd time on the test host → expect changed=0
# Or use Molecule (`molecule test` has an idempotence step) if the role has a scenario
```
