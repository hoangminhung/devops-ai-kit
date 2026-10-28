---
paths:
  - "**/charts/**"
  - "**/helm/**"
  - "**/helmfile.d/**"
  - "**/Chart.yaml"
  - "**/Chart.lock"
  - "**/values*.yaml"
  - "**/values*.yml"
  - "**/helmfile*.yaml"
---

# Helm standards

<!-- devops-ai-kit · Last reviewed: 2026-10-28 -->

## Versions & upgrades

- **MUST** Pin the chart version everywhere it is set (`helm upgrade --version`, `dependencies` in `Chart.yaml`, helmfile, Argo CD `targetRevision`). Commit `Chart.lock`.
- **MUST** Before you change the chart version: read the release notes / upgrade notes of **every** version between the current and the target version. Compare default values (`helm show values <chart> --version <old>` and `<new>`). Write breaking changes in the plan.
- **MUST** CRDs: Helm does not upgrade CRDs in the chart's `crds/` folder. For charts with CRDs (kube-prometheus-stack, cert-manager, Longhorn, operators…), follow the chart's upgrade guide: apply the CRDs separately, or use Argo CD with `ServerSideApply=true`.
- Helm 4 renamed / changed some flags compared to Helm 3. Check `helm version` and `helm upgrade --help` before you use flags like rollback on failure (`--atomic` in Helm 3) or `--force`.

## Values

- **SHOULD** Use layers: `values.yaml` (shared) + `values-<env>.yaml` (per-environment differences). Only write what you override. Do not copy all the chart's default values.
- **MUST** Do not put secrets in committed values. Use `existingSecret` (if the chart supports it) with ESO, or SOPS / helm-secrets.
- **SHOULD** Apply pod security standards (kubernetes rule) through values when the chart supports it. Do not fork a chart only to force the standards.
- Note: `helm get values` can print passwords that are in the values. Prefer reading the values files in Git.

## Deployment

- **MUST** Preview: `helm diff upgrade <release> <chart> -n <ns> --version <v> -f <values...>` (helm-diff plugin), or `helm template ... | kubectl diff -f -` for releases not managed by GitOps.
- **SHOULD** Use `--wait` and a sensible `--timeout`, so the command only succeeds when the workload is really ready.
- Rollback: `helm history <release>` then `helm rollback <release> <revision>`. Rollback does **not** undo CRDs or data in PVCs.
- Releases managed by Argo CD / Flux: change them through Git. Do not run `helm upgrade` by hand.

## Verification gates

```bash
helm lint <chart-dir> -f <values...>
helm template <release> <chart> --version <v> -f <values...> | kubeconform -strict -summary
helm diff upgrade <release> <chart> -n <ns> --version <v> -f <values...>
```
