# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

# Install uv
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy dependency manifests first for better layer caching
COPY pyproject.toml uv.lock ./

# Install all locked runtime dependencies into a virtual environment (no drift)
RUN uv sync --frozen --no-install-project --no-dev

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Copy the pre-built venv from the builder stage
COPY --from=builder /app/.venv /app/.venv

# Copy application source
COPY app/ ./app/

# Activate the virtual environment for all subsequent commands
ENV PATH="/app/.venv/bin:$PATH"

# Expose the API port
EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/recipes')" || exit 1

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
