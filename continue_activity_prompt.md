
## 📄 `PROMPT.md` (handover / continuation prompt)

```md
# deviceOIDC – Continuation Prompt

You are continuing work on a local Kubernetes reference system called **deviceOIDC**.

This prompt exists to restore **full context** in a new chat session.

---

## Core idea

This is a **gateway-first, GitOps-driven OIDC architecture**:

- Envoy is the single enforcement point
- Keycloak issues JWTs
- Envoy validates JWTs offline via JWKS
- Backend services do NOT implement authentication
- Everything runs on local k3s (Colima)
- Cluster state is managed via ArgoCD

This is a clarity-first system, not a production cluster.

---

## What is already DONE

### Security
- Envoy validates JWTs offline
- No token introspection
- Keycloak key rotation works
- Unauthorized requests blocked at Envoy
- Authorized requests succeed

### GitOps
- App-of-Apps pattern
- Declarative state
- Manual kubectl only for debugging

### Logging
- Loki + Promtail fully functional
- Promtail reads Docker JSON logs
- Old log rejection and rate limits understood
- Logs queryable by namespace/app/pod/container/node

### Tooling
- `doctor.sh` verifies:
  - cluster
  - ingress routing
  - Keycloak OIDC
  - Envoy
  - Loki
  - optional token mint + API call

---

## What is NOT done yet (intentionally)

- Envoy access logs → Loki
- Keycloak structured logs → Loki
- Metrics via Mimir
- Traces via Tempo
- Grafana dashboards
- Signal correlation

---

## Immediate next technical steps

1. Enable Envoy access logs
   - JSON format
   - stdout
   - picked up by Promtail

2. Normalize logs
   - Keycloak → JSON logs
   - Hello service → JSON logs
   - Consistent fields (service, level, request_id)

3. Expand observability
   - Grafana dashboards (logs first)
   - Add Mimir metrics
   - Add Tempo tracing
   - Correlate via trace_id

4. Debug flows explicitly
   - Watch Envoy logs for requests
   - Watch Keycloak logs for token issuance
   - Watch Hello logs for request handling

---

## Constraints (do not break)

- Gateway owns auth
- Services stay dumb
- No introspection
- No sidecars
- Everything observable
- Everything reproducible via Git

---

## Mental model

This system answers one question:

“How do I explain and prove gateway-first security on a whiteboard without hiding complexity?”

Proceed incrementally.  
Always make behavior visible.
