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

# Go
RUN curl -fsSL https://go.dev/dl/go1.22.4.linux-amd64.tar.gz | tar -C /usr/local -xz
ENV PATH="/usr/local/go/bin:$PATH"

# GitHub Copilot CLI (correct package: @github/copilot, requires Node 22+)
RUN npm install -g @github/copilot

# OpenAI Codex CLI
RUN npm install -g @openai/codex

# Python dependencies
WORKDIR /app
COPY requirements.txt .

# Non-root user — created before pip install so pip runs as non-root
RUN useradd -m botuser && mkdir -p /repo /data && chown botuser:botuser /repo /app /data
USER botuser
ENV PATH="/home/botuser/.local/bin:$PATH"

RUN pip install --no-cache-dir --user -r requirements.txt

# App source
COPY --chown=botuser:botuser src/ src/

# Repo clone destination + persistent data
VOLUME /repo
VOLUME /data

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "src.main"]
