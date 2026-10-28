---
name: container-supply-chain
description: Container and software supply-chain security in CI/CD — vulnerability scanning gates with Trivy or Grype, SBOM generation with Syft, image signing with Cosign (keyless or key-based), admission policies that only allow signed images (Kyverno, Sigstore policy-controller), base-image update cadence and registry hygiene. Use whenever building or changing CI pipelines that produce images, setting up registries, adding admission policies, or reviewing image security. Dockerfile authoring rules live in the dockerfile rule.
when_to_use: Use when building or changing a CI pipeline that builds images, setting up a registry, adding an admission policy, or reviewing image security. Vietnamese triggers — "xây/sửa pipeline CI build image", "thiết lập registry", "thêm admission policy", "review bảo mật image".
---

# Container supply-chain standards

<!-- devops-ai-kit · Last reviewed: 2026-10-28 · Dockerfile writing rules are in rule `dockerfile.md` (loaded automatically when you edit a Dockerfile). -->

## 1. Vulnerability scanning

- **MUST** The image build pipeline scans with Trivy or Grype. Fail the pipeline on `CRITICAL` (and **SHOULD** on `HIGH`) vulnerabilities **that already have a fix** (`--ignore-unfixed`, so vulnerabilities without a fix do not block every build).
- **SHOULD** Re-scan running images on a schedule (new vulnerabilities are published after the build), not only at build time.
- **SHOULD** Exceptions (`.trivyignore` / VEX) must have a reason and an expiry date.

## 2. SBOM

- **SHOULD** Create an SBOM for each released image (Syft, SPDX or CycloneDX format). Store it with the image (attestation) or in an artifact store.

## 3. Signing & deploy-time control

- **SHOULD** Sign images with Cosign before pushing to the production registry. Prefer keyless (the CI's OIDC), so you do not have to manage a private key.
- **CONTEXT** An admission policy that only allows signed images from trusted registries (Kyverno `verifyImages`, or Sigstore policy-controller).
  - Roll out in audit mode first, then enforce.
  - Exclude system namespaces on purpose, so you do not lock yourself out of the cluster.

## 4. Base images & registry

- **SHOULD** Have a base image update schedule (Renovate / Dependabot) to get security fixes.
- **SHOULD** Use a private registry (ACR / ECR / Artifact Registry / Harbor). Production clusters pull images only from allowed registries. Think about a mirror / cache for public images, to avoid rate limits and the risk of images being deleted.
- **MUST** Image tags cannot be overwritten in production (turn on immutable tags if the registry supports it), or deploy by digest.
