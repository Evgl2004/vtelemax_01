FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts
COPY migrations ./migrations

RUN pip install --upgrade pip \
    && pip install -e ".[telegram,vk,max]"

CMD ["python", "-m", "vtelemax.apps.telegram_app"]
