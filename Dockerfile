FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# uv binary from the official image: avoids pip entirely (Railway's Nixpacks
# builds kept failing inside `pip install uv==...` on flaky PyPI index fetches).
COPY --from=ghcr.io/astral-sh/uv:0.11.17 /uv /uvx /usr/local/bin/

WORKDIR /app

# Dependency layer: only re-runs when the lockfile changes.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --no-dev --frozen --no-install-project

COPY src ./src
RUN uv sync --no-dev --frozen

ENV PATH="/app/.venv/bin:$PATH"

# No EXPOSE on purpose: Railway infers the target port from EXPOSE when present,
# which can conflict with the PORT it injects. Bind to $PORT only.
CMD ["sh", "-c", "uvicorn --app-dir src set_bidask_service.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
