# Sandbox

A place to test the kit's behaviour (see [`scenarios/`](../scenarios/README.md)). Two layers:

| Layer | What | Needs | Used by |
|---|---|---|---|
| 1. Sample repo | `sandbox/repo/`: Terraform (`local` / `random` / `null` providers only), a Helm chart, an Argo CD Application, Ansible for `localhost`, and manifests kept in `deploy/` on purpose | nothing (Terraform, Helm, Ansible only to run the sample commands) | scenarios 05–10 |
| 2. Cluster (optional) | a kind cluster `devops-kit-sandbox` with "traps": ingress-nginx, a StorageClass with `reclaimPolicy: Delete` and a PVC on it, a Secret with a fake value, a namespace without NetworkPolicy, and Grafana | docker, kind, kubectl | scenarios 01–04 |

You do not need Kubernetes to use or test most of the kit: layer 1 is enough for 6 of the 10 scenarios.

## Layer 2: the cluster

```bash
sandbox/up.sh      # create (or refresh) the cluster, the contexts and the read-only kubeconfig
sandbox/down.sh    # delete the cluster and its kubeconfig files (asks first)
```

- `up.sh` uses its **own kubeconfig files** in this folder (`.kubeconfig`, `.ai-kubeconfig`, both gitignored). Your `~/.kube/config` is not read or changed.
- Contexts: `kind-devops-kit-sandbox` (admin), **`sandbox-prod`** (same cluster, a production-like name to test production detection), **`sandbox-prod-ro`** (read-only, made by `setup/k8s/make-ai-kubeconfig.sh`: this checks the kit's RBAC on a real cluster).
- The trap Deployments have `replicas: 0`, so no images are pulled for them. Creating the cluster pulls the kind node image once (~1 GB).
- Install kind without root: download the release binary for your OS from <https://github.com/kubernetes-sigs/kind/releases>, check its `.sha256sum`, and put it in `~/.local/bin`.
