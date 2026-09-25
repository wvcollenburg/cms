# PoC / Profile A image: Flask app under Gunicorn. See PLAN §10 and compose.yaml.
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    FLASK_APP=app

WORKDIR /srv/createur

# Dependencies first, so code changes don't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --group server --no-install-project

COPY app ./app
COPY migrations ./migrations
COPY babel.cfg ./
COPY deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN pybabel compile -d app/translations \
 && useradd --system --uid 10001 --home /srv/createur createur \
 && mkdir -p /data/media /data/private /data/instance \
 && chown -R createur /data \
 && chmod +x /usr/local/bin/entrypoint.sh

ENV MEDIA_ROOT=/data/media \
    PRIVATE_ROOT=/data/private \
    INSTANCE_PATH=/data/instance
USER createur
EXPOSE 8000
ENTRYPOINT ["entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60", "--access-logfile", "-", "app:create_app()"]
