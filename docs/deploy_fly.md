# Deploying clinical-data (Server A) on Fly.io

This guide deploys the **clinical-data** MCP server over **StreamableHTTP** with bearer auth, health checks, and in-memory metrics. The agent connects via `CLINICAL_DATA_URL` + `CLINICAL_DATA_AUTH_TOKEN`; clinic-ops stays local stdio for now.

## Prerequisites

- [Fly CLI](https://fly.io/docs/hands-on/install-flyctl/) installed and authenticated (`fly auth login`)
- Docker (Fly builds from `Dockerfile`)

## One-time setup

```bash
cd clinical-ops-copilot

# Create the app (skip if fly.toml app name is taken — edit app = in fly.toml)
fly apps create clinical-data-mcp

# Required: shared secret for MCP HTTP (never commit this)
fly secrets set CLINICAL_DATA_AUTH_TOKEN="$(openssl rand -hex 32)"

# Optional: only if EXTRACTOR_BACKEND=real in production (incurs Claude cost per extract call)
# fly secrets set ANTHROPIC_API_KEY="sk-..."
```

## Deploy

```bash
# Stateful MCP must run on a single machine (no load-balanced sessions).
fly deploy --ha=false
```

If Fly already created two machines:

```bash
fly scale count 1 --yes
```

After deploy, note the public URL:

```bash
fly status
# Health: https://<app-name>.fly.dev/health
# MCP:    https://<app-name>.fly.dev/mcp
```

## Redeploy (code or config changes)

```bash
fly deploy --ha=false
```

If a second machine reappears after deploy:

```bash
fly scale count 1 --yes
```

## Run the agent against the deployed server

```bash
export CLINICAL_DATA_URL="https://clinical-data-mcp.fly.dev/mcp"
export CLINICAL_DATA_AUTH_TOKEN="<same value as fly secret>"
export EXTRACTOR_BACKEND=stub   # agent-side; server also defaults to stub in image

uv run python -m agent ...   # or your case runner entrypoint
```

## Post-deploy smoke test

```bash
export CLINICAL_DATA_DEPLOY_URL="https://clinical-data-mcp.fly.dev"
uv run pytest tests/test_clinical_data_http.py -m deploy -q
```

## Local HTTP (before Docker)

```bash
export CLINICAL_DATA_AUTH_TOKEN="dev-token"
uv run python -m servers.clinical_data --transport http --host 127.0.0.1 --port 8000
curl -s http://127.0.0.1:8000/health
```

## Docker locally

```bash
docker build -t clinical-data-mcp .
docker run --rm -p 8000:8000 \
  -e CLINICAL_DATA_AUTH_TOKEN="dev-token" \
  clinical-data-mcp
```

## Troubleshooting

### `421 Misdirected Request` from the agent

Stateful MCP sessions must hit **one** Fly machine, and the HTTP client must avoid HTTP/2 connection reuse on the shared Fly edge:

```bash
fly scale count 1 --yes
fly machines list   # confirm exactly one started machine
```

Pull the latest agent code (uses `http2=False`, `Connection: close`, and `anyio.run` for StreamableHTTP).

If 421 persists:

```bash
fly logs
fly ips allocate-v4   # optional: dedicated IPv4 instead of shared
```

### Deploy smoke test skipped

`CLINICAL_DATA_DEPLOY_URL` must be set to the base URL (no `/mcp` suffix):

```bash
export CLINICAL_DATA_DEPLOY_URL="https://clinical-data-mcp.fly.dev"
uv run pytest tests/test_clinical_data_http.py -m deploy -q
```

## Cost / security notes

- **Auth token**: HTTP MCP is protected by `CLINICAL_DATA_AUTH_TOKEN`. Without it, anyone could call tools if the service were public.
- **Extractor**: Image defaults `EXTRACTOR_BACKEND=stub`. If you set `EXTRACTOR_BACKEND=real` on the server and provide `ANTHROPIC_API_KEY`, each `extract_chart` call bills Claude — auth prevents anonymous abuse.
- **Stateful transport**: We run `stateless_http=False` and `json_response=False` so SSE and server-initiated notifications work. **Fly must run exactly one machine** (`fly deploy --ha=false`, `fly scale count 1`) or MCP sessions hit `421 Misdirected Request`. See `docs/transport_tradeoff.md`.
