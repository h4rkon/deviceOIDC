#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# deviceOIDC "doctor" script
# - prints setup facts (URLs, namespaces)
# - detects access mode:
#     * port-forward mode via EDGE_PORT (default 8081)
#     * or direct mode (EDGE_PORT empty)
# - checks k8s/argo/ingress/keycloak/envoy
# - retrieves ArgoCD initial admin password (if secret exists)
# - optional: mint Keycloak token + call protected hello (KCPASS=...)
#
# Requirements: kubectl, curl, jq
# Optional: lsof (nice-to-have for port check)
# -----------------------------------------------------------------------------

# --- Config (override via env vars) ------------------------------------------
NS_ARGOCD="${NS_ARGOCD:-argocd}"
NS_INGRESS="${NS_INGRESS:-ingress-nginx}"
NS_KEYCLOAK="${NS_KEYCLOAK:-keycloak}"
NS_POSTGRES="${NS_POSTGRES:-postgres}"
NS_GATEWAY="${NS_GATEWAY:-gateway}"
NS_HELLO="${NS_HELLO:-hello}"

ARGO_HOST="${ARGO_HOST:-argocd.local}"
KEYCLOAK_HOST="${KEYCLOAK_HOST:-keycloak.local}"
HELLO_HOST="${HELLO_HOST:-hello.local}"

REALM="${REALM:-deviceoidc}"
CLIENT_ID="${CLIENT_ID:-deviceoidc-cli}"
KC_USER="${KC_USER:-test}"

# Access model:
# - If you port-forward ingress-nginx to localhost, set EDGE_PORT (default 8081).
# - If you reach cluster ingress directly (NodeIP/LB), set EDGE_PORT="" and ensure DNS points to that IP.
EDGE_HOST="${EDGE_HOST:-localhost}"
EDGE_PORT="${EDGE_PORT:-8081}" # empty string => direct mode on port 80

# Optional: Keycloak user password for token mint test
KCPASS="${KCPASS:-}"

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
bold() { printf "\033[1m%s\033[0m\n" "$*"; }
ok()   { printf "  ✅ %s\n" "$*"; }
warn() { printf "  ⚠️  %s\n" "$*"; }
fail() { printf "  ❌ %s\n" "$*"; exit 1; }

need() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing dependency: $1"
}

section() {
  echo
  bold "== $* =="
}

hr() { echo "------------------------------------------------------------"; }

http_code_remote() {
  # prints: "<code> (remote=<ip>)"
  curl -s -o /dev/null -w "%{http_code} (remote=%{remote_ip})" "$1" || true
}

dns_ip() {
  local h="$1"
  getent hosts "$h" 2>/dev/null | awk '{print $1}' | head -n1 || true
}

# -----------------------------------------------------------------------------
# Preflight
# -----------------------------------------------------------------------------
need kubectl
need curl
need jq

# -----------------------------------------------------------------------------
# Derived URLs
# -----------------------------------------------------------------------------
if [[ -n "${EDGE_PORT}" ]]; then
  # Port-forward mode: ingress is exposed on localhost:EDGE_PORT, but Host routing is still by hello.local/keycloak.local
  INGRESS_BASE="http://${EDGE_HOST}:${EDGE_PORT}"
  HELLO_URL="${INGRESS_BASE}/hello"              # with Host header hello.local
  KEYCLOAK_URL="${INGRESS_BASE}/"                # with Host header keycloak.local
  ARGO_URL="http://localhost:8080"               # typical port-forward for argocd-server
else
  # Direct mode: relies on DNS mapping hosts to cluster IP and port 80
  INGRESS_BASE="http://${HELLO_HOST}"
  HELLO_URL="http://${HELLO_HOST}/hello"
  KEYCLOAK_URL="http://${KEYCLOAK_HOST}/"
  ARGO_URL="http://${ARGO_HOST}"
fi

KC_ISSUER="http://${KEYCLOAK_HOST}/realms/${REALM}"
KC_WELLKNOWN="${KC_ISSUER}/.well-known/openid-configuration"
KC_TOKEN="${KC_ISSUER}/protocol/openid-connect/token"
KC_JWKS="${KC_ISSUER}/protocol/openid-connect/certs"

# -----------------------------------------------------------------------------
# Setup facts
# -----------------------------------------------------------------------------
section "Setup facts (what this script assumes)"
cat <<EOF
Namespaces:
  - argocd:        ${NS_ARGOCD}
  - ingress-nginx: ${NS_INGRESS}
  - keycloak:      ${NS_KEYCLOAK}
  - postgres:      ${NS_POSTGRES}
  - gateway:       ${NS_GATEWAY}
  - hello:         ${NS_HELLO}

Access mode:
  - EDGE_HOST:     ${EDGE_HOST}
  - EDGE_PORT:     ${EDGE_PORT:-<direct>}
  - Ingress base:  ${INGRESS_BASE}
  - ArgoCD URL:    ${ARGO_URL}

Host-based URLs (used via Host header routing):
  - Keycloak UI:   http://${KEYCLOAK_HOST}/admin
  - Hello API:     http://${HELLO_HOST}/hello

Keycloak OIDC endpoints:
  - Issuer:        ${KC_ISSUER}
  - Token:         ${KC_TOKEN}
  - JWKS:          ${KC_JWKS}
EOF

if [[ -n "$KCPASS" ]]; then
  warn "KCPASS is set -> will mint a Keycloak token for user '${KC_USER}' and call Hello API."
fi

# -----------------------------------------------------------------------------
# K8s basics
# -----------------------------------------------------------------------------
section "Kubernetes sanity"
kubectl get nodes -o wide
ok "Nodes listed"

echo
bold "Namespaces present?"
for ns in "${NS_ARGOCD}" "${NS_INGRESS}" "${NS_KEYCLOAK}" "${NS_POSTGRES}" "${NS_GATEWAY}" "${NS_HELLO}"; do
  kubectl get ns "$ns" >/dev/null 2>&1 && ok "$ns" || fail "Namespace missing: $ns"
done

echo
bold "Pods overview (non-running pods highlighted):"
kubectl get pods -A
NON_RUNNING="$(kubectl get pods -A --no-headers | awk '$4!="Running" && $4!="Completed"{print}' || true)"
if [[ -n "$NON_RUNNING" ]]; then
  warn "Some pods are not Running/Completed:"
  echo "$NON_RUNNING" | sed 's/^/  /'
else
  ok "All pods Running/Completed"
fi

# -----------------------------------------------------------------------------
# Ingress + routing checks
# -----------------------------------------------------------------------------
section "Ingress sanity"
kubectl -n "${NS_INGRESS}" get pods
kubectl get ingress -A || warn "No ingress resources found (is Envoy exposed differently?)"

if [[ -n "${EDGE_PORT}" ]]; then
  echo
  bold "Port-forward mode checks (does localhost:${EDGE_PORT} listen?)"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"${EDGE_PORT}" -sTCP:LISTEN >/dev/null 2>&1 \
      && ok "Port ${EDGE_PORT} is listening on localhost" \
      || warn "Port ${EDGE_PORT} is NOT listening. Start port-forward for ingress-nginx."
  else
    warn "lsof not found; skipping listener check"
  fi
else
  echo
  bold "Direct mode checks (DNS mapping must NOT be 127.0.0.1)"
  for h in "${HELLO_HOST}" "${KEYCLOAK_HOST}" "${ARGO_HOST}"; do
    ip="$(dns_ip "$h")"
    echo "  DNS ${h} => ${ip:-<no result>}"
    [[ "$ip" == "127.0.0.1" ]] && warn "${h} resolves to 127.0.0.1 but EDGE_PORT is empty (direct mode)"
  done
fi

hr
bold "HTTP checks"
if [[ -n "${EDGE_PORT}" ]]; then
  # Use Host header to hit ingress via localhost
  HELLO_CODE="$(http_code_remote "${HELLO_URL}")"
  KC_CODE="$(http_code_remote "${KEYCLOAK_URL}")"
  echo "  hello.local /hello => ${HELLO_CODE} (via ${INGRESS_BASE} + Host: hello.local)"
  echo "  keycloak.local     => ${KC_CODE} (via ${INGRESS_BASE} + Host: keycloak.local)"

  # Real calls (first line only, to keep output readable)
  echo
  bold "Routing smoke (first line):"
  curl -s -i -H "Host: hello.local" "${HELLO_URL}" | head -n 1
  curl -s -i -H "Host: keycloak.local" "${KEYCLOAK_URL}" | head -n 1
else
  HELLO_CODE="$(http_code_remote "${HELLO_URL}")"
  KC_CODE="$(http_code_remote "${KEYCLOAK_URL}")"
  echo "  hello.local /hello => ${HELLO_CODE}"
  echo "  keycloak.local     => ${KC_CODE}"
fi

# -----------------------------------------------------------------------------
# ArgoCD
# -----------------------------------------------------------------------------
section "ArgoCD health"
kubectl -n "${NS_ARGOCD}" get pods
echo
bold "ArgoCD Applications:"
kubectl -n "${NS_ARGOCD}" get applications.argoproj.io 2>/dev/null || warn "No ArgoCD Applications found via kubectl (CRDs missing?)"

echo
bold "ArgoCD initial admin password (if available):"
# Many installs store the one-time password in argocd-initial-admin-secret
if kubectl -n "${NS_ARGOCD}" get secret argocd-initial-admin-secret >/dev/null 2>&1; then
  PW="$(kubectl -n "${NS_ARGOCD}" get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d || true)"
  if [[ -n "$PW" ]]; then
    ok "Retrieved from argocd-initial-admin-secret"
    cat <<EOF
  URL:      ${ARGO_URL}
  user:     admin
  password: ${PW}
EOF
  else
    warn "Secret exists but password could not be decoded"
  fi
else
  warn "argocd-initial-admin-secret not found (maybe already rotated/deleted)."
  echo "  If you previously changed the admin password, Kubernetes won't know the old one."
fi

# -----------------------------------------------------------------------------
# Keycloak OIDC endpoints
# -----------------------------------------------------------------------------
section "Keycloak OIDC endpoints"
if [[ -n "${EDGE_PORT}" ]]; then
  # In port-forward mode, the public host keycloak.local is reached via ingress on localhost:EDGE_PORT with Host header.
  # But the OIDC discovery URLs use absolute URLs with keycloak.local.
  # We'll fetch through ingress using Host header, targeting the right path.
  WK_PATH="/realms/${REALM}/.well-known/openid-configuration"
  JWKS_PATH="/realms/${REALM}/protocol/openid-connect/certs"

  WK_JSON="$(curl -s -H "Host: keycloak.local" "${INGRESS_BASE}${WK_PATH}" || true)"
  ISSUER="$(echo "$WK_JSON" | jq -r .issuer 2>/dev/null || true)"
  if [[ -n "$ISSUER" && "$ISSUER" != "null" ]]; then
    ok "Well-known reachable (via ingress port-forward)"
    echo "  issuer: ${ISSUER}"
  else
    warn "Failed to fetch .well-known via ingress port-forward: ${INGRESS_BASE}${WK_PATH}"
  fi

  JWKS_JSON="$(curl -s -H "Host: keycloak.local" "${INGRESS_BASE}${JWKS_PATH}" || true)"
  JWKS_KEYS="$(echo "$JWKS_JSON" | jq '.keys | length' 2>/dev/null || echo "0")"
  if [[ "${JWKS_KEYS}" != "0" ]]; then
    ok "JWKS reachable (${JWKS_KEYS} keys)"
  else
    warn "JWKS fetch failed or empty"
  fi
else
  ISSUER="$(curl -s "${KC_WELLKNOWN}" | jq -r .issuer 2>/dev/null || true)"
  if [[ -n "$ISSUER" && "$ISSUER" != "null" ]]; then
    ok "Well-known reachable"
    echo "  issuer: ${ISSUER}"
  else
    warn "Failed to fetch .well-known config from ${KC_WELLKNOWN}"
  fi

  JWKS_KEYS="$(curl -s "${KC_JWKS}" | jq '.keys | length' 2>/dev/null || echo "0")"
  if [[ "${JWKS_KEYS}" != "0" ]]; then
    ok "JWKS reachable (${JWKS_KEYS} keys)"
  else
    warn "JWKS fetch failed or empty"
  fi
fi

# -----------------------------------------------------------------------------
# Envoy quick check
# -----------------------------------------------------------------------------
section "Envoy quick check"
kubectl -n "${NS_GATEWAY}" get pods
ENVOY_POD="$(kubectl -n "${NS_GATEWAY}" get pods -l app=envoy -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
if [[ -n "$ENVOY_POD" ]]; then
  ok "Envoy pod: ${ENVOY_POD}"
  echo
  bold "Last 30 log lines:"
  kubectl -n "${NS_GATEWAY}" logs "${ENVOY_POD}" --tail=30 || true
else
  warn "Couldn't find Envoy pod via label app=envoy. Adjust selector in script."
fi

# -----------------------------------------------------------------------------
# Optional: mint token + call hello with Bearer
# -----------------------------------------------------------------------------
if [[ -n "$KCPASS" ]]; then
  section "Keycloak token mint + protected call"

  # Token endpoint via ingress (port-forward mode) or direct (direct mode)
  if [[ -n "${EDGE_PORT}" ]]; then
    TOKEN_ENDPOINT="${INGRESS_BASE}/realms/${REALM}/protocol/openid-connect/token"
    TOKEN_JSON="$(curl -s -X POST "${TOKEN_ENDPOINT}" \
      -H "Host: keycloak.local" \
      -H 'content-type: application/x-www-form-urlencoded' \
      -d "grant_type=password&client_id=${CLIENT_ID}&username=${KC_USER}&password=${KCPASS}" || true)"
  else
    TOKEN_ENDPOINT="${KC_TOKEN}"
    TOKEN_JSON="$(curl -s -X POST "${TOKEN_ENDPOINT}" \
      -H 'content-type: application/x-www-form-urlencoded' \
      -d "grant_type=password&client_id=${CLIENT_ID}&username=${KC_USER}&password=${KCPASS}" || true)"
  fi

  TOKEN="$(echo "$TOKEN_JSON" | jq -r .access_token 2>/dev/null || true)"
  if [[ -z "$TOKEN" || "$TOKEN" == "null" ]]; then
    echo "$TOKEN_JSON" | jq . || true
    fail "Token mint failed. Check username/password/client settings."
  fi
  ok "Token minted"

  echo
  bold "JWT headline (iss/aud/exp):"
  echo "$TOKEN" | awk -F. '{print $2}' | base64 -d 2>/dev/null | jq '{iss,aud,exp,azp,scope}' || true

  echo
  bold "Call hello with Bearer token (first line):"
  if [[ -n "${EDGE_PORT}" ]]; then
    curl -s -i -H "Host: hello.local" -H "Authorization: Bearer ${TOKEN}" "${HELLO_URL}" | head -n 1
  else
    curl -s -i -H "Authorization: Bearer ${TOKEN}" "${HELLO_URL}" | head -n 1
  fi
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
section "Summary / next commands"
cat <<EOF
Common commands (port-forward mode):
  curl -i -H "Host: hello.local"    ${INGRESS_BASE}/hello
  curl -i -H "Host: keycloak.local" ${INGRESS_BASE}/
  curl -s -H "Host: keycloak.local" ${INGRESS_BASE}/realms/${REALM}/.well-known/openid-configuration | jq .issuer

ArgoCD password (initial, if exists):
  kubectl -n ${NS_ARGOCD} get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d

To mint token and test protected hello:
  KCPASS='testUserPassword' EDGE_PORT=${EDGE_PORT:-8081} ./.scripts/doctor.sh
EOF

ok "Done"
