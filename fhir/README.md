# Local HAPI FHIR server

PostgreSQL-backed [HAPI FHIR](https://hapifhir.io/) for local development on `feat/fhir-integration` and later phases.

**Base URL:** `http://localhost:8080/fhir`

## Layout

- `docker-compose.fhir.yml` — HAPI (`hapiproject/hapi:v7.0.0`) + Postgres 16
- `application.yaml` — Postgres datasource + `HapiFhirPostgresDialect` (required for correct schema)
- `pgdata/` — persistent Postgres files (gitignored)

## Start / stop

From the repo root:

```bash
make fhir-up    # docker compose -f fhir/docker-compose.fhir.yml up -d
make fhir-down  # docker compose -f fhir/docker-compose.fhir.yml down
```

First startup can take a minute while HAPI initializes the schema.

## Smoke checks

```bash
curl -s http://localhost:8080/fhir/metadata | head
curl -s http://localhost:8080/fhir/Patient
```

Expect HTTP 200 with a `CapabilityStatement` and an empty searchset `Bundle` (no patients until Phase 1).

## Data persistence

Postgres data is stored in `fhir/pgdata/` (gitignored). Credentials (`hapi` / `hapi`) are for local dev only.
