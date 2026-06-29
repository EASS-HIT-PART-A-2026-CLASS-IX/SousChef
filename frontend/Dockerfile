# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml ./
# Pin streamlit to the version in uv.lock (1.56.0). The app's RTL CSS targets
# Streamlit's internal DOM (data-testid / emotion class names), which newer
# releases rename — leaving this unpinned pulls a version whose markup the CSS
# no longer matches, breaking the entire UI styling.
RUN uv venv /app/.venv && \
    uv pip install --python /app/.venv/bin/python \
        streamlit==1.56.0 requests python-dotenv google-genai

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY main.py ./
COPY app/ ./app/
COPY .streamlit/ ./.streamlit/

ENV PATH="/app/.venv/bin:$PATH"
ENV STREAMLIT_SERVER_HEADLESS=true

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health')" || exit 1

CMD ["streamlit", "run", "main.py", "--server.address=0.0.0.0", "--server.port=8501"]
