Feature: Prometheus Metrics Endpoint
Status: Proposed
Owners: @GateCode (implementation), @GateSec (security review)

Summary

Expose a lightweight Prometheus-compatible `/metrics` HTTP endpoint inside the container. Provide core application metrics: request counts, error counts, and latency histograms per AI backend and key routes (AI send/stream, web-dashboard, bot commands).

Motivation

- Improve observability and SLO tracking.
- Allow alerting on error spikes, increased latency, or unexpected traffic patterns.
- Enable capacity planning and cost analysis.

Files to Change

- src/main.py — initialize metrics server or integrate with existing web-dashboard server.
- src/metrics.py — new module to register/emit metrics (wrapper over `prometheus_client`).
- src/ai/* — instrument backend send/stream with metrics (request_latency, request_count, error_count labels: backend, model).
- src/bot.py / src/platform/slack.py — instrument command handling and outgoing API calls.
- docker-compose.yml.example — expose metrics port and PATH.
- tests/ — unit tests for metrics emission and integration test for `/metrics` route.

Design

1. Library: use `prometheus_client` (python) with ASGI/WSGI exporter. If the project uses an existing ASGI server for the web-dashboard, mount the exporter there; otherwise run a small aiohttp server bound to localhost or a configurable interface.

2. Metrics to expose (minimal set):
   - `agentgate_requests_total{route="<route>",backend="<name>",model="<model>"}` (counter)
   - `agentgate_request_errors_total{route="<route>",backend="<name>"}` (counter)
   - `agentgate_request_duration_seconds_bucket{route="<route>",backend="<name>"}` (histogram)
   - `agentgate_inprogress_requests{route="<route>"}` (gauge)
   - `agentgate_ai_bytes_sent_total` / `agentgate_ai_bytes_received_total` (optional)

3. Integration points:
   - Wrap AI backend calls (both stateless and stateful) to increment counters, observe duration, and record backend/model labels.
   - Instrument bot command handlers and web-dashboard API endpoints.

4. Config: add `METRICS_ENABLED` (default: true in prod), `METRICS_BIND` (default localhost:9000), `METRICS_PATH` (default `/metrics`). Optionally `METRICS_AUTH_TOKEN` for basic auth if needed.

Security Considerations

- By default bind metrics to localhost or container-internal interface; do NOT expose on public interfaces without network controls.
- Consider basic auth or network policy if metrics must be reachable remotely.
- Metrics may leak metadata (model names, counts). Avoid including sensitive identifiers in labels.

### Endpoint Authentication (GateSec review)

An IP allowlist (`METRICS_ALLOWED_IPS`) alone is *insufficient* as the sole
access control:
- Container-orchestrated environments (Kubernetes, ECS) assign dynamic pod IPs;
  allowlists become stale or overly broad (entire CIDR blocks).
- IP spoofing is trivial on flat container networks without mutual TLS.
- A compromised sidecar on the same node bypasses any IP-based restriction.

*Recommended layered approach:*
1. **Bind to localhost** (`METRICS_BIND=127.0.0.1:9000`) — default, zero-config.
   Prometheus reaches it via `kubectl port-forward` or a sidecar scraper.
2. **Bearer token auth** (`METRICS_AUTH_TOKEN`) — if the endpoint must be
   network-reachable, require a static bearer token validated in middleware.
   The token MUST be registered with `SecretRedactor` so it is never leaked in
   AI responses.
3. **IP allowlist** (`METRICS_ALLOWED_IPS`) — optional *additional* layer, not
   a replacement for auth. Useful for defense-in-depth in VPC/private-network
   deployments.
4. **Network policy** — in Kubernetes, a `NetworkPolicy` restricting ingress to
   the metrics port from the monitoring namespace only.

At minimum, implement layers 1 + 2. Layer 3 is a nice-to-have. Layer 4 is
infrastructure-level and outside the app's scope but should be documented.

### Label Cardinality — User Tracking Prevention (GateSec review)

The Notes section says "avoid unbounded label values (user IDs, full repo
names)" — this is correct but too vague. Explicit prohibitions:
- `chat_id`, `user_id`, `channel_id`, `session_id` MUST NOT appear as
  Prometheus label values. These are unbounded, PII-adjacent identifiers that
  enable user tracking via the unauthenticated metrics endpoint.
- `tenant_id` is acceptable ONLY if the deployment has a small, fixed set of
  tenants (< 20). Otherwise use a separate metrics partition per tenant.
- Allowed labels: `backend`, `model`, `route`, `status_code`, `platform`
  (telegram/slack). All are low-cardinality and non-identifying.

Testing

- Unit tests: check that metrics counters/histograms increment under simulated calls.
- Integration test: start metrics server in test mode and `GET /metrics` to assert presence of expected metric names.

Rollout Plan

- Enable in staging with bind localhost and no auth.
- Add Prometheus scrape job in infra for staging; validate dashboards/alerts.
- Roll to prod with network policy or private metrics endpoint behind monitoring network.

Open Questions

- Should we include per-tenant labels for multi-tenant deployments? (cardinality concerns)
- Which retention/export mechanism for long-term storage (Pushgateway, remote_write)?

Notes

Keep metric cardinality low — avoid unbounded label values (user IDs, full repo names). Use stable labels: backend, model, route, status_code.

**Hard rule (GateSec):** `chat_id`, `user_id`, `session_id` MUST NEVER be used
as Prometheus labels. See "Label Cardinality" in Security Considerations.
