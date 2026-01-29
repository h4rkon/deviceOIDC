# deviceOIDC — Envoy + Keycloak (OIDC) + ArgoCD (GitOps) on local k3s/Colima

This repo is a **local, fully self-contained OIDC + API Gateway demo** on Kubernetes (Colima + k3s) with **GitOps via ArgoCD**.

No magic. No introspection. No “the backend does auth too”. Just a clean gateway pattern.

---

## What we’re building (target state)

**End goal:**

- **Envoy** is the API Gateway in front of services
- **Keycloak** is the Identity Provider (OIDC)
- Envoy validates **JWTs offline** via **JWKS** (no token introspection)
- A simple **Node.js hello service** is protected behind Envoy
- Everything is reproducible and GitOps-friendly (ArgoCD App-of-Apps)

---

## Current architecture (works)

### Cluster
- Local k3s running on **Colima**, single node

### Namespaces
- `argocd` — ArgoCD controllers + UI
- `ingress-nginx` — ingress controller
- `gateway` — Envoy
- `keycloak` — Keycloak
- `postgres` — Postgres for Keycloak
- `hello` — demo Node.js service

### Routing model
We use **host-based routing**:
- `hello.local`
- `keycloak.local`
- (optionally) `argocd.local`

**Important:** right now we primarily use **port-forward mode** (stable on macOS/Colima):
- ingress-nginx forwarded to `localhost:8081`
- ArgoCD forwarded to `localhost:8080`

So you reach everything via localhost + ports, and the `Host:` header does the host routing.

---

## URLs / Endpoints

### Port-forward mode (default)
- Ingress base: `http://localhost:8081`
- ArgoCD UI: `http://localhost:8080`

### Host-based (used by ingress rules)
- Keycloak UI: `http://keycloak.local/admin`
- Hello API: `http://hello.local/hello`

### Keycloak OIDC endpoints
- Issuer: `http://keycloak.local/realms/deviceoidc`
- Token: `http://keycloak.local/realms/deviceoidc/protocol/openid-connect/token`
- JWKS: `http://keycloak.local/realms/deviceoidc/protocol/openid-connect/certs`

---

## Behavior checks (expected)
- `hello` without token → **401** (Envoy blocks)
- `hello` with valid token → **200**
- Keycloak UI → **200/302**

Examples (port-forward via ingress):
```bash
curl -i -H "Host: hello.local" http://localhost:8081/hello
curl -i -H "Host: keycloak.local" http://localhost:8081/
