# Logging

AgentGate uses Python's standard `logging` module. All log output goes to **stdout** by default, which makes it compatible with `docker logs` and any log-aggregation stack (Loki, CloudWatch, Papertrail, etc.).

## Log level

Set the `LOG_LEVEL` environment variable to control verbosity:

| Value | What you see |
|-------|-------------|
| `DEBUG` | Raw subprocess output, full tracebacks, every bot event |
| `INFO` | Startup banner, key lifecycle events (default) |
| `WARNING` | Only warnings and errors |
| `ERROR` | Only errors |

```env
LOG_LEVEL=DEBUG
```

The value is case-insensitive. An unrecognised value falls back to `INFO` with a warning.

## Log to file (with rotation)

Set `LOG_DIR` to a directory path to write logs to a file **in addition to stdout**:

```env
LOG_DIR=/data/logs
```

Files are written to `$LOG_DIR/agentgate.log` and rotated automatically:

| Setting | Value |
|---------|-------|
| Rotation schedule | Daily (at midnight UTC) |
| Retention | 14 days |
| Compression | gzip (rotated files become `agentgate.log.YYYY-MM-DD.gz`) |

### Persisting logs across restarts (Docker)

Mount a host directory so logs survive container restarts:

```yaml
services:
  myproject:
    image: ghcr.io/agigante80/agentgate:latest
    env_file: .env
    environment:
      - LOG_DIR=/data/logs
    volumes:
      - ./logs:/data/logs   # persisted on host
      - ./data:/data
```

> **Note:** The `/data` volume already used for the history database and the log directory can share the same mount or use separate mounts — both work.

## Log format

All log lines follow this format:

```
2026-03-08T05:38:17 [INFO] src.main: AgentGate v0.7.0
2026-03-08T05:38:17 [INFO] src.main:   Platform : slack
2026-03-08T05:38:17 [INFO] src.main:   AI       : copilot
```

Timestamps are ISO-8601 local time (`YYYY-MM-DDTHH:MM:SS`).
