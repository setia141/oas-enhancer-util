# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Local Development (without Docker)

```bash
# Backend — from repo root
cd backend
python -m uvicorn backend.server:app --host 0.0.0.0 --port 8000 --reload

# Frontend — from repo root
cd flask_ui
python app.py
```

### Docker
```bash
# Build and run both services
docker compose up -d --build

# Logs
docker logs oas-enhancer-util-backend-1
docker logs oas-enhancer-util-ui-1
```

### Tests
```bash
python -m pytest tests/test_postman_parser.py -v
```

### Helm (Kubernetes)
```bash
helm upgrade --install <release> ./helm/oas-enhancer -n <namespace> \
  --set backend.openaiApiKey=<key>
```

## Environment Setup

Copy and fill in the required env files before running:
- `backend/.env.example` → `backend/.env` — **required**: `OPENAI_API_KEY`
- `flask_ui/.env.example` → `flask_ui/.env` — **required**: `BACKEND_URL`

Key tuning variables in `backend/.env`:
- `BATCH_SIZE` (default 50) — gaps per LLM call. Use 100 for large specs, 25 for strict token limits.
- `SUGGESTER_MODEL` (default `gpt-4.1-mini`) — model used for suggestions
- `OPENAI_BASE_URL` — override for corporate API gateways

## Architecture

### Two-Service Design
- **Backend** (`backend/`): FastAPI on port 8000 — all intelligence lives here
- **Frontend** (`flask_ui/`): Flask on port 3000 — thin proxy + SSE relay + UI

The Flask frontend never talks to OpenAI directly. It proxies `/suggest` and `/apply` to the FastAPI backend and relays the SSE stream back to the browser.

### Suggestion Pipeline (backend)

```
Upload OAS + Postman
  → Phase 1: spec_walker.py — deterministic gap detection (no LLM)
  → Yield scan_complete event (gap count + estimated time) to UI
  → Phase 2: pipeline.py — batched concurrent LLM calls
      ├─ OAS gaps split into BATCH_SIZE chunks, MAX_CONCURRENT=3 in parallel
      └─ Postman: separate batch via postman_parser.py
  → Cache results (SHA256 of spec + postman + prompts.py content)
  → router.py — pre-validate all suggestions (dry-run apply)
  → Stream enriched suggestions to UI via SSE
```

### Key Files

| File | Purpose |
|------|---------|
| `backend/spec_walker.py` | Phase 1 — finds gaps without LLM. Health check paths (`/health`, `/healthz`, etc.) are skipped. |
| `backend/pipeline.py` | Phase 2 — LLM batching, caching, retry logic, SSE events |
| `backend/router.py` | FastAPI routes: `POST /oas-enhancer/suggest`, `POST /oas-enhancer/apply`, `GET /oas-enhancer/health` |
| `backend/postman_parser.py` | Parses Postman v2.1 collections — normalises `{{var}}` and `:param` URL styles to OAS `{param}` |
| `backend/agents/prompts.py` | **Customise here** — `WALK_RULES` controls what gaps to find; `VALUE_RULES` controls LLM output quality |
| `flask_ui/app.py` | Flask proxy routes — `/suggest` streams SSE, `/apply` returns JSON |
| `flask_ui/templates/index.html` | Entire frontend UI in one file — SSE event handler, suggestion review, diff view |

### SSE Event Flow

The browser receives these events in order:
1. `start` — processing begun
2. `scan_complete` — `{total_gaps, total_batches, estimated_minutes}` — shown in UI status bar
3. `heartbeat` — keepalive every 5s during LLM processing
4. `done` — `{suggestions, spec, original_yaml}` — triggers review phase
5. `error` — processing failed

### Caching

Cache lives in `.cache/` (excluded from git). Key is `SHA256(prompts.py content + canonical spec YAML + postman text)`. Changing `prompts.py` automatically busts all cached results. Delete `.cache/*.json` to force refresh manually.

### Helm Chart

Chart at `helm/oas-enhancer/`. Key design decisions:
- **Logs**: `emptyDir` — not persisted, avoids PVC attachment issues
- **Cache**: PVC with `ReadWriteOnce` + `strategy: Recreate` — brief downtime on deploy but cache survives pod restarts
- **Security context**: `runAsUser: 1001`, `fsGroup: 1001` matching `appuser` in Dockerfile
- **Health probe path**: `/oas-enhancer/health` (not `/health`)
- Secrets injected via `.vault/secrets.apisecrets exec` in the container command
