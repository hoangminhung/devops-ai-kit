# What to look for, per technology

<!-- devops-ai-kit · Used by /infra-scout step 2. Read files only; never open state, .env, keys or kubeconfig contents. -->

| Technology | Files to look for | What to take | Goes to (CLAUDE.md) |
|---|---|---|---|
| Terraform / OpenTofu | `*.tf`, `*.tfvars`, `.terraform-version`, `.opentofu-version`, `.terraform.lock.hcl`, `terragrunt.hcl` | Env folders (`envs/<env>`, `environments/<platform>/<env>`), `backend` block (type + key / container / bucket name, not credentials), workspace use (`terraform.workspace`), `required_version`, provider versions, module sources | Environment registry (Terraform dir / workspace), Stack & versions, Repo layout |
| Helm | `Chart.yaml`, `values*.yaml`, `helmfile*.yaml`, `charts/` or `chart/` | Chart names and versions, dependencies, one values file per env | Stack & versions, Repo layout |
| Argo CD | YAML with `apiVersion: argoproj.io/...` and `kind: Application` / `ApplicationSet` / `AppProject` | `spec.source(s).repoURL` + `targetRevision` (which branch per env), `destination.server` / `name` + namespace, sync policy (automated / selfHeal / prune) | Environment registry (who makes changes: GitOps), Project conventions |
| Kubernetes manifests | YAML with `apiVersion` + `kind`, `kustomization.yaml`, overlays | Namespaces, overlay per env, folders outside `k8s/`, `manifests/` (note them for `/infra-rulebook`) | Repo layout, Environment registry (namespace) |
| Ansible | `ansible.cfg`, `inventories/<env>/`, `inventory*`, `group_vars/`, `host_vars/`, playbooks (`- hosts:`), `roles/` | Inventory per env, how inventory is made (static / generated from Terraform), main playbooks | Environment registry, Common commands |
| Containers | `Dockerfile*`, `Containerfile`, `.dockerignore` | Base images, registry names | Stack & versions |
| Observability | `*.alloy`, `PrometheusRule`, `ServiceMonitor`, dashboards JSON | Monitoring stack and where alerts live | Stack & versions |
| CI / automation | `.github/workflows/*`, `.gitlab-ci.yml`, `Jenkinsfile`, `azure-pipelines.yml`, `Makefile`, `scripts/` | Lint / plan / apply jobs, who can apply, `make` targets and their env argument (e.g. `make plan e=<platform>/<env>`) | Common commands, Environment registry (who makes changes) |
| Access | gitignored names like `kubeconfig.*`, `ai-config`, `.kube/` mentions in README / scripts | **Names** of kubeconfig files and contexts per env (never their content) | Environment registry (kube context / kubeconfig) |
| Docs | `README*`, `docs/`, `runbooks/`, `adr/` | Where runbooks, ADRs and change records live; doc language | Documentation |

## Environment registry hints

- An env usually shows up in several places with the same name: a Terraform env folder, a tfvars file, an inventory folder, an Argo CD destination, a kubeconfig file name. Matching names → ✅; one source only → ⚠️.
- A name that contains `prod`, `prd`, `production` or `live` is production until the user says otherwise. Mark it so in the registry.
- "Who makes changes" comes from CI (apply job, manual approval), Argo CD sync policy, or README. If nothing says it → ⚠️ and ask.
