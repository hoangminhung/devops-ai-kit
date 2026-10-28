# <Project name>

<!-- Copy this file to the repo root as CLAUDE.md (or .claude/CLAUDE.md) and fill it in.
     Write only what is SPECIFIC to this project. General rules are already in ~/.claude/rules/devops-kit/.
     Keep this file under ~100 lines. -->

## Purpose

<1–3 lines: what infrastructure this repo manages, and for which system.>

## Environment registry

The AI must check this table before it touches infrastructure.

| Env | Kube context (AI) | Main namespace | Cloud scope | Terraform dir / workspace | Who makes changes |
|---|---|---|---|---|---|
| dev | `kind-dev` | `app` | sub: `<dev-sub>` | `envs/dev` / `default` | AI runs it after preview + your confirmation |
| staging | `aks-stg-weu` | `app` | sub: `<stg-sub>` | `envs/staging` | AI runs it after preview + your confirmation |
| prod | `aks-prod-weu-ro` (read-only) | `app` | sub: `<prod-sub>` | `envs/prod` | Only through a GitOps PR, or you run it yourself |

## Stack & versions

<Fill in by hand; the AI will check again with commands.>

- Kubernetes: <e.g. AKS 1.3x>
- GitOps: <Argo CD x.y, repo `<...>`, tracked branch `<...>`>
- Storage: <Longhorn 1.x / Azure Disk CSI>
- Monitoring: <kube-prometheus-stack x, Loki x, Alloy x>
- Database: <PGO 5.x, PostgreSQL 16>

## Repo layout

<Which folder holds what. If manifests/values live in folders that do not match the `paths` of the kit's rules, add a project-level rule in `.claude/rules/` with matching `paths`.>

## Project conventions (override / add to the general standards)

- <e.g. node pools are named `np-<purpose>-<nn>`>
- <e.g. use Sealed Secrets instead of ESO because ...>

## Common commands

```bash
# <build / lint / plan commands specific to this repo>
```

## Documentation

- Language: <keep the kit default (`--lang` at install time), or write your own choice here>
- Concept notes are stored in: <e.g. ~/kb/concepts/ (personal KB) or docs/concepts/>
- Runbooks: `docs/runbooks/` · ADR: `docs/adr/` · Change records: `docs/changes/`
