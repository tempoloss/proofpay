# ProofPay application image (API / worker / MCP).
# Build from the backend root: docker build -f deploy/Dockerfile .

# --- builder: install dependencies and the project via uv ---
FROM python:3.14-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Manifests only first, so the dependency layer is cached separately.
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --no-install-project

# Then the sources and the project itself.
COPY proofpay ./proofpay
COPY alembic.ini ./
COPY migrations ./migrations
RUN uv sync --frozen --no-dev

# --- runtime: minimal layer with the ready venv ---
FROM python:3.14-slim AS runtime

RUN useradd --create-home --uid 1000 proofpay

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app
USER proofpay

EXPOSE 8000

CMD ["uvicorn", "proofpay.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
