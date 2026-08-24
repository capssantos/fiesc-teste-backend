FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /workspace/backend

COPY backend/requirements.txt ./requirements.txt

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY backend /workspace/backend
COPY config /workspace/config

RUN chmod +x /workspace/backend/docker-entrypoint.sh

EXPOSE 8000

CMD ["/workspace/backend/docker-entrypoint.sh"]
