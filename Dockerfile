# syntax=docker/dockerfile:1
FROM python:3.12-slim

# System tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl wget gnupg ca-certificates unzip \
    build-essential \
  && rm -rf /var/lib/apt/lists/*

# gh CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] \
      https://cli.github.com/packages stable main" \
    > /etc/apt/sources.list.d/github-cli.list && \
    apt-get update && apt-get install -y --no-install-recommends gh && \
    rm -rf /var/lib/apt/lists/*

# Node.js LTS via NodeSource (simpler and more reliable in Docker than nvm)
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

# Go — arch-aware (supports linux/amd64 and linux/arm64)
RUN ARCH=$(dpkg --print-architecture) && \
    curl -fsSL "https://go.dev/dl/go1.22.4.linux-${ARCH}.tar.gz" | tar -C /usr/local -xz
ENV PATH="/usr/local/go/bin:$PATH"

# GitHub Copilot CLI — pinned version (update via Dependabot)
RUN npm install -g @github/copilot@1.0.61

# OpenAI Codex CLI — pinned version (update via Dependabot)
RUN npm install -g @openai/codex@0.139.0

# Google Gemini CLI — pinned version (update via Dependabot)
RUN npm install -g @google/gemini-cli@0.46.0

# Anthropic Claude CLI — pinned version (update via Dependabot)
RUN npm install -g @anthropic-ai/claude-code@2.1.177

# ── Telemetry default-deny (privacy / data-minimisation) — see issue #83 ──────
# scrubbed_env() strips AgentGate credentials but does not disable a CLI's own
# usage telemetry, so set a default-deny posture at the image level. Operators
# can opt back in at runtime (see the README privacy section).
ENV DO_NOT_TRACK=1
# claude-code: telemetry is opt-in (off by default); this umbrella also disables
# error reporting + in-CLI auto-update checks (the CLI version is pinned above).
ENV CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
# gemini-cli: privacy.usageStatisticsEnabled defaults to TRUE (anonymised usage
# metrics, not prompt content). The system-settings tier has highest precedence,
# so this disables it regardless of the runtime HOME/UID (HOME=/data is a VOLUME).
# Written as root here, before `USER botuser` below.
ENV GEMINI_CLI_SYSTEM_SETTINGS_PATH=/etc/gemini-cli/settings.json
RUN mkdir -p /etc/gemini-cli && \
    printf '%s' '{"privacy":{"usageStatisticsEnabled":false}}' > /etc/gemini-cli/settings.json
# codex/copilot: OTEL/OTLP telemetry exports only to a configured collector — we
# intentionally set NO OTEL_EXPORTER_OTLP_ENDPOINT, so nothing is exported.

# Python dependencies — installed as root so packages are system-wide and
# accessible regardless of which UID the container runs as at runtime.
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Non-root user for runtime
RUN useradd -m botuser && mkdir -p /repo /data && chown botuser:botuser /repo /app /data
USER botuser

# App source
COPY --chown=botuser:botuser src/ src/
COPY --chown=botuser:botuser VERSION .

# Repo clone destination + persistent data
VOLUME /repo
VOLUME /data

ENV PYTHONUNBUFFERED=1
# Copilot/Codex CLIs write to $HOME — ensure it's always writable
ENV HOME=/data
# Default timezone — override with TZ env var at runtime (e.g. TZ=Europe/London)
ENV TZ=UTC

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD test -f /tmp/healthy

CMD ["python", "-m", "src.main"]
