# deviceOIDC

Envoy + Keycloak (OIDC) + ArgoCD (GitOps) on local k3s / Colima

This repository is a **local, fully reproducible OIDC + API Gateway reference setup** on Kubernetes.

Focus:

* clarity over abstraction
* gateway-first security
* GitOps as the control plane
* observability as a first-class concern

No token introspection.
No backend auth logic.
No magic sidecars.

---

## Why this exists

This repo is a **learning and architecture sandbox** for:

* API Gateway–centric security
* Offline JWT validation (JWKS)
* Machine / device authentication patterns
* Declarative GitOps workflows with ArgoCD
* Building an LGTM observability stack bottom-up (logs → metrics → traces)

Everything runs **locally** (Colima + k3s) so nothing is hidden.

---

## Target architecture (north star)

* **Envoy**

  * API Gateway
  * Validates JWTs offline using Keycloak JWKS
  * Blocks unauthorized traffic before it reaches services

* **Keycloak**

  * OIDC / OAuth2 Identity Provider
  * Issues access tokens
  * Publishes JWKS

* **Hello service (Node.js)**

  * No auth logic
  * No Keycloak dependency
  * Purely business-agnostic

* **ArgoCD**

  * App-of-Apps pattern
  * Declarative cluster state

* **Observability (LGTM)**

  * Loki + Promtail: **working**
  * Grafana / Tempo / Mimir: **scaffolded, not wired yet**

---

## What works today

### Security / Gateway

* Envoy validates JWTs offline
* No token introspection
* Keycloak key rotation works via JWKS
* `hello` without token → 401
* `hello` with valid token → 200

### GitOps

* Everything is applied via ArgoCD
* `kubectl` is only used for debugging

### Logging (Loki)

* Promtail runs as DaemonSet
* Reads Docker JSON logs
* Loki ingests correctly
* Old log rejection and rate limits understood and fixed
* Logs queryable by labels:

  * `namespace`
  * `app`
  * `pod`
  * `container`
  * `node`

---

## What is intentionally NOT done yet

* Envoy access logs → Loki
* Keycloak structured logs → Loki
* Metrics via Mimir
* Traces via Tempo
* Grafana dashboards
* Cross-signal correlation

This is deliberate. Logs come first.

---

## Cluster layout

### Namespaces

| Namespace     | Purpose                               |
| ------------- | ------------------------------------- |
| argocd        | GitOps controllers + UI               |
| ingress-nginx | Ingress controller                    |
| gateway       | Envoy                                 |
| keycloak      | Keycloak                              |
| postgres      | Database for Keycloak                 |
| hello         | Demo service                          |
| observability | Loki, Promtail, Grafana, Tempo, Mimir |

---

## Routing model

Host-based routing everywhere:

* `hello.local`
* `keycloak.local`

Default access mode: port-forward to the ingress controller (avoids Colima/macOS networking weirdness).

### Default access mode: port-forward

This avoids macOS / Colima networking issues - achieved with

```bash
make pf-status # gives the status of port forwarding
make pf-start  # starts port forwarding for ingress, argocd, grafana, and keycloak
make pf-stop   # stops port forwarding
```

| Component | URL                                            |
| --------- | ---------------------------------------------- |
| ArgoCD    | [http://argoargocd.local:8080](http://argocd.local:8080) |
| Keycloak  | [http://keycloak.local:8082/admin](http://keycloak.local:8082/admin) |
| Grafana   | [http://grafana.local:3000](http://grafana.local:3000) |
| MinIO S3  | [http://localhost:9000](http://localhost:9000) |
| MinIO UI  | [http://localhost:9001](http://localhost:9001) |

---

## Dataplatform UI Map (clickable)

The diagram links to the local UIs. It also shows the flow from source DB
through CDC, streaming, Iceberg, and query/lineage layers.

```mermaid
flowchart LR
  %% =========================
  %% UIs (clickable)
  %% =========================
  UI_POSTGRES["Postgres (psql)\nlocalhost:5432"]
  UI_MINIO["MinIO Console\nhttp://localhost:9001"]
  UI_TRINO["Trino UI\nhttp://localhost:8084/ui"]
  UI_NESSIE["Nessie API\nhttp://localhost:19120/api/v1"]
  UI_MARQUEZ["Marquez UI\nhttp://localhost:3001"]
  UI_GRAFANA["Grafana\nhttp://localhost:3000"]
  UI_ARGO["ArgoCD\nhttp://localhost:8080"]

  click UI_MINIO "http://localhost:9001" "MinIO Console"
  click UI_TRINO "http://localhost:8084/ui" "Trino UI"
  click UI_NESSIE "http://localhost:19120/api/v1" "Nessie API"
  click UI_MARQUEZ "http://localhost:3001" "Marquez UI"
  click UI_GRAFANA "http://localhost:3000" "Grafana"
  click UI_ARGO "http://localhost:8080" "ArgoCD"

  %% =========================
  %% Data Flow
  %% =========================
  STATE["State service\n(status generator)"]
  PG[(Postgres\nschema: dataplatform)]
  DBZ["Debezium\n(Kafka Connect)"]
  RP["Redpanda / Kafka"]
  ICEBERG["Iceberg Sink\n(Kafka Connect)"]
  NESSIE["Nessie\ncatalog"]
  MINIO["MinIO\nS3 warehouse"]
  TRINO["Trino\nSQL on Iceberg"]
  DBT["dbt (local)\nSilver/Gold models"]
  MARQUEZ["Marquez\nLineage"]

  STATE --> PG --> DBZ --> RP --> ICEBERG --> MINIO
  ICEBERG --> NESSIE
  NESSIE --> TRINO
  DBT --> TRINO
  DBT --> MARQUEZ
  TRINO --> UI_TRINO
  NESSIE --> UI_NESSIE
  MINIO --> UI_MINIO
  MARQUEZ --> UI_MARQUEZ
  UI_GRAFANA --- RP
  UI_ARGO --- STATE
```

In /etc/hosts, the *.local hostnames are pointing to loopback 127.0.0.1. Routing to backends is done via the Host header.

### Keycloak Access Model (UI vs OIDC)

Keycloak serves two very different consumers:
- Humans (browser / admin UI): use direct port-forward to Keycloak service [http://keycloak.local:8082/admin](http://keycloak.local:8082/admin)
- Machines (slot machine / scripts): go through Envoy (policy + JWT + observability)

```mermaid
flowchart LR
  %% =========================
  %% External (your laptop)
  %% =========================
  subgraph LAPTOP["Laptop (macOS)"]
    B["Browser (Human)"]
    S["Slotmachine client (Python)"]
    PF_I["make pf-start<br/>port-forward ingress-nginx<br/>localhost:8081 → svc/ingress-nginx:80"]
    PF_K["(optional) port-forward Keycloak<br/>keycloak.local:8082 → svc/keycloak:8080"]
  end

  %% =========================
  %% Kubernetes cluster
  %% =========================
  subgraph K8S["k3s on Colima (Kubernetes)"]
    N["ingress-nginx controller"]
    ING["Ingress (gateway/hello)<br/>hosts: hello.local, keycloak.local<br/>backend: svc/envoy:80"]
    E["Envoy (gateway)<br/>host-based routing + JWT filter"]
    H["Hello service (hello)"]
    KC["Keycloak (keycloak)<br/>OIDC + Admin Console"]
  end

  %% --- Browser path (Admin UI) ---
  B -->|open http://keycloak.local:8082/admin| PF_K --> KC
  KC -->|302 /admin → /admin/master/console| B

  %% --- Machine path (OIDC via Envoy) ---
  S -->|HTTP to localhost:8081<br/>Host: keycloak.local| PF_I --> N --> ING --> E --> KC
  KC -->|OIDC endpoints<br/>/realms/.../token, /certs, /.well-known| S

  %% --- Regular app traffic through Envoy ---
  S -->|HTTP to localhost:8081<br/>Host: hello.local<br/>Authorization: Bearer <token>| PF_I --> N --> ING --> E --> H

  %% Labels to make intent obvious
  classDef human fill:#f7f7f7,stroke:#333,stroke-width:1px;
  classDef machine fill:#eef7ff,stroke:#333,stroke-width:1px;
  class B,PF_K human;
  class S,PF_I machine;
```

**Admin UI (browser):**
- You use keycloak.local:8082 (direct port-forward to Keycloak)
- No Envoy, no NGINX host routing, no “why is my console redirecting to Narnia?”

**OIDC token minting (slotmachine / scripts):**
- You call keycloak.local:8081 (port-forward to ingress-nginx)
- You set Host: keycloak.local
- NGINX routes to Envoy
- Envoy routes to Keycloak
- You get tokens + JWKS like a grown-up service would

#### Keycloak UI

**Admin Console (human access)**
Requires Keycloak port-forward enabled.
- Start:
  - pf-start if you want it automated
- Open:
  - [http://keycloak.local:8082/admin](http://keycloak.local:8082/admin)

**OIDC endpoints (machine access via Envoy)**
These are reached through the edge port-forward (keycloak.local:8081) + Host header:
- Issuer:
  - curl -H 'Host: keycloak.local' http://keycloak.local:8081/realms/deviceoidc
- Token:
  - curl -H 'Host: keycloak.local' http://keycloak.local:8081/realms/deviceoidc/protocol/openid-connect/token
- JWKS:
  - curl -H 'Host: keycloak.local' http://keycloak:8081/realms/deviceoidc/protocol/openid-connect/certs

---

## Important endpoints

### Hello API

[http://hello.local/hello](http://hello.local/hello)

### Keycloak UI

[http://keycloak.local/admin](http://keycloak.local:8082/admin)

### OIDC endpoints

* Issuer
  [http://keycloak.local/realms/deviceoidc](http://keycloak.local/realms/deviceoidc)

* Token
  [http://keycloak.local/realms/deviceoidc/protocol/openid-connect/token](http://keycloak.local/realms/deviceoidc/protocol/openid-connect/token)

* JWKS
  [http://keycloak.local/realms/deviceoidc/protocol/openid-connect/certs](http://keycloak.local/realms/deviceoidc/protocol/openid-connect/certs)

---

## Expected behavior (smoke tests)

Hello without token (blocked):

curl -i -H "Host: hello.local" [http://hello.local:8081/hello](http://hello.local:8081/hello)
→ 401

Hello with token (allowed):

curl -i 
-H "Host: hello.local" 
-H "Authorization: Bearer <token>" 
[http://hello.local:8081/hello](http://hello.local:8081/hello)
→ 200

```mermaid
flowchart LR
    subgraph Local_Machine["Developer Machine"]
        Browser["Browser"]
        Slot["Slot Machine (Python)"]
    end

    subgraph PortForward["kubectl port-forward"]
        PF_Keycloak["Keycloak Admin UI :8082"]
    end

    subgraph Ingress["NGINX Ingress"]
        NGINX["ingress-nginx"]
    end

    subgraph Gateway["Gateway Namespace"]
        Envoy["Envoy API Gateway"]
    end

    subgraph Identity["Keycloak Namespace"]
        KC["Keycloak"]
    end

    subgraph Services["Services"]
        Hello["Hello Service"]
    end

    %% Admin access (out-of-band)
    Browser -->|http://keycloak.local:8082/admin| PF_Keycloak
    PF_Keycloak --> KC

    %% Machine flow
    Slot -->|POST /token\nHost: keycloak.local| NGINX
    NGINX --> Envoy
    Envoy --> KC

    Slot -->|POST /hello\nHost: hello.local\nBearer token| NGINX
    NGINX --> Envoy
    Envoy --> Hello
```

---

## Doctor script (mandatory)

The `doctor.sh` script is the **single source of truth** for system health.

It verifies:

* cluster sanity
* ingress routing
* Keycloak OIDC endpoints
* Envoy presence
* Loki ingestion
* optional token mint + API call

Run:

./scripts/doctor.sh

With token test:

KCPASS=secret ./scripts/doctor.sh

---

## Observability status (LGTM)

### Logs

* Promtail → Loki works
* Docker JSON logs ingested
* Labels are consistent and queryable

### Metrics / Traces

* Configs exist
* Not connected yet
* Will be added incrementally

---

## Next steps (deliberate order)

1. Envoy access logs → Loki (JSON)
2. Keycloak structured logs → Loki
3. Hello service structured logs
4. Grafana log dashboards
5. Metrics via Mimir
6. Traces via Tempo
7. Correlation across signals

---

## Design principles

* Gateway owns security
* Services stay dumb
* No introspection
* Observability is mandatory
* Git is the source of truth
* If it works locally, it scales conceptually

---

## Status

The system is **intentionally incomplete**.

What exists is:

* correct
* observable
* explainable

# Dummy machine clients

Realized through python script under ./client/machine.py

Use and setup of python:

```bash
make init
make shell
deactivate
make clean
``` 

Minimal client calls (defaults cover most settings):

```bash
# password grant (user/password)
./client/machine.py --password "<KC_PASS>"

# private_key_jwt (client credentials)
./client/machine_key.py --private-key slot-machine.private.pem
```

Generate a client_assertion for curl:

```bash
CLIENT_ASSERTION="$(./client/client_assertion.py --private-key slot-machine.private.pem)"
```

Use with curl (client_credentials + private_key_jwt):

```bash
curl -s -H 'Host: keycloak.local' \
  -d 'grant_type=client_credentials' \
  -d 'client_id=slot-machine' \
  -d 'client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer' \
  -d "client_assertion=${CLIENT_ASSERTION}" \
  http://keycloak.local:8081/realms/deviceoidc/protocol/openid-connect/token
```

Optional overrides if needed:

```bash
./client/machine.py --ingress-base http://localhost:8081 --realm deviceoidc \
  --client-id deviceoidc-cli --username test --machine-id slot-001 --bet 1 --debug

./client/machine_key.py --ingress-base http://localhost:8081 --realm deviceoidc \
  --client-id slot-machine --private-key slot-machine.private.pem --kid "<KID>" \
  --machine-id slot-001 --bet 1 --debug
```

Everything else will be added step by step.

# Dataplatform on-premise demo

### 🧱 Initial Database Setup for Data Platform

We use the existing PostgreSQL instance from the OIDC demo to host
our data platform tables. These are maintained in a dedicated schema
(`dataplatform`) to avoid interference with the Keycloak operational data.
The schema includes lookup tables (veranstalter, betriebsstaette, geraet,
player, device_assignment) and the fact table `status_abfrage`.

To initialize the database, execute:

```bash
psql \
  -h localhost \
  -p 5432 \
  -U keycloak \
  -d keycloak \
  -f .scripts/dataplatform_init.sql
```

### State service (status generator)

The `state` service simulates status probes by inserting rows into
`dataplatform.status_abfrage` on a fixed interval. It also seeds
lookup tables for veranstalter, betriebsstaetten, geraete, players,
and device assignments.

Behavior:
* Seeds lookup tables from `services/state/*.js` on startup (idempotent)
* Picks a random player from `services/state/players.js`
* Picks a random active device assignment from `services/state/device_assignments.js`
* Inserts a row every 10 seconds
* Occasionally reassigns a device to a new betriebsstaette to simulate resale

Notes:
* Connection is configured via `POSTGRES_*` env vars in `manifests/state/deployment.yaml`
* Data lives in the `dataplatform` schema inside the shared Postgres instance

### CDC pipeline overview

```mermaid
flowchart LR
  State[State service] --> Postgres[(Postgres)]
  Postgres --> Debezium[Debezium CDC]
  Debezium --> Redpanda[Redpanda/Kafka]
  Redpanda --> Iceberg[Iceberg sink]
  Iceberg --> MinIO[(MinIO warehouse)]
```

### Object storage (MinIO)

MinIO provides the S3-compatible blob storage used later by Iceberg.
Manifests live in `manifests/minio`.

Default credentials (demo only):
* user: `minioadmin`
* password: `minioadmin`

Access (port-forward):

```bash
kubectl -n minio port-forward svc/minio 9000:9000 9001:9001
```

Then open:
* S3 API: http://localhost:9000
* Console: http://localhost:9001

### Kafka/Redpanda + Connect (CDC backbone)

For the PoC we run a single-node Kafka-compatible broker using Redpanda
to reduce operational overhead. On a production cluster, this should be
replaced with a real Kafka deployment (multi-broker, proper storage and
replication).

Everything runs in the `kafka` namespace.
Manifests live in `manifests/kafka`.

Services:
* Broker bootstrap: `redpanda.kafka.svc.cluster.local:9092`
* Connect REST: `connect.kafka.svc.cluster.local:8083`

Sanity check (in-cluster pub/sub):

```bash
kubectl -n kafka exec redpanda-0 -- sh -lc "rpk topic create sanity -X brokers=redpanda.kafka.svc.cluster.local:9092"
kubectl -n kafka exec redpanda-0 -- sh -lc "echo hello | rpk topic produce sanity -X brokers=redpanda.kafka.svc.cluster.local:9092"
kubectl -n kafka exec redpanda-0 -- sh -lc "rpk topic consume sanity -n 1 -X brokers=redpanda.kafka.svc.cluster.local:9092"
kubectl -n kafka exec redpanda-0 -- sh -lc "rpk topic delete sanity -X brokers=redpanda.kafka.svc.cluster.local:9092"
```

### Debezium CDC (Postgres -> Redpanda)

Create the connector (from repo root):

```bash
kubectl -n kafka exec deploy/connect -- sh -lc \
  "cat <<'JSON' | curl -sS -X POST -H 'Content-Type: application/json' \
  --data-binary @- http://localhost:8083/connectors
{
  \"name\": \"dataplatform-postgres-connector\",
  \"config\": {
    \"connector.class\": \"io.debezium.connector.postgresql.PostgresConnector\",
    \"tasks.max\": \"1\",
    \"database.hostname\": \"postgres.postgres.svc.cluster.local\",
    \"database.port\": \"5432\",
    \"database.user\": \"keycloak\",
    \"database.password\": \"keycloak\",
    \"database.dbname\": \"keycloak\",
    \"database.server.name\": \"dataplatform\",
    \"topic.prefix\": \"dataplatform\",
    \"schema.include.list\": \"dataplatform\",
    \"table.include.list\": \"dataplatform.status_abfrage,dataplatform.veranstalter,dataplatform.betriebsstaette,dataplatform.geraet,dataplatform.device_assignment,dataplatform.player\",
    \"plugin.name\": \"pgoutput\",
    \"snapshot.mode\": \"initial\",
    \"publication.autocreate.mode\": \"filtered\"
  }
}
JSON"
```

List connectors:

```bash
kubectl -n kafka exec deploy/connect -- sh -lc \
  "curl -sS http://localhost:8083/connectors"
```

Check connector status:

```bash
kubectl -n kafka exec deploy/connect -- sh -lc \
  "curl -sS http://localhost:8083/connectors/dataplatform-postgres-connector/status"
```

Consume CDC events (in-cluster):

```bash
kubectl -n kafka exec redpanda-0 -- sh -lc \
  "rpk topic consume dataplatform.dataplatform.status_abfrage -n 1 -X brokers=redpanda.kafka.svc.cluster.local:9092"
```

Notes:
* Topic naming is `<topic.prefix>.<schema>.<table>` (for example: `dataplatform.dataplatform.status_abfrage`)
* `snapshot.mode=initial` emits a one-time snapshot (`op: r`) followed by live changes (`op: c/u/d`)

### Grafana (Loki) – CDC visibility

Grafana is wired to Loki. You can inspect Debezium + Iceberg activity via logs.

Open Grafana:
* http://localhost:3000

Explore → Loki, then run queries like:

```logql
{namespace="kafka", app="connect"} |= "WorkerSourceTask"
{namespace="kafka", app="connect"} |= "ERROR"
{namespace="kafka", app="iceberg-connect"} |= "Successfully committed to table"
{namespace="kafka", app="iceberg-connect"} |= "ERROR"
```

If you see no data, expand a log line and confirm the actual labels (namespace/app/pod).

### Iceberg sink (Redpanda -> MinIO)
Note on "AWS" config: Iceberg uses Hadoop S3A to talk to S3-compatible storage. MinIO speaks S3, so the settings look like AWS (`fs.s3a.*`, access/secret keys, region), but they are just the S3 protocol knobs pointed at MinIO.

Create the MinIO bucket (one-time):

```bash
kubectl -n minio apply -f manifests/minio/warehouse-job.yaml
```

Iceberg sink runs in a dedicated Kafka Connect deployment:
* Connect REST: `iceberg-connect.kafka.svc.cluster.local:8083`
* Image: `docker.io/h4rkon/iceberg-connect:latest` (built from the public Databricks Iceberg Connect runtime release)

Create the Iceberg sink connector:

```bash
kubectl -n kafka exec deploy/iceberg-connect -- sh -lc \
  "cat <<'JSON' | curl -sS -X POST -H 'Content-Type: application/json' \
  --data-binary @- http://localhost:8083/connectors
{
  \"name\": \"iceberg-sink\",
  \"config\": {
    \"connector.class\": \"io.tabular.iceberg.connect.IcebergSinkConnector\",
    \"tasks.max\": \"1\",
    \"topics\": \"dataplatform.dataplatform.status_abfrage,dataplatform.dataplatform.veranstalter,dataplatform.dataplatform.betriebsstaette,dataplatform.dataplatform.geraet,dataplatform.dataplatform.device_assignment,dataplatform.dataplatform.player\",
    \"iceberg.catalog.type\": \"nessie\",
    \"iceberg.catalog.uri\": \"http://nessie.nessie.svc.cluster.local:19120/api/v1\",
    \"iceberg.catalog.ref\": \"main\",
    \"iceberg.catalog.warehouse\": \"s3a://warehouse/\",
    \"iceberg.catalog.io-impl\": \"org.apache.iceberg.hadoop.HadoopFileIO\",
    \"iceberg.catalog.hadoop.fs.s3a.endpoint\": \"http://minio.minio.svc.cluster.local:9000\",
    \"iceberg.catalog.hadoop.fs.s3a.connection.ssl.enabled\": \"false\",
    \"iceberg.catalog.hadoop.fs.s3a.path.style.access\": \"true\",
    \"iceberg.catalog.hadoop.fs.s3a.access.key\": \"minioadmin\",
    \"iceberg.catalog.hadoop.fs.s3a.secret.key\": \"minioadmin\",
    \"iceberg.catalog.hadoop.fs.s3a.aws.credentials.provider\": \"org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider\",
    \"iceberg.catalog.hadoop.fs.s3a.endpoint.region\": \"us-east-1\",
    \"iceberg.catalog.hadoop.fs.s3a.region\": \"us-east-1\",
    \"iceberg.tables\": \"dataplatform.status_abfrage,dataplatform.veranstalter,dataplatform.betriebsstaette,dataplatform.geraet,dataplatform.device_assignment,dataplatform.player\",
    \"iceberg.tables.auto-create-enabled\": \"true\",
    \"iceberg.tables.auto-create-props.write.format.default\": \"parquet\"
  }
}
JSON"
```

Check sink status:

```bash
kubectl -n kafka exec deploy/iceberg-connect -- sh -lc \
  "curl -sS http://localhost:8083/connectors/iceberg-sink/status"
```

### Catalog + lineage (Nessie + Marquez)

Nessie provides an Iceberg catalog with versioned metadata (branchable table history).
Marquez stores OpenLineage events to visualize data lineage.

### How the CDC pipeline is wired (answering “what goes where”)

* Debezium reads Postgres WAL → publishes CDC events to Redpanda topics.
* Iceberg sink (Kafka Connect) consumes those topics → writes Iceberg tables.
* MinIO is the S3-compatible storage for Iceberg data + metadata.
* Nessie is the Iceberg catalog (table metadata + versioned history).
* Trino queries Iceberg tables through Nessie.

### How to inspect Iceberg content (no native UI)

There’s no dedicated Iceberg UI in this stack. Use:

**Trino (recommended)**
```sql
SHOW SCHEMAS FROM iceberg;
SHOW TABLES FROM iceberg.dataplatform;
SELECT count(*) FROM iceberg.dataplatform.status_abfrage;
SELECT after.vorname, after.nachname, after.status_ts
FROM iceberg.dataplatform.status_abfrage
LIMIT 5;
```

**Nessie API (catalog metadata)**
* http://localhost:19120/api/v1/trees
* http://localhost:19120/api/v1/trees/main/namespaces

**MinIO Console (raw files)**
* http://localhost:9001
* Bucket: `warehouse/`
* You will see table folders like `dataplatform/status_abfrage_...`

Deploy:

```bash
kubectl apply -f apps/nessie-app.yaml
kubectl apply -f apps/marquez-app.yaml
```

Port-forward Nessie:

```bash
kubectl -n nessie port-forward svc/nessie 19120:19120
```

Create the Iceberg namespace in Nessie (one-time):

```bash
kubectl -n trino port-forward svc/trino 8080:8080
curl -sS -H 'X-Trino-User: admin' -X POST --data 'CREATE SCHEMA IF NOT EXISTS iceberg.dataplatform' \
  http://localhost:8080/v1/statement
```

Port-forward Marquez (API + UI):

```bash
kubectl -n marquez port-forward svc/marquez 5005:5000
kubectl -n marquez port-forward svc/marquez-web 3000:3000
```

Notes:
* Trino is configured to use Nessie via `manifests/trino/catalog-iceberg.yaml`.
* The Iceberg sink uses Nessie when created from `.scripts/connectors/iceberg-connector.json`.
* For dbt lineage, install `openlineage-dbt` (provides `dbt-ol`) and set `OPENLINEAGE_URL=http://localhost:5005`.

### Trino (SQL on Iceberg)

Trino provides SQL access to the Iceberg tables stored in MinIO.
Manifests live in `manifests/trino`, and the Argo app is `apps/trino-app.yaml`.

Port-forward Trino:

```bash
kubectl -n trino port-forward svc/trino 8080:8080
```

Example queries:

```sql
SHOW SCHEMAS FROM iceberg;
SHOW TABLES FROM iceberg.dataplatform;
SELECT * FROM iceberg.dataplatform.status_abfrage LIMIT 5;
```

Interactive Trino query runner (HTTP):

```bash
.python/bin/python .scripts/trino_query.py
```

Then type a SQL statement, for example:

```sql
SELECT * FROM iceberg.silver.status_abfrage LIMIT 5;
```

### dbt (silver layer)

The `dbt/` folder contains a minimal dbt project that flattens CDC
envelopes into silver tables.
Silver models:
* `dbt/models/silver/status_abfrage.sql`
* `dbt/models/silver/veranstalter.sql`
* `dbt/models/silver/betriebsstaette.sql`
* `dbt/models/silver/geraet.sql`
* `dbt/models/silver/device_assignment.sql`
* `dbt/models/silver/player.sql`
The model is incremental (merge on `unique_identifier`) and only processes
rows newer than the latest `cdc_ts_ms` in the silver table. Use a full refresh
when you want a complete rebuild.
Note: Trino Iceberg + Nessie does not support views, so the model sets
`views_enabled=false` to use temp tables during incremental merges.

**What “silver” means here**
Silver is a flattened clone of the original Postgres table, built from CDC:
* CDC tables in Iceberg store `before/after/op` envelopes.
* Silver extracts `after.*` into a clean, queryable table that mirrors the source schema.
* Deletes can be handled by `op='d'` (depending on the model).

Quick start (local dbt-trino):

```bash
pip install dbt-trino openlineage-dbt
cp dbt/profiles.yml.example dbt/profiles.yml
DBT_PROFILES_DIR=dbt dbt --project-dir dbt run

# Full rebuild
DBT_PROFILES_DIR=dbt dbt --project-dir dbt run --full-refresh

# With OpenLineage -> Marquez
OPENLINEAGE_URL=http://localhost:5005 OPENLINEAGE_NAMESPACE=dataplatform \
  DBT_PROFILES_DIR=dbt dbt-ol run --project-dir dbt
```

Make targets (uses defaults from `Makefile` for OpenLineage job name + tags):

```bash
make dbt-run
make dbt-ol-run
DBT_INTERVAL=60 make dbt-loop
```

### dbt (gold layer)

Gold models build aggregated, queryable views on top of the silver table.

Models:
* `dbt/models/gold/veranstalter_query_counts.sql` - counts per `veranstalter_id`
* `dbt/models/gold/veranstalter_device_overview.sql` - counts by `veranstalter_id`,
  `betriebsstaette_id`, `geraete_id`

Optional dbt vars (CDC time window + optional veranstalter filter):
* `from_cdc_ts_ms` (inclusive)
* `until_cdc_ts_ms` (inclusive)
* `veranstalter_id`

Examples:

```bash
# Full gold build (all data)
DBT_PROFILES_DIR=dbt dbt --project-dir dbt run --select gold

# Filter by timeframe (epoch ms)
DBT_PROFILES_DIR=dbt dbt --project-dir dbt run --select gold \
  --vars '{"from_cdc_ts_ms": 1770550000000, "until_cdc_ts_ms": 1770560000000}'

# Filter by veranstalter_id
DBT_PROFILES_DIR=dbt dbt --project-dir dbt run --select gold \
  --vars '{"veranstalter_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}'
```

Sample Trino queries:

```sql
SELECT * FROM iceberg.gold.veranstalter_query_counts ORDER BY query_count DESC;
SELECT * FROM iceberg.gold.veranstalter_device_overview ORDER BY veranstalter_id, betriebsstaette_id, geraete_id;
```

### End-to-end demo status (CDC → Bronze → Silver → Gold)

At this point the pipeline is complete:
* Postgres → Debezium snapshot + CDC → Redpanda topics → Iceberg (bronze)
* dbt reads bronze CDC envelopes → writes silver (flattened clone)
* dbt builds gold aggregates

Example full refresh run (local):

```bash
DBT_PROFILES_DIR=dbt dbt --project-dir dbt run --full-refresh
```

Example results (from a successful run):
* `silver.status_abfrage`: 47,610 rows
* `silver.device_assignment`: 4,793 rows
* `silver.player`: 20 rows
* `silver.geraet`: 10 rows
* `silver.betriebsstaette`: 10 rows
* `silver.veranstalter`: 4 rows
* `gold.veranstalter_device_overview`: 100 rows
* `gold.veranstalter_query_counts`: 4 rows

Verify in Trino:

```sql
SELECT count(*) FROM iceberg.silver.status_abfrage;
SELECT * FROM iceberg.silver.status_abfrage LIMIT 5;
SELECT * FROM iceberg.gold.veranstalter_query_counts;
```

### How to verify bronze (CDC) and silver data

**Bronze (raw CDC in Iceberg)**
```sql
SELECT after.unique_identifier, after.vorname, after.nachname, after.status_ts
FROM iceberg.dataplatform.status_abfrage
LIMIT 5;
```

**Silver (flattened clone)**
```sql
SELECT unique_identifier, vorname, nachname, status_ts
FROM iceberg.silver.status_abfrage
LIMIT 5;
```
