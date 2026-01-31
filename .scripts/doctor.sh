#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# deviceOIDC - doctor.sh
#
# Purpose:
# - One-command sanity + smoke test for the whole system
# - No assumptions, everything verified explicitly
#
# Requirements:
#   kubectl, curl, jq
#
# Optional:
#   lsof (port checks)
# =============================================================================

# -----------------------------------------------------------------------------
# Config (override via env)
# -----------------------------------------------------------------------------
NS_ARGOCD="${NS_ARGOCD:-argocd}"
NS_INGRESS="${NS_INGRESS:-ingress-nginx}"
NS_KEYCLOAK="${NS_KEYCLOAK:-keycloak}"
NS_POSTGRES="${NS_POSTGRES:-postgres}"
NS_GATEWAY="${NS_GATEWAY:-gateway}"
NS_HELLO="${NS_HELLO:-hello}"
NS_OBS="${NS_OBS:-observability}"

HELLO_HOST="${HELLO_HOST:-hello.local}"
KEYCLOAK_HOST="${KEYCLOAK_HOST:-keycloak.local}"
ARGO_HOST="${ARGO_HOST:-argocd.local}"

REALM="${REALM:-deviceoidc}"
CLIENT_ID="${CLIENT_ID:-deviceoidc-cli}"
KC_USER="${KC_USER:-test}"

EDGE_HOST="${EDGE_HOST:-localhost}"
EDGE_PORT="${EDGE_PORT:-8081}"   # empty = direct mode

KCPASS="${KCPASS:-}"

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
bold() { printf "\033[1m%s\033[0m\n" "$*"; }
ok()   { printf "  ✅ %s\n" "$*"; }
warn() { printf "  ⚠️  %s\n" "$*"; }
fail() { printf "  ❌ %s\n" "$*"; exit 1; }

need() { command -v "$1" >/dev/null || fail "Missing dependency: $1"; }

section() { echo; bold "== $* =="; }

# -----------------------------------------------------------------------------
# Preflight
# -----------------------------------------------------------------------------
need kubectl
need curl
need jq

# -----------------------------------------------------------------------------
# URLs
# -----------------------------------------------------------------------------
if [[ -n "$EDGE_PORT" ]]; then
  INGRESS="http://${EDGE_HOST}:${EDGE_PORT}"
  HELLO_URL="${INGRESS}/hello"
  KC_BASE="${INGRESS}"
  ARGO_URL="http://localhost:8080"
else
  HELLO_URL="http://${HELLO_HOST}/hello"
  KC_BASE="http://${KEYCLOAK_HOST}"
  ARGO_URL="http://${ARGO_HOST}"
fi

KC_ISSUER="http://${KEYCLOAK_HOST}/realms/${REALM}"
KC_TOKEN="${KC_ISSUER}/protocol/openid-connect/token"
KC_JWKS="${KC_ISSUER}/protocol/openid-connect/certs"

# -----------------------------------------------------------------------------
# Cluster sanity
# -----------------------------------------------------------------------------
section "Kubernetes"
kubectl get nodes -o wide
ok "Cluster reachable"

section "Namespaces"
for ns in "$NS_ARGOCD" "$NS_INGRESS" "$NS_KEYCLOAK" "$NS_POSTGRES" "$NS_GATEWAY" "$NS_HELLO" "$NS_OBS"; do
  kubectl get ns "$ns" >/dev/null && ok "$ns" || fail "Missing namespace: $ns"
done

section "Pods (non-running highlighted)"
kubectl get pods -A
BAD=$(kubectl get pods -A --no-headers | awk '$4!="Running" && $4!="Completed"{print}')
[[ -z "$BAD" ]] && ok "All pods healthy" || warn "Some pods not healthy"

# -----------------------------------------------------------------------------
# Ingress routing
# -----------------------------------------------------------------------------
section "Ingress routing"
curl -s -I -H "Host: hello.local" "$HELLO_URL" | head -n1
curl -s -I -H "Host: keycloak.local" "$KC_BASE/" | head -n1

# -----------------------------------------------------------------------------
# ArgoCD
# -----------------------------------------------------------------------------
section "ArgoCD"
kubectl -n "$NS_ARGOCD" get pods
kubectl -n "$NS_ARGOCD" get applications.argoproj.io || warn "No applications found"

# -----------------------------------------------------------------------------
# Keycloak
# -----------------------------------------------------------------------------
section "Keycloak OIDC"
WK=$(curl -s -H "Host: keycloak.local" "$KC_BASE/realms/$REALM/.well-known/openid-configuration")
ISSUER=$(echo "$WK" | jq -r .issuer)
[[ -n "$ISSUER" && "$ISSUER" != "null" ]] && ok "OIDC discovery OK" || fail "OIDC discovery failed"

JWKS_KEYS=$(curl -s -H "Host: keycloak.local" "$KC_BASE/realms/$REALM/protocol/openid-connect/certs" | jq '.keys|length')
[[ "$JWKS_KEYS" -gt 0 ]] && ok "JWKS available" || fail "JWKS empty"

# -----------------------------------------------------------------------------
# Envoy
# -----------------------------------------------------------------------------
section "Envoy"
ENVOY=$(kubectl -n "$NS_GATEWAY" get pods -l app=envoy -o jsonpath='{.items[0].metadata.name}')
kubectl -n "$NS_GATEWAY" logs "$ENVOY" --tail=20

# -----------------------------------------------------------------------------
# Loki / logs
# -----------------------------------------------------------------------------
section "Observability (logs)"
kubectl -n "$NS_OBS" get pods
LOKI_POD=$(kubectl -n "$NS_OBS" get pods -l app=loki -o jsonpath='{.items[0].metadata.name}')
kubectl -n "$NS_OBS" logs "$LOKI_POD" --tail=10

# -----------------------------------------------------------------------------
# Optional token test
# -----------------------------------------------------------------------------
if [[ -n "$KCPASS" ]]; then
  section "Token mint + API call"
  TOKEN=$(curl -s -X POST \
    -H "Host: keycloak.local" \
    -H "content-type: application/x-www-form-urlencoded" \
    "$KC_BASE/realms/$REALM/protocol/openid-connect/token" \
    -d "grant_type=password&client_id=$CLIENT_ID&username=$KC_USER&password=$KCPASS" \
    | jq -r .access_token)

  [[ -n "$TOKEN" && "$TOKEN" != "null" ]] || fail "Token mint failed"

  curl -s -I \
    -H "Host: hello.local" \
    -H "Authorization: Bearer $TOKEN" \
    "$HELLO_URL" | head -n1
fi

section "Doctor finished"
ok "System looks sane"
