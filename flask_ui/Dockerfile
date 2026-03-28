FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY flask_ui/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY flask_ui/ ./flask_ui/

EXPOSE 3000

CMD ["gunicorn", "flask_ui.app:app", "--bind", "0.0.0.0:3000", "--workers", "2", "--timeout", "120"]
