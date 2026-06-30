# Local HAPI FHIR server

PostgreSQL-backed [HAPI FHIR](https://hapifhir.io/) for local development on `feat/fhir-integration`.

**Base URL:** `http://localhost:8080/fhir`

## Layout

- `docker-compose.fhir.yml` — HAPI (`hapiproject/hapi:v7.0.0`) + Postgres 16
- `application.yaml` — Postgres datasource + `HapiFhirPostgresDialect`
- `fhir_loader/load_synthea.py` — typed loader (httpx + retries) for Synthea bundles
- `fhir_client/` — typed read client (`FhirClient`) for all FHIR interactions in later phases
- `pgdata/` — persistent Postgres files (gitignored)

Gitignored at repo root: `synthea/` (prebuilt JAR + generated output).

## Prerequisites

- Docker Desktop (HAPI)
- Java 17+ (`java -version`) for the Synthea prebuilt JAR

## Start / stop HAPI

```bash
make fhir-up
make fhir-down
```

First startup can take a minute while HAPI initializes the schema.

## Generate synthetic patients (Synthea prebuilt JAR)

Downloads `synthea-with-dependencies.jar` from [official releases](https://github.com/synthetichealth/synthea/releases) into gitignored `synthea/`, then generates FHIR R4 transaction bundles:

```bash
make generate-synthea    # default SYNTHEA_POP=100, SYNTHEA_STATE=Massachusetts
```

Smaller test batch:

```bash
make generate-synthea SYNTHEA_POP=5
```

Equivalent manual commands:

```bash
make download-synthea
cd synthea && java -jar synthea-with-dependencies.jar -p 100 --exporter.fhir.export true Massachusetts
```

Output: `synthea/output/fhir/` (`hospitalInformation*.json`, `practitionerInformation*.json`, then one bundle per patient).

## Load into HAPI

Upload bundles in dependency order (Organization → Practitioner → patients):

```bash
make load-synthea
# or: uv run load-synthea
# or: FHIR_BASE_URL=http://localhost:8080/fhir uv run load-synthea synthea/output/fhir
```

## Verify

```bash
curl -s 'http://localhost:8080/fhir/Patient?_summary=count'
curl -s 'http://localhost:8080/fhir/Observation?_summary=count'
curl -s 'http://localhost:8080/fhir/Condition?_summary=count'
curl -s 'http://localhost:8080/fhir/MedicationRequest?_summary=count'
```

Pick a patient id from the count response or search, then:

```bash
curl -s 'http://localhost:8080/fhir/Patient/{id}'
```

## Smoke checks (empty server)

```bash
curl -s http://localhost:8080/fhir/metadata | head
curl -s http://localhost:8080/fhir/Patient
```

## Data persistence

Postgres data is stored in `fhir/pgdata/` (gitignored). HAPI credentials (`hapi` / `hapi`) are for local dev only.
