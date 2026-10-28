---
paths:
  - "**/k8s/**"
  - "**/kubernetes/**"
  - "**/manifests/**"
  - "**/kustomize/**"
  - "**/overlays/**"
  - "**/clusters/**"
  - "**/kustomization.yaml"
  - "**/kustomization.yml"
---

# Kubernetes manifest standards

<!-- devops-ai-kit · Last reviewed: 2026-10-28 · If a repo keeps manifests in another folder, add a project-level rule with matching `paths`. -->

The items below apply to workloads the team writes itself. For third-party Helm charts, apply them through values when the chart supports it (see the helm rule). Do not fork a chart only to force the standards.

## Resources & availability

- **MUST** Every container has `resources.requests` (cpu, memory) and `limits.memory`.
- **CONTEXT** A CPU limit is not required (it causes throttling). Set it when you need to stop a noisy neighbor, when the namespace's LimitRange / quota requires it, or when a critical workload needs QoS `Guaranteed` (requests == limits for both cpu and memory).
- **MUST** Services that receive traffic have a `readinessProbe`. A `livenessProbe` must not depend on external dependencies (database, other APIs). Otherwise one DB problem makes all pods restart in a chain.
- **CONTEXT** `startupProbe` when the app starts slowly.
- **SHOULD** Production: `replicas ≥ 2`, a `PodDisruptionBudget`, and `topologySpreadConstraints` by zone/node.
- **CONTEXT** Split `system` / `workload` / `stateful` node pools with taints + tolerations when the cluster is big enough. Dev clusters or small clusters do not need it.

## Images & pod security

- **MUST** Do not use the `latest` tag; **SHOULD** pin the digest in production.
- **MUST** `securityContext`: `runAsNonRoot: true`, `allowPrivilegeEscalation: false`, `capabilities.drop: ["ALL"]`, `seccompProfile.type: RuntimeDefault`.
- **SHOULD** `readOnlyRootFilesystem: true` (mount an `emptyDir` for `/tmp` or any folder that needs writes).
- **SHOULD** App namespaces have Pod Security Admission labels: `enforce: baseline`, `warn` and `audit`: `restricted`. Raise `enforce` to `restricted` when the workload can meet it.
- **SHOULD** App namespaces have a default-deny ingress NetworkPolicy plus specific allows. When you turn on default-deny **egress**, always allow DNS to kube-dns (UDP and TCP 53). Otherwise all name lookups fail (details in skill `k8s-networking`).
- **SHOULD** Standard labels `app.kubernetes.io/name`, `instance`, `part-of`, `managed-by`.

## Safe changes

- **MUST** Preview before apply: `kubectl diff -f <file>` (or `-k <dir>`) and `kubectl apply --dry-run=server`.
- **MUST** Find immutable fields before you edit: Deployment `spec.selector`, StatefulSet `volumeClaimTemplates`, PVC `storageClassName` / `accessModes`, Service `clusterIP`, Job `template`. Changing them requires delete and re-create, so it is an L3 change with its own plan. Never delete a StatefulSet / PVC as a "quick fix".
- **MUST** Resources managed by GitOps (with the annotation `argocd.argoproj.io/tracking-id`, or the label `app.kubernetes.io/instance` set by Argo CD, or Flux labels) must be changed through Git, not with a direct `kubectl apply` / `edit`, because Argo CD will overwrite them or cause drift.
- After a change: `kubectl rollout status`. Rollback with `kubectl rollout undo` only for resources not managed by GitOps.

## Verification gates

```bash
kubeconform -strict -summary <file-or-folder>
#   For CRDs: add -schema-location default \
#     -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'
kubectl diff -f <file>                    # or -k <dir>
kubectl apply --dry-run=server -f <file>
kube-linter lint <dir>                    # if installed
```
