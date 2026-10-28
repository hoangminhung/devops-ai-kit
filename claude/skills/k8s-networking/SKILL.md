---
name: k8s-networking
description: Kubernetes networking standards — Gateway API versus Ingress, migrating off the retired ingress-nginx controller, choosing a Gateway implementation, Cilium/eBPF CNI and kube-proxy replacement, NetworkPolicy and L7 policy, Hubble observability, DNS and load-balancer cutovers. Use whenever designing or changing ingress or gateways, CNI, network policies, TLS termination, or troubleshooting in-cluster networking — and whenever ingress-nginx is found in a cluster.
when_to_use: Use when designing/changing ingress, Gateway API, CNI (Cilium), NetworkPolicy, TLS, moving off ingress-nginx, or debugging networking inside the cluster. Vietnamese triggers — "thiết kế/đổi ingress", "chuyển khỏi ingress-nginx", "debug mạng trong cluster".
---

# Kubernetes networking standards

<!-- devops-ai-kit · Last reviewed: 2026-10-28 -->

## 1. ingress-nginx is no longer maintained

- The Ingress NGINX project (`kubernetes/ingress-nginx`) was retired in March 2026: no more releases, bug fixes or security patches. Running copies still work, but new vulnerabilities will not be fixed.
- Do not confuse it with F5's **NGINX Ingress Controller** (`nginx/kubernetes-ingress`). That is a different product, and F5 still maintains it. Check the real image that is running.
- **MUST** When recon finds ingress-nginx (`kubectl get pods -A -l app.kubernetes.io/name=ingress-nginx`): write it in the risks part of the report and suggest a migration plan (L2/L3). Do not rewrite routing outside the task scope.
- Migration plan:
  1. List every `nginx.ingress.kubernetes.io/*` annotation in use (rewrite, auth, rate limit, snippet, CORS…). These annotations do **not** work on other controllers; map them to HTTPRoute filters or to the new implementation's own policies.
  2. Build the new Gateway **side by side**, with a new IP / LB.
  3. Lower the DNS TTL; test with the Host header / hosts file.
  4. Move DNS step by step (one host at a time).
  5. Keep the old controller until it has no more traffic.

## 2. Gateway API

- **SHOULD** New platforms use Gateway API with a conformant implementation (e.g. Cilium, Envoy Gateway, Istio, NGINX Gateway Fabric, or a managed cloud service such as Application Gateway for Containers on Azure). Choose based on the conformance report and the features you need, for the **exact version**.
- Roles:
  - The platform team manages `GatewayClass` / `Gateway` (listeners, TLS, IP).
  - App teams manage `HTTPRoute` / `GRPCRoute`.
  - Routes from other namespaces must be allowed with `allowedRoutes`; cross-namespace references (e.g. a TLS Secret) need a `ReferenceGrant`.
- Advanced features (weighted traffic split, header match, mirroring) have different support levels between implementations (Core / Extended / Implementation-specific). Check before you design around them.
- TLS on the Gateway is managed by cert-manager (see `pki-secrets`).
- **CONTEXT** If the system uses Ingress with a controller that is still maintained, keep it. The Ingress API is feature-frozen but not removed.

## 3. CNI & Cilium

- **CONTEXT** Self-managed clusters (on-prem, Hetzner…) can use Cilium with kube-proxy replacement. Check the kernel requirements for the Cilium version. Changing the CNI of a running cluster is L3; building a new cluster is often easier.
- Managed clusters use the provider's option: AKS → Azure CNI Overlay (optional Azure-managed Cilium dataplane), GKE → Dataplane V2, EKS → VPC CNI or Cilium depending on the design. Do **not** install Cilium on top of a managed CNI.
- **SHOULD** Turn on Hubble when you use Cilium, to see network flows, drop reasons, DNS.
- **CONTEXT** L7 policy (`CiliumNetworkPolicy` by method / path) only when really needed; L7 policy sends traffic through a proxy, so it adds overhead.

## 4. NetworkPolicy

- **SHOULD** Default-deny **ingress** for app namespaces, plus specific allows (from the Gateway / ingress namespace, from the monitoring namespace to scrape metrics).
- **CONTEXT** Default-deny **egress** is safer but takes more work to maintain. When you turn it on, always allow:
  - DNS to kube-dns (UDP **and** TCP 53);
  - needed egress: databases, external APIs, the API server for operators.
- **MUST** Roll out in this order: create the allow policies first, then turn on default-deny. Treat it as an L2 change.
- **MUST** Verify with real traffic, not only by reading YAML: a test pod (`kubectl run` / `kubectl debug` + curl), or `hubble observe --verdict DROPPED`.

## 5. DNS & load balancers during a migration

- **MUST** Lower the TTL of the DNS records before the switch (wait at least as long as the old TTL).
- **CONTEXT** `externalTrafficPolicy: Local` keeps the client source IP but can spread load unevenly; use it when you need the real IP for rate limits / logs.

## Verify

```bash
kubectl get gatewayclass,gateway -A
kubectl get httproute -A -o wide            # Accepted / ResolvedRefs = True
kubectl describe httproute <name> -n <ns>   # check conditions when a route does not work
curl -sv --resolve <host>:443:<gateway-ip> https://<host>/healthz
```
