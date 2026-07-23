# cr2e/Dockerfile
# ─────────────────────────────────────────────────────────────────────────────
# CR²E — Causal RAN Root-Cause Engine
# Runs on port 8001. Shares the ASTRA base image Python environment.
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim

WORKDIR /app

# ── System dependencies ───────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ───────────────────────────────────────────────────────
COPY cr2e/requirements.txt /app/cr2e/requirements.txt
RUN pip install --no-cache-dir -r /app/cr2e/requirements.txt

# ── Application code ──────────────────────────────────────────────────────────
# Mount cr2e/ and xapp/ (for state bus access) via docker-compose volume.
# Only copy what is needed at build time.
COPY cr2e/ /app/cr2e/
COPY xapp/ /app/xapp/

# ── Directories ───────────────────────────────────────────────────────────────
RUN mkdir -p /app/cr2e/data /app/cr2e/results /app/injection

# ── Expose port ───────────────────────────────────────────────────────────────
EXPOSE 8001

# ── Healthcheck ───────────────────────────────────────────────────────────────
HEALTHCHECK --interval=20s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/cr2e/health')"

# ── Entry point ───────────────────────────────────────────────────────────────
CMD ["python", "-m", "cr2e.main"]
