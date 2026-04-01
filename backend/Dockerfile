FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*

RUN groupadd -r -g 1001 appuser && useradd -r -u 1001 -g appuser appuser && update-ca-certificates

RUN pip install --upgrade pip && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "backend.server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
