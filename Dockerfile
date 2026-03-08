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
RUN npm install -g @github/copilot@0.0.421

# OpenAI Codex CLI — pinned version (update via Dependabot)
RUN npm install -g @openai/codex@0.111.0

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

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD test -f /tmp/healthy

CMD ["python", "-m", "src.main"]
