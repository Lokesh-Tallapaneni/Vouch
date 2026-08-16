# Multi-stage: the build stage carries uv and the lockfile, the runtime stage
# carries neither. Smaller image, and no package manager in production.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

FROM python:3.12-slim AS runtime
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
COPY app ./app
COPY scripts ./scripts
COPY migrations ./migrations
COPY data ./data

# Non-root. A container that does not need to write to its own filesystem
# should not be able to.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
# Migrations run before the server binds, so a deploy can never serve traffic
# against a schema it does not expect.
CMD ["sh", "-c", "python -m scripts.migrate && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
