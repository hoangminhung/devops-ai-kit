---
paths:
  - "**/argocd/**"
  - "**/argo-cd/**"
  - "**/applicationsets/**"
  - "**/*appset*.{yaml,yml}"
  - "**/*application*.{yaml,yml}"
---

# GitOps standards with Argo CD

<!-- devops-ai-kit · Last reviewed: 2026-10-28 -->

## Repos & app management

- **SHOULD** Keep the app source code repo separate from the deployment config repo (manifests / values).
- **CONTEXT** Many clusters, or many apps with the same shape: use `ApplicationSet` (Git / cluster / matrix generator). For a few apps, single `Application`s are enough.
- **MUST** Every change to a resource managed by Argo CD goes through Git. A direct `kubectl apply` / `edit` will be overwritten by selfHeal or will cause drift.
- **MUST** A `git push` / merge into a branch that Argo CD watches **is a deployment**. Treat it as a mutating command: it needs a preview and confirmation.

## Sync policy

- **SHOULD** Dev / staging: `automated: { prune: true, selfHeal: true }`.
- **CONTEXT** Production: automated sync is OK when Git changes must go through PR review. For core stateful parts (database, storage, operator, CRD), use manual sync or turn off prune.
- **MUST** Production resources that hold data (PVC, database cluster CR) have `argocd.argoproj.io/sync-options: Prune=false`, so deleting them from Git by mistake does not lose data. Think about adding `Delete=false` to keep the resource when the Application is deleted.
- **SHOULD** `CreateNamespace=false` when the namespace is defined in Git (with PSA labels and quota).
- **CONTEXT** `ServerSideApply=true` for charts with large CRDs (e.g. kube-prometheus-stack) that go over the annotation size limit of client-side apply.
- **CONTEXT** `ApplyOutOfSyncOnly=true` for very large Applications, to reduce load.
- **SHOULD** `ignoreDifferences` for fields that controllers change by themselves (`replicas` with HPA, webhook `caBundle`), to avoid false OutOfSync.

## Deployment order

- **SHOULD** Sync waves (`argocd.argoproj.io/sync-wave`). Negative numbers are allowed:
  - `-2`: CRD, operator
  - `-1`: Namespace, SecretStore / ExternalSecret, ConfigMap
  - `0`: Storage, database
  - `1`: Core services
  - `2`: Ingress / Gateway / HTTPRoute, DNS
- **MUST** Database migrations run as a `Job` with the hook `argocd.argoproj.io/hook: PreSync` and `argocd.argoproj.io/hook-delete-policy: BeforeHookCreation`. Do not use initContainers (see skill `db-reliability`).

## Secrets

- **MUST** Do not commit raw or base64 Secrets. Use External Secrets Operator (source: Key Vault / Secrets Manager / Vault), Sealed Secrets or SOPS.

## Verification gates

```bash
# Render the manifests the same way Argo CD will, then validate
kustomize build <dir> | kubeconform -strict -summary         # or helm template ... | kubeconform
argocd app diff <app>                                         # if you have argocd CLI access
# After sync: argocd app get <app> → Synced + Healthy; no Degraded/Missing resources
```
