FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /workspace/backend

COPY requirements.txt ./requirements.txt

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY app /workspace/backend/app
COPY alembic /workspace/backend/alembic
COPY config /workspace/backend/config
COPY docs /workspace/backend/docs
COPY alembic.ini docker-entrypoint.sh ./

RUN chmod +x /workspace/backend/docker-entrypoint.sh

EXPOSE 8000

CMD ["/workspace/backend/docker-entrypoint.sh"]
