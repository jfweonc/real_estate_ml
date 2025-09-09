# Python + Playwright (Node + browsers) pinned
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# OS deps kept minimal
RUN apt-get update && apt-get install -y --no-install-recommends \
    tini git ca-certificates && \
    rm -rf /var/lib/apt/lists/*
    
# --- Install Node.js 20 LTS (for Playwright/TS tooling) ---
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get update && apt-get install -y --no-install-recommends nodejs \
 && node -v && npm -v \
 && rm -rf /var/lib/apt/lists/*


# --- Python deps (cache-friendly layer) ---
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# --- Node deps (optional now; cache-friendly layer) ---
COPY package.json package-lock.json* ./
RUN npm ci --ignore-scripts || (npm i --package-lock-only && npm ci --ignore-scripts)

# --- App code last (changes often) ---
COPY . .

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash"]
