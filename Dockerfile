# ── Stage 1: Build React frontend ─────────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./

# Vite bakes env vars into the bundle at build time — pass them as build args
ARG VITE_AZURE_CLIENT_ID
ARG VITE_AZURE_TENANT_ID
ARG VITE_AZURE_ALLOWED_GROUP_ID
ARG VITE_REDIRECT_URI

ENV VITE_AZURE_CLIENT_ID=$VITE_AZURE_CLIENT_ID \
    VITE_AZURE_TENANT_ID=$VITE_AZURE_TENANT_ID \
    VITE_AZURE_ALLOWED_GROUP_ID=$VITE_AZURE_ALLOWED_GROUP_ID \
    VITE_REDIRECT_URI=$VITE_REDIRECT_URI

RUN npm run build


# ── Stage 2: Python backend + serve frontend ───────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ ./backend/

# Copy built frontend from stage 1
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

EXPOSE 8000

# OPENAI_API_KEY must be provided at runtime via -e or env file
CMD ["uvicorn", "backend.server:app", "--host", "0.0.0.0", "--port", "8000"]
