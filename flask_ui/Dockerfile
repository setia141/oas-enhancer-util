FROM python:3.11-slim

WORKDIR /app

COPY flask_ui/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY flask_ui/ ./flask_ui/

CMD ["python", "flask_ui/app.py"]
