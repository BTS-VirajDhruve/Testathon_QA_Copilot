FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv

COPY pyproject.toml ./
COPY uv.lock* ./
COPY app ./app
COPY seed ./seed
COPY tests ./tests
COPY pytest.ini ./

# Sync project + deps into a local .venv (no global pip packages)
RUN uv sync --frozen --no-dev || uv sync --no-dev

ENV DATA_DIR=/app/data
ENV CHROMA_DIR=/app/data/chroma
ENV GRAPH_STORE_PATH=/app/data/graph_store.json
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]