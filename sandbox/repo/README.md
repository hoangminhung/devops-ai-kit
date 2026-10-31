# shop-infra (sample)

Sample infrastructure repo used by the devops-ai-kit scenarios. It needs no cloud and no cluster:
Terraform uses only the `local`, `random` and `null` providers.

| Folder | Content |
|---|---|
| `terraform/envs/<env>/` | one root module per environment (`dev`, `prod`), local state |
| `terraform/modules/app-config/` | writes a config file for the app |
| `charts/web/` | Helm chart of the web app, one values file per environment |
| `gitops/apps/web/app.yaml` | Argo CD Application (Argo CD itself is not needed) |
| `deploy/web/` | plain Kubernetes manifests, kept outside the usual `k8s/` folder on purpose |
| `ansible/` | inventories per environment and a playbook for `localhost` |

```bash
make plan e=dev        # terraform plan for one environment
make apply e=dev       # terraform apply (local files only)
make ansible-check e=dev
```
