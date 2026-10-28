---
name: pki-secrets
description: Certificate, secret and access-management standards — cert-manager with ACME (HTTP-01/DNS-01) or Vault PKI, certificate-expiry alerting, External Secrets Operator with Key Vault/Secrets Manager/Vault, SOPS and Sealed Secrets, secret-leak prevention (gitleaks), workload identity, least-privilege and just-in-time access for humans, and read-only identities for AI agents. Use whenever handling TLS certificates, Kubernetes secrets, credentials, IAM/RBAC grants, access to clusters or cloud consoles, or anything that could leak a secret.
when_to_use: Use when handling TLS certificates, Kubernetes secrets, credentials, IAM/RBAC grants, cluster/console access, or anything that could leak a secret. Vietnamese triggers — "chứng chỉ TLS", "Kubernetes secret", "cấp quyền IAM/RBAC", "truy cập cluster/console", "làm lộ bí mật".
---

# PKI, secrets & access standards

<!-- devops-ai-kit · Last reviewed: 2026-10-28 -->

## 1. Certificates

- **MUST** TLS certificates in the cluster are managed by cert-manager (ACME / Let's Encrypt ClusterIssuer, or Vault PKI / an internal CA). For new setups, do not create certificates by hand and paste them into a Secret. If an old system already does this, write a recommendation to migrate.
- Choosing the ACME challenge:
  - HTTP-01: simple, needs a public endpoint.
  - DNS-01: needed for wildcards or internal endpoints; the DNS credential must be limited to the right zone.
- **SHOULD** Test new setups with Let's Encrypt **staging** first, so you do not hit the production rate limits.
- **MUST** Expiry alerts:
  - Certificates managed by cert-manager: `certmanager_certificate_expiration_timestamp_seconds - time() < 15 * 86400`, plus an alert when `certmanager_certificate_ready_status{condition="False"} == 1`.
  - Certificates outside cert-manager (cloud LB, external services): blackbox exporter with `probe_ssl_earliest_cert_expiry`.

## 2. Secrets in Kubernetes / GitOps

- **MUST** Do not commit raw / base64 Secrets. Do not keep secrets in plaintext in values / tfvars / inventory.
- **SHOULD** External Secrets Operator pulls from Azure Key Vault / AWS Secrets Manager / GCP Secret Manager / Vault. **CONTEXT** SOPS or Sealed Secrets when there is no central secret store yet.
- **SHOULD** Limit RBAC for reading Secrets: the default `view` role cannot read Secrets; do not widen it unless needed.
- **SHOULD** Have a rotation process for each type of secret, and know which apps must restart to get the new value.

## 3. Leak prevention

- **MUST** IaC / GitOps repos have secret scanning: gitleaks (or trufflehog) in pre-commit and CI.
- **MUST** A leaked secret (commit, log, chat, screenshot) must be **rotated right away**, not only removed from Git history.

## 4. Workload identity

- **MUST** Pods access the cloud with workload identity: AKS Workload Identity, EKS Pod Identity / IRSA, GKE Workload Identity Federation. Do not mount static credentials.
- **MUST** CI/CD uses OIDC federation. Do not store long-lived cloud keys in CI secrets.

## 5. Human access

- **MUST** One identity per person (SSO + MFA); no shared admin accounts; control-plane audit logs are on (AKS diagnostic logs / EKS control plane logging / GKE audit logs).
- **SHOULD** Admin access is given when needed and for a limited time: Entra PIM, AWS IAM Identity Center with temporary permission sets.
- **CONTEXT** Full zero standing privileges with PAM (Teleport, HashiCorp Boundary), with session recording for `kubectl exec` / SSH, when the organization has compliance requirements.

## 6. Identity for AI agents

- **MUST** AI sessions (Claude Code) use their own identity, **read-only** on production:
  - a kubeconfig from a ServiceAccount bound to the `view` role + cluster-scoped read, **no Secret read** (see `setup/k8s/` in devops-ai-kit);
  - Azure Reader / AWS ReadOnly / GCP Viewer for the cloud.
- **MUST** AI tokens are short-lived (`kubectl create token --duration`) and are created again when they expire.
- **SHOULD** Production changes prepared by the AI go through a GitOps PR or are run by the user.
