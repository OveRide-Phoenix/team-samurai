FROM ghcr.io/astral-sh/uv:0.9.21 AS uv

FROM public.ecr.aws/docker/library/python:3.14.5-slim-bookworm

COPY --from=uv /uv /uvx /bin/

WORKDIR /app

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SAMURAI_ENVIRONMENT=production

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --no-cache

COPY src ./src

RUN groupadd --gid 10001 samurai \
    && useradd --create-home --gid samurai --uid 10001 samurai \
    && chown -R samurai:samurai /app

USER samurai

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn samurai.app:create_app --factory --app-dir src --host 0.0.0.0 --port ${PORT:-8080}"]
