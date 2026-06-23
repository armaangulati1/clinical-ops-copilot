# StreamableHTTP transport tradeoff: stateful vs stateless

## What we run in production

The clinical-data MCP server is deployed with **StreamableHTTP** using FastMCP defaults:

- `stateless_http=False` — **stateful** sessions
- `json_response=False` — **streaming** responses (SSE), not a single final JSON blob

Local development and tests keep **stdio** transport; the agent uses HTTP only when `CLINICAL_DATA_URL` is set.

## Why stateful matters

MCP over StreamableHTTP is not just request/response RPC. The protocol uses:

1. **HTTP POST** for client → server messages
2. **An SSE (Server-Sent Events) channel** for server → client traffic between posts

In a **stateful** deployment, the server holds a session, keeps the SSE connection alive, and can push **server-initiated** traffic: progress notifications, log messages, sampling requests, roots/list-changed notifications, and other MCP features that are not tied to a single POST round-trip.

Our prior-auth workflow and observability depend on that channel behaving like a live session, not a sequence of isolated HTTP calls.

## What breaks if `stateless_http=True`

When `stateless_http=True`, FastMCP treats each request as independent. The server **does not maintain session state** and **does not keep the SSE channel** in the same way.

Concretely, you lose or degrade:

| Capability | Effect |
|------------|--------|
| **SSE stream** | No durable server→client event stream between POSTs |
| **Progress notifications** | Tool progress cannot stream to the client mid-call |
| **Logging notifications** | Server-side log forwarding to the MCP client stops working |
| **Sampling / roots / list-changed** | Server-initiated requests and lifecycle notifications break |
| **UX & observability** | Agent host and operators see only final tool results, not live telemetry |

For a demo or production agent where we want transparent tool execution and MCP-correct behavior, that is a **correctness and UX regression**, not a cosmetic difference.

## What breaks if `json_response=True`

With `json_response=True`, responses are returned as **one JSON document** at the end of the request instead of streaming over SSE.

That means:

- No incremental events during long-running tools (e.g. extraction)
- No interleaved notifications and partial results
- Higher perceived latency and worse debuggability when tools are slow

We keep `json_response=False` so clients can consume the event stream as MCP intends.

## What stateless would buy us

The main benefit of `stateless_http=True` is **horizontal scaling behind a load balancer**: any replica can answer any POST without sticky sessions or shared session store. That is attractive for high QPS, multi-tenant SaaS, or strict 12-factor “no server memory” deployments.

## Why we chose correctness here

Clinical-data is a **low-QPS, session-oriented** read server with bundled synthetic charts and bearer-token auth. Traffic is agent-driven, not anonymous internet scale. Preserving MCP semantics (progress, logging, SSE) matters more than elastic scale-out on day one.

**Decision:** run **stateful** StreamableHTTP (`stateless_http=False`, `json_response=False`), protect with `CLINICAL_DATA_AUTH_TOKEN`, and accept single-replica / sticky-session deployment (e.g. one Fly machine with `min_machines_running = 1`). If we later need multiple replicas, we would add session affinity or an external session store — not flip to stateless and silently drop notifications.

## Interview-ready summary

> We deploy MCP over StreamableHTTP in stateful mode because MCP uses SSE for server-initiated messages. Stateless HTTP mode removes that channel, which breaks progress, logging, and other notifications — hurting UX and observability. JSON-only responses remove streaming entirely. We trade easy horizontal scale for protocol correctness and a better operator experience, which fits a secured, agent-backed clinical read service more than a stateless public API.
