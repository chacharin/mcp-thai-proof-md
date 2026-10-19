# mcp-thai-proofread - MCP server (streamable HTTP) for Thai spelling correction
FROM python:3.12-slim

# TZ: Thailand (UTC+7) in POSIX form, so the slim image needs no tzdata; it only stamps backup and
# log file names. Override with TZ in .env (POSIX form, e.g. "<+00>0" for UTC).
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 TZ="<+07>-7"
WORKDIR /app

# uv is mounted only for this step, so the 42 MB binary never ends up in the image
COPY pyproject.toml uv.lock ./
RUN --mount=from=ghcr.io/astral-sh/uv:0.13.1,source=/uv,target=/bin/uv \
    uv sync --frozen --no-dev --no-install-project

COPY app/ ./app/
RUN useradd --system --uid 10001 appuser
USER appuser
EXPOSE 8800
CMD ["/app/.venv/bin/python", "-m", "app.server"]
