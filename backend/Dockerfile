FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN pip install --no-cache-dir "uv==0.9.18" \
    && useradd --create-home --uid 10001 app

FROM base AS dependencies

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

FROM dependencies AS development

RUN uv sync --frozen --all-groups
COPY app ./app
USER app
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM dependencies AS runtime

COPY app ./app
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=6 CMD python -c "from urllib.request import urlopen; response = urlopen('http://127.0.0.1:8000/ready', timeout=2); assert response.status == 200"
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
