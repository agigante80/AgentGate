Feature: Token / Cost Tracking
Status: Proposed
Owners: @GateCode (implementation), @GateSec (security review)

Summary

Capture usage/`usage` payloads returned by OpenAI (via DirectAPIBackend) and accumulate per-session and per-day spend counters. Surface spend and token usage via `/gate status` and expose lightweight metrics for consumption.

Motivation

- Make AI costs visible to operators and end users.
- Enable budget alerts and per-session accountability.
- Provide data for cost-optimizations (prompt trimming, model selection).

Files to Change

- src/ai/direct.py — collect and forward `usage` from provider responses.
- src/config.py — add pricing overrides and feature flags (see Env vars).
- src/history.py or a new src/billing.py — persist aggregated usage (per-day, per-session).
- src/bot.py — extend `/gate status` handler to show today's spend and session totals.
- tests/ — unit/contract tests for aggregation and reporting.

Design

1. Capture: DirectAPIBackend inspects provider responses for a `usage` block (e.g., OpenAI: prompt_tokens, completion_tokens, total_tokens). Convert tokens -> cost using model-specific pricing coefficients.

2. Storage: add a new SQLite table `usage_records`:
   - id, date (YYYY-MM-DD), session_id, backend, model, prompt_tokens, completion_tokens, total_tokens, cost_usd, created_at

   Aggregate queries calculate per-session and per-day totals. Prefer storing raw token counts + computed cost (avoid storing provider billing IDs).

3. Pricing config: add optional per-model pricing overrides to `AIConfig` (e.g., `pricing_overrides: {"gpt-4": {"prompt": 0.03, "completion": 0.06}}`). If unset, fall back to default in-code coefficients (documented and testable).

4. Surface: `/gate status` returns concise spend summary for current session and today (e.g., "Today: $1.23 — Session: $0.11"). Additionally, expose metrics (see metrics feature) and a `/gate billing --since=2026-03-01` admin command.

5. Backpressure & batching: buffer usage writes in-memory and flush periodically to avoid DB I/O bursts. On shutdown, flush buffer.

Env Vars

- TOKEN_TRACKING_ENABLED=true|false (default: false)
- TOKEN_PRICING_OVERRIDES — JSON string or path to file (optional)
- USAGE_RETENTION_DAYS — integer, days to keep usage records (default: 90) *(GateSec)*
- COST_DAILY_BUDGET_USD — float, optional daily spend cap triggering a warning
- COST_ALERT_ENABLED=true|false (default: false) — opt-in for budget channel alerts *(GateSec)*

Security Considerations

- Usage records do not store prompts or model responses; only token counts and computed cost. Avoid persisting any unredacted text.
- Access to usage data is still sensitive (billing info). Enforce same access controls as history DB and audit access events.
- Validate that redaction logic is not accidentally bypassed — token counting should occur from the provider response metadata, not by re-parsing user content.

### PII / Data-Retention Concerns (GateSec review)

The `usage_records` table stores `session_id` which maps directly to
`chat_id` (Telegram chat ID or Slack channel ID). This is a *PII-adjacent
identifier* — it can be correlated with the `history` table to reconstruct
who asked what and how much it cost.

*Required mitigations:*
1. **Hash or anonymise `session_id`** in `usage_records`. Use a one-way
   keyed hash (HMAC-SHA256 with a config-derived key) so billing aggregation
   still works but the raw chat/channel ID is not stored in plaintext.
   Alternatively, use an opaque auto-increment surrogate that cannot be
   joined to the history table without an in-memory mapping.
2. **Data retention policy** — add `USAGE_RETENTION_DAYS` (default: 90).
   A periodic cleanup task (or SQLite trigger) must purge rows older than
   the retention window. Document this for GDPR/right-to-erasure compliance.
3. **`gate clear` must cascade** — when a user runs `gate clear` to delete
   their conversation history, the corresponding `usage_records` rows for
   that `session_id` should also be deleted (or the hash makes them
   unlinkable, satisfying the same goal).
4. **No raw text columns** — the schema looks clean (token counts + cost
   only), but add a contract test asserting that `usage_records` columns
   contain no TEXT fields beyond `session_id`, `backend`, `model`, and
   `date`. This prevents future schema drift from accidentally adding
   prompt/response text.

### Budget Warning Channel Leakage (GateSec review)

If a `COST_DAILY_BUDGET_USD` mechanism is implemented, the budget-exceeded
warning MUST be routed through the same auth-guarded path as other bot
messages:
- On Telegram: send only to `TG_CHAT_ID` (already auth-restricted).
- On Slack: send only to `SLACK_CHANNEL_ID` (auth-restricted channel).
  Do NOT post to a different channel or use `<!channel>` / `<!here>` in the
  warning — this would leak cost/usage data to users who are in the channel
  but not in `ALLOWED_USERS`.
- The warning message itself should contain only the budget threshold and
  current spend (e.g., "Daily budget $5.00 exceeded — current spend: $5.23").
  It MUST NOT include `session_id`, `chat_id`, or per-user breakdowns in the
  channel message. Per-user detail should only be visible via `/gate billing`
  (which is already auth-gated by `@_requires_auth` / `_is_allowed()`).
- Add `COST_ALERT_ENABLED=true|false` (default: false) as an explicit
  opt-in to prevent unexpected message leakage on upgrade.

Testing

- Unit tests: token->cost conversion, per-model pricing override, DB insertion, aggregation queries.
- Integration tests: simulate DirectAPIBackend responses with `usage` payload and assert `/gate status` shows expected sums.
- Regression: ensure no raw text fields are written to usage tables.

Rollout Plan

- Feature-flagged rollout (TOKEN_TRACKING_ENABLED=false by default).
- Deploy to staging, validate metrics and `/gate status` output for sample loads, then enable in prod.

Open Questions

- Who pays costs per-session (user vs tenant)? Add tenant_id to storage if multi-tenant.
- Should historical per-day costs be exportable (CSV)?
- Rate-limits around DB writes under high traffic.

Notes

This doc focuses on OpenAI-style `usage` payloads. For other backends (Anthropic, Gemini), normalize their usage metadata to the same schema.
