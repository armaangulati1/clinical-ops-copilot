# Synthetic chart data and local artifacts are copied into the image.
# Secrets (CLINICAL_DATA_AUTH_TOKEN, ANTHROPIC_API_KEY) are injected at runtime only.

FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
COPY agent ./agent
COPY evals ./evals
COPY schemas ./schemas
COPY servers ./servers
COPY data ./data

RUN uv sync --frozen --no-dev

ENV CLINICAL_DATA_CHART_ROOT=/app/data/charts
# Public demo default: stub extractor avoids per-call Claude cost server-side.
# Set EXTRACTOR_BACKEND=real and ANTHROPIC_API_KEY only when you accept that cost.
# CLINICAL_DATA_AUTH_TOKEN is required so anonymous callers cannot burn API quota.
ENV EXTRACTOR_BACKEND=stub
ENV CLINICAL_DATA_HTTP_HOST=0.0.0.0
ENV CLINICAL_DATA_HTTP_PORT=8000

EXPOSE 8000

CMD ["uv", "run", "python", "-m", "servers.clinical_data", "--transport", "http", "--host", "0.0.0.0", "--port", "8000"]
