---
paths:
  - "**/Dockerfile"
  - "**/Dockerfile.*"
  - "**/*.Dockerfile"
  - "**/*.dockerfile"
  - "**/Containerfile"
  - "**/.dockerignore"
---

# Dockerfile standards

<!-- devops-ai-kit · Last reviewed: 2026-10-28 · The CI part (scan, SBOM, image signing) is in skill `container-supply-chain`. -->

- **MUST** Use a multi-stage build for apps that need a build step: the build stage has the toolchain; the runtime stage has only the binary and the minimum dependencies.
- **MUST** Do not use the `latest` tag for the base image; **SHOULD** pin the digest (`image:tag@sha256:...`) for production images.
- **SHOULD** Use a minimal runtime base: distroless, Chainguard, or Alpine.
  - Note: Alpine uses musl, which can behave differently from glibc (DNS, native modules).
  - If the image has no shell, debug with `kubectl debug` (ephemeral container).
- **MUST** Run as a non-root user with a **numeric UID** (e.g. `USER 10001:10001`), so Kubernetes `runAsNonRoot` can check it.
- **SHOULD** Order steps for good caching:
  1. Copy the dependency files (`go.mod`, `package*.json`, `requirements.txt`, `pom.xml`).
  2. Install dependencies.
  3. Copy the source code.
- **SHOULD** Install packages and clean the cache in the same `RUN` (`apt-get install --no-install-recommends ... && rm -rf /var/lib/apt/lists/*`, `apk add --no-cache`).
- **MUST** Do not put secrets in `ARG` / `ENV` / layers. If you need a secret at build time, use BuildKit `RUN --mount=type=secret`.
- **MUST** Have a `.dockerignore` that excludes `.git`, `.env*`, `*.tfstate*`, kubeconfig, `node_modules`, old build artifacts.
- `HEALTHCHECK` does nothing on Kubernetes. Use probes in the manifest.

## Verification gates

```bash
hadolint Dockerfile
docker build -t <name>:<tag> .
trivy image --severity HIGH,CRITICAL --ignore-unfixed <name>:<tag>
```
