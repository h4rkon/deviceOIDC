SHELL := /bin/bash
.DEFAULT_GOAL := help

DOCTOR := ./.scripts/doctor.sh
PIDDIR := ./.pids

EDGE_PORT ?= 8081
ARGO_PORT ?= 8080
CLOAK_PORT ?= 8082
GRFN_PORT ?= 3000
POST_PORT ?= 5432
TRINO_PORT ?= 8084
NESSIE_PORT ?= 19120
MARQUEZ_PORT ?= 5005
MARQUEZ_UI_PORT ?= 3001

KC_PASS ?= swordfish

DBT_PROJECT_DIR ?= dbt
DBT_PROFILES_DIR ?= dbt
DBT_INTERVAL ?= 60
OPENLINEAGE_URL ?= http://localhost:5005
OPENLINEAGE_NAMESPACE ?= dataplatform
OPENLINEAGE_DBT_JOB_NAME ?= dbt-silver
OPENLINEAGE_JOB_TAG_PROJECT ?= dataplatform
OPENLINEAGE_JOB_TAG_LAYER ?= silver
OPENLINEAGE_RUN_TAG_ENV ?= local

VENV := .python
PYTHON := python3
PIP := $(VENV)/bin/pip

.PHONY: help
help:
	@echo ""
	@echo "deviceOIDC – targets"
	@echo ""
	@echo "  make check            Run health checks (expects port-forward ingress on EDGE_PORT)"
	@echo "  make pf-start         Start port-forwards (argocd + ingress-nginx) in background"
	@echo "  make pf-stop          Stop port-forwards"
	@echo "  make pf-status        Show port-forward PIDs / listeners"
	@echo "  make dbt-run          Run dbt (silver models) once"
	@echo "  make dbt-ol-run       Run dbt with OpenLineage -> Marquez"
	@echo "  make dbt-loop         Run dbt-ol on an interval"
	@echo ""
	@echo "Variables:"
	@echo "  EDGE_PORT=8081        Local port forwarded to ingress-nginx svc:80"
	@echo "  ARGO_PORT=8080        Local port forwarded to argocd-server svc:80"
	@echo "  CLOAK_PORT=8082        Local port forwarded to Keycloak svc:80"
	@echo "  GRFN_PORT=3000        Local port forwarded to Grafana svc:3000"
	@echo "  POST_PORT=5432        Local port forwarded to Postgres svc:5432"
	@echo "  TRINO_PORT=8084       Local port forwarded to Trino svc:8080"
	@echo "  NESSIE_PORT=19120     Local port forwarded to Nessie svc:19120"
	@echo "  MARQUEZ_PORT=5005     Local port forwarded to Marquez API svc:5000"
	@echo "  MARQUEZ_UI_PORT=3001  Local port forwarded to Marquez UI svc:3000"
	@echo "  DBT_INTERVAL=60       Seconds between dbt runs (dbt-loop)"
	@echo "  OPENLINEAGE_URL=http://localhost:5005  OpenLineage endpoint"
	@echo ""

.PHONY: dbt-run
dbt-run:
	@DBT_PROFILES_DIR=$(DBT_PROFILES_DIR) $(VENV)/bin/python -m dbt.cli.main run --project-dir $(DBT_PROJECT_DIR)

.PHONY: dbt-ol-run
dbt-ol-run:
	@OPENLINEAGE_URL=$(OPENLINEAGE_URL) \
	  OPENLINEAGE_NAMESPACE=$(OPENLINEAGE_NAMESPACE) \
	  OPENLINEAGE_DBT_JOB_NAME=$(OPENLINEAGE_DBT_JOB_NAME) \
	  OPENLINEAGE__TAGS__JOB__project=$(OPENLINEAGE_JOB_TAG_PROJECT) \
	  OPENLINEAGE__TAGS__JOB__layer=$(OPENLINEAGE_JOB_TAG_LAYER) \
	  OPENLINEAGE__TAGS__RUN__env=$(OPENLINEAGE_RUN_TAG_ENV) \
	  DBT_PROFILES_DIR=$(DBT_PROFILES_DIR) \
	  $(VENV)/bin/dbt-ol run --project-dir $(DBT_PROJECT_DIR) --profiles-dir $(DBT_PROFILES_DIR)

.PHONY: dbt-loop
dbt-loop:
	@echo ">> Running dbt-ol every $(DBT_INTERVAL)s (Ctrl+C to stop)"
	@while true; do \
	  $(MAKE) dbt-ol-run; \
	  sleep $(DBT_INTERVAL); \
	done
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
	@echo ">> Starting port-forwards (ingress-nginx -> :$(EDGE_PORT), argocd -> :$(ARGO_PORT), Keycloak -> :$(CLOAK_PORT), Grafana -> :$(GRFN_PORT), PostgreSQL -> :$(POST_PORT), Trino -> :$(TRINO_PORT), Nessie -> :$(NESSIE_PORT), Marquez API -> :$(MARQUEZ_PORT), Marquez UI -> :$(MARQUEZ_UI_PORT))"
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
	@# Keycloak
	@bash -c ' \
	  if lsof -nP -iTCP:$(CLOAK_PORT) -sTCP:LISTEN >/dev/null 2>&1; then \
	    echo "   Keycloak  :$(CLOAK_PORT) already listening"; \
	  else \
	    (kubectl -n keycloak port-forward svc/keycloak $(CLOAK_PORT):8080 >/dev/null 2>&1 & echo $$! > $(PIDDIR)/pf-cloak.pid); \
	    echo "   started Keycloak port-forward (pid $$(cat $(PIDDIR)/pf-cloak.pid))"; \
	  fi'
	@# Grafana
	@bash -c ' \
	  if lsof -nP -iTCP:$(GRFN_PORT) -sTCP:LISTEN >/dev/null 2>&1; then \
	    echo "   Grafana  :$(GRFN_PORT) already listening"; \
	  else \
	    (kubectl -n observability port-forward svc/grafana $(GRFN_PORT):3000 >/dev/null 2>&1 & echo $$! > $(PIDDIR)/pf-grfn.pid); \
	    echo "   started Grafana port-forward (pid $$(cat $(PIDDIR)/pf-grfn.pid))"; \
	  fi'
	@# PostgreSQL
	@bash -c ' \
	  if lsof -nP -iTCP:$(POST_PORT) -sTCP:LISTEN >/dev/null 2>&1; then \
	    echo "   PostgreSQL  :$(POST_PORT) already listening"; \
	  else \
	    (kubectl -n postgres port-forward svc/postgres $(POST_PORT):5432 >/dev/null 2>&1 & echo $$! > $(PIDDIR)/pf-post.pid); \
	    echo "   started PostgreSQL port-forward (pid $$(cat $(PIDDIR)/pf-post.pid))"; \
	  fi'
	@# Trino
	@bash -c ' \
	  if lsof -nP -iTCP:$(TRINO_PORT) -sTCP:LISTEN >/dev/null 2>&1; then \
	    echo "   Trino  :$(TRINO_PORT) already listening"; \
	  else \
	    (kubectl -n trino port-forward svc/trino $(TRINO_PORT):8080 >/dev/null 2>&1 & echo $$! > $(PIDDIR)/pf-trino.pid); \
	    echo "   started Trino port-forward (pid $$(cat $(PIDDIR)/pf-trino.pid))"; \
	  fi'
	@# Nessie
	@bash -c ' \
	  if lsof -nP -iTCP:$(NESSIE_PORT) -sTCP:LISTEN >/dev/null 2>&1; then \
	    echo "   Nessie  :$(NESSIE_PORT) already listening"; \
	  else \
	    (kubectl -n nessie port-forward svc/nessie $(NESSIE_PORT):19120 >/dev/null 2>&1 & echo $$! > $(PIDDIR)/pf-nessie.pid); \
	    echo "   started Nessie port-forward (pid $$(cat $(PIDDIR)/pf-nessie.pid))"; \
	  fi'
	@# Marquez API
	@bash -c ' \
	  if lsof -nP -iTCP:$(MARQUEZ_PORT) -sTCP:LISTEN >/dev/null 2>&1; then \
	    echo "   Marquez API  :$(MARQUEZ_PORT) already listening"; \
	  else \
	    (kubectl -n marquez port-forward svc/marquez $(MARQUEZ_PORT):5000 >/dev/null 2>&1 & echo $$! > $(PIDDIR)/pf-marquez.pid); \
	    echo "   started Marquez API port-forward (pid $$(cat $(PIDDIR)/pf-marquez.pid))"; \
	  fi'
	@# Marquez UI
	@bash -c ' \
	  if lsof -nP -iTCP:$(MARQUEZ_UI_PORT) -sTCP:LISTEN >/dev/null 2>&1; then \
	    echo "   Marquez UI  :$(MARQUEZ_UI_PORT) already listening"; \
	  else \
	    (kubectl -n marquez port-forward svc/marquez-web $(MARQUEZ_UI_PORT):3000 >/dev/null 2>&1 & echo $$! > $(PIDDIR)/pf-marquez-ui.pid); \
	    echo "   started Marquez UI port-forward (pid $$(cat $(PIDDIR)/pf-marquez-ui.pid))"; \
	  fi'

.PHONY: pf-stop
pf-stop:
	@echo ">> Stopping port-forwards"
	@bash -c ' \
	  for f in $(PIDDIR)/pf-ingress.pid $(PIDDIR)/pf-argocd.pid $(PIDDIR)/pf-cloak.pid $(PIDDIR)/pf-grfn.pid $(PIDDIR)/pf-post.pid $(PIDDIR)/pf-trino.pid $(PIDDIR)/pf-nessie.pid $(PIDDIR)/pf-marquez.pid $(PIDDIR)/pf-marquez-ui.pid; do \
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
	@echo "   expected: ingress localhost:$(EDGE_PORT), argocd localhost:$(ARGO_PORT), Keycloak localhost:${CLOAK_PORT}, Grafana localhost:${GRFN_PORT}, PostgreSQL localhost:${POST_PORT}, Trino localhost:${TRINO_PORT}, Nessie localhost:${NESSIE_PORT}, Marquez API localhost:${MARQUEZ_PORT}, Marquez UI localhost:${MARQUEZ_UI_PORT}"
	@bash -c ' \
	  for p in $(EDGE_PORT) $(ARGO_PORT) $(CLOAK_PORT) $(GRFN_PORT) $(POST_PORT) $(TRINO_PORT) $(NESSIE_PORT) $(MARQUEZ_PORT) $(MARQUEZ_UI_PORT); do \
	    if lsof -nP -iTCP:$$p -sTCP:LISTEN >/dev/null 2>&1; then \
	      echo "   port $$p: LISTENING"; \
	    else \
	      echo "   port $$p: not listening"; \
	    fi; \
	  done'
	@bash -c ' \
	  for f in $(PIDDIR)/pf-ingress.pid $(PIDDIR)/pf-argocd.pid $(PIDDIR)/pf-cloak.pid $(PIDDIR)/pf-grfn.pid $(PIDDIR)/pf-post.pid $(PIDDIR)/pf-trino.pid $(PIDDIR)/pf-nessie.pid $(PIDDIR)/pf-marquez.pid $(PIDDIR)/pf-marquez-ui.pid; do \
	    if [ -f $$f ]; then echo "   $$(basename $$f): $$(cat $$f)"; else echo "   $$(basename $$f): <none>"; fi; \
	  done'

.PHONY: argocd-pass
argocd-pass:
	@kubectl -n argocd get secret argocd-initial-admin-secret \
	  -o jsonpath='{.data.password}' | base64 -d; echo

.PHONY: slot
slot:
	@KC_PASS=$(KC_PASS) python3 client/machine.py

.PHONY: init
init:
	@if [ ! -d "$(VENV)" ]; then \
		echo ">> Creating virtualenv in $(VENV)"; \
		$(PYTHON) -m venv $(VENV); \
	else \
		echo ">> Virtualenv already exists"; \
	fi
	@echo ">> Installing requirements"
	@$(PIP) install -r requirements.txt

.PHONY: shell
shell:
	@echo ">> Run:"
	@echo "   source $(VENV)/bin/activate"

.PHONY: clean
clean:
	rm -rf $(VENV)
