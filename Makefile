SHELL := /bin/bash
.DEFAULT_GOAL := help

DOCTOR := ./.scripts/doctor.sh
PIDDIR := ./.pids

EDGE_PORT ?= 8081
ARGO_PORT ?= 8080
CLOAK_PORT ?= 8082

KC_PASS ?= swordfish

.PHONY: help
help:
	@echo ""
	@echo "deviceOIDC – targets"
	@echo ""
	@echo "  make check            Run health checks (expects port-forward ingress on EDGE_PORT)"
	@echo "  make pf-start         Start port-forwards (argocd + ingress-nginx) in background"
	@echo "  make pf-stop          Stop port-forwards"
	@echo "  make pf-status        Show port-forward PIDs / listeners"
	@echo ""
	@echo "Variables:"
	@echo "  EDGE_PORT=8081        Local port forwarded to ingress-nginx svc:80"
	@echo "  ARGO_PORT=8080        Local port forwarded to argocd-server svc:80"
	@echo "  CLOAK_PORT=8082        Local port forwarded to Keycloak svc:80"
	@echo ""

.PHONY: check
check:
	@echo ">> Running deviceOIDC checks (EDGE_PORT=$(EDGE_PORT))"
	EDGE_PORT=$(EDGE_PORT) $(DOCTOR)

# --- Port-forward management --------------------------------------------------

$(PIDDIR):
	@mkdir -p $(PIDDIR)

.PHONY: pf-start
pf-start: $(PIDDIR)
	@echo ">> Starting port-forwards (ingress-nginx -> :$(EDGE_PORT), argocd -> :$(ARGO_PORT), Keycloak -> :$(CLOAK_PORT))"
	@# ingress-nginx
	@bash -c ' \
	  if lsof -nP -iTCP:$(EDGE_PORT) -sTCP:LISTEN >/dev/null 2>&1; then \
	    echo "   ingress :$(EDGE_PORT) already listening"; \
	  else \
	    (kubectl -n ingress-nginx port-forward svc/ingress-nginx-controller $(EDGE_PORT):80 >/dev/null 2>&1 & echo $$! > $(PIDDIR)/pf-ingress.pid); \
	    echo "   started ingress port-forward (pid $$(cat $(PIDDIR)/pf-ingress.pid))"; \
	  fi'
	@# argocd
	@bash -c ' \
	  if lsof -nP -iTCP:$(ARGO_PORT) -sTCP:LISTEN >/dev/null 2>&1; then \
	    echo "   argocd  :$(ARGO_PORT) already listening"; \
	  else \
	    (kubectl -n argocd port-forward svc/argocd-server $(ARGO_PORT):80 >/dev/null 2>&1 & echo $$! > $(PIDDIR)/pf-argocd.pid); \
	    echo "   started argocd port-forward (pid $$(cat $(PIDDIR)/pf-argocd.pid))"; \
	  fi'
	@# keycloak
	@bash -c ' \
	  if lsof -nP -iTCP:$(CLOAK_PORT) -sTCP:LISTEN >/dev/null 2>&1; then \
	    echo "   Keycloak  :$(CLOAK_PORT) already listening"; \
	  else \
	    (kubectl -n keycloak port-forward svc/keycloak $(CLOAK_PORT):8080 >/dev/null 2>&1 & echo $$! > $(PIDDIR)/pf-cloak.pid); \
	    echo "   started Keycloak port-forward (pid $$(cat $(PIDDIR)/pf-cloak.pid))"; \
	  fi'

.PHONY: pf-stop
pf-stop:
	@echo ">> Stopping port-forwards"
	@bash -c ' \
	  for f in $(PIDDIR)/pf-ingress.pid $(PIDDIR)/pf-argocd.pid $(PIDDIR)/pf-cloak.pid; do \
	    if [ -f $$f ]; then \
	      pid=$$(cat $$f); \
	      if kill -0 $$pid >/dev/null 2>&1; then \
	        kill $$pid; echo "   killed pid $$pid ($$f)"; \
	      else \
	        echo "   stale pid file $$f"; \
	      fi; \
	      rm -f $$f; \
	    else \
	      echo "   no $$f"; \
	    fi; \
	  done'

.PHONY: pf-status
pf-status:
	@echo ">> Port-forward status"
	@echo "   expected: ingress localhost:$(EDGE_PORT), argocd localhost:$(ARGO_PORT), Keycloak localhost:${CLOAK_PORT}"
	@bash -c ' \
	  for p in $(EDGE_PORT) $(ARGO_PORT) $(CLOAK_PORT); do \
	    if lsof -nP -iTCP:$$p -sTCP:LISTEN >/dev/null 2>&1; then \
	      echo "   port $$p: LISTENING"; \
	    else \
	      echo "   port $$p: not listening"; \
	    fi; \
	  done'
	@bash -c ' \
	  for f in $(PIDDIR)/pf-ingress.pid $(PIDDIR)/pf-argocd.pid $(PIDDIR)/pf-cloak.pid; do \
	    if [ -f $$f ]; then echo "   $$(basename $$f): $$(cat $$f)"; else echo "   $$(basename $$f): <none>"; fi; \
	  done'

.PHONY: argocd-pass
argocd-pass:
	@kubectl -n argocd get secret argocd-initial-admin-secret \
	  -o jsonpath='{.data.password}' | base64 -d; echo

.PHONY: slot
slot:
	@KC_PASS=$(KC_PASS) python3 client/machine.py
