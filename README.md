# OAS Enhancer — Flask + FastAPI + OpenAI

An AI-powered web application that automatically enhances OpenAPI Specification (OAS) files with descriptions, examples, and error schemas using a multi-agent review → enhance loop.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [How the Enhancement Loop Works](#how-the-enhancement-loop-works)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Local Setup](#local-setup)
- [Environment Variables](#environment-variables)
- [Running the App](#running-the-app)
- [Customising Reviewer Rules](#customising-reviewer-rules)
- [API Reference](#api-reference)
- [State Flow](#state-flow)
- [Security Notes](#security-notes)
- [Troubleshooting](#troubleshooting)

---

## Overview

Upload an OAS file (JSON or YAML, Swagger 2.0 or OAS 3.x). The app runs a multi-agent loop where:

1. A **Reviewer** agent reads the spec and identifies issues (missing descriptions, examples, error schemas, etc.)
2. An **Enhancer** agent applies all suggestions and returns the improved spec
3. The loop repeats up to a configurable number of iterations (default: 5) until the reviewer is satisfied

Progress streams live to the browser via Server-Sent Events (SSE). The final enhanced spec is available in both YAML and JSON, with a side-by-side diff against the original.

Optionally upload a Postman collection alongside the OAS file to enable breaking change improvements (schema alignment).

---

## Architecture

```
Browser
   │
   │  HTTP / SSE
   ▼
Flask Frontend  (flask_ui — port 3000)
   │  app.py — serves UI, proxies /enhance and /convert to backend
   │
   │  POST /enhance  (proxied SSE stream)
   │  POST /convert
   ▼
FastAPI Backend  (backend — port 8000)
   │  server.py — /enhance (SSE), /convert, /config, /health
   │
   └── Enhancement Loop  (loop_runner.py — configurable iterations via MAX_ITERATIONS)
         │
         ├── Reviewer Agent  (gpt-4.1-mini)
         │     reads current spec + previous changes context
         │     calls submit_review tool
         │     outputs: satisfied, summary, suggestions[]
         │
         └── Enhancer Agent  (gpt-4.1, streamed)
               reads current spec + reviewer suggestions
               calls save_enhanced_spec tool
               outputs: full updated spec, changes_made[]
```

**Why two separate servers?**
Flask handles the browser-facing UI (templating, file uploads, SSE proxying). FastAPI handles the async agent loop with proper SSE streaming and multipart file handling. The Flask frontend proxies all `/enhance` and `/convert` requests to FastAPI — the browser never calls FastAPI directly.

---

## How the Enhancement Loop Works

```
Upload OAS file (+ optional Postman collection + optional instructions)
      │
      ▼
Parse and validate original spec — record baseline errors
      │
      ▼
For each iteration (up to MAX_ITERATIONS, default 5):
  │
  ├── 1. Check stall guard — if no improvement for 3 consecutive iterations → stop
  │
  ├── 2. Reviewer (gpt-4.1-mini) reads current spec
  │         → calls submit_review(satisfied, summary, suggestions)
  │
  ├── 3. If satisfied = true OR suggestions = [] → stop (reviewer is happy)
  │
  ├── 4. Enhancer (gpt-4.1, streamed) reads spec + all suggestions
  │         → calls save_enhanced_spec(enhanced_spec, changes_made)
  │
  └── 5. Spec post-processing:
            - Misplaced path items rescued from top level into paths{}
            - Non-OAS top-level keys stripped
            - Non-path keys stripped from paths{}
            - Swagger 2.0 fields (produces/consumes) stripped from OAS 3.x operations
            - Duplicate operationIds renamed (_2, _3, …)
            - Paths/operations dropped by the model restored from previous iteration
            - Updated spec validated — errors logged
      │
      ▼
done event:
  original spec (JSON + YAML), final spec (JSON + YAML),
  per-iteration history, original validation errors, final validation errors
```

**Breaking changes policy:**
- Without Postman collection → additive only (add descriptions, examples, new error responses). Existing paths, schemas, types, formats never changed.
- With Postman collection → breaking changes allowed. Enhancer may align schemas with actual Postman responses.

**Why two different models?**

| Agent | Model | Reason |
|---|---|---|
| Reviewer | `gpt-4.1-mini` | Only reads spec and outputs a short suggestion list — fast and cost-efficient |
| Enhancer | `gpt-4.1` (streamed) | Must read the full spec, apply all changes, and return the **complete modified spec** as a structured tool call — large output task requiring the stronger model. Streamed to keep the connection alive. |

---

## Project Structure

```
oas-enhancer-util/
│
├── backend/                        # FastAPI backend
│   ├── __init__.py
│   ├── server.py                   # API endpoints: /enhance (SSE), /convert, /config, /health
│   ├── loop_runner.py              # Multi-agent loop, spec sanitization, SSE event stream, heartbeat
│   ├── requirements.txt
│   ├── .env                        # OPENAI_API_KEY (+ MAX_ITERATIONS) — git-ignored, create from .env.example
│   ├── .env.example                # Template for backend env vars
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── prompts.py              # ← edit REVIEWER_RULES here to change what gets checked
│   │   └── tools.py                # OpenAI function schemas + breaking-changes policy helper
│   └── tools/
│       ├── __init__.py
│       └── oas_to_postman.py       # Native Python OAS 3.x → Postman Collection v2.1 converter
│
├── flask_ui/                       # Flask frontend
│   ├── app.py                      # Flask server — UI routes + proxy to backend
│   ├── requirements.txt
│   ├── .env                        # BACKEND_URL (+ MAX_ITERATIONS) — git-ignored, create from .env.example
│   ├── .env.example                # Template for frontend env vars
│   └── templates/
│       ├── home.html               # Landing page
│       └── index.html              # OAS Enhancer single-page app (SSE reader, diff viewer)
│
├── README.md
└── Dockerfile
```

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | Required for both backend and frontend |
| OpenAI API key | — | Needs access to `gpt-4.1-mini` and `gpt-4.1` models |

---

## Local Setup

### Step 1 — Clone and enter the project

```bash
git clone <your-repo-url>
cd oas-enhancer-util
```

---

### Step 2 — Set up the Backend

#### 2a. Create a virtual environment

```bash
python -m venv backend/venv

# Windows
backend\venv\Scripts\activate

# macOS / Linux
source backend/venv/bin/activate
```

#### 2b. Install dependencies

```bash
pip install -r backend/requirements.txt
```

#### 2c. Create the environment file

```bash
cp backend/.env.example backend/.env
```

Open `backend/.env` and fill in your values:

```env
OPENAI_API_KEY=sk-...
MAX_ITERATIONS=5
```

> Get your API key from [platform.openai.com/api-keys](https://platform.openai.com/api-keys). Ensure your account has access to `gpt-4.1` and `gpt-4.1-mini`.

---

### Step 3 — Set up the Frontend

Open a **new terminal** (keep the backend terminal open).

#### 3a. Create a virtual environment

```bash
cd flask_ui
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

#### 3b. Install dependencies

```bash
pip install -r requirements.txt
```

#### 3c. Create the environment file

```bash
cp .env.example .env
```

Edit `flask_ui/.env` if your backend runs on a non-default host/port or you want to change the iteration count shown in the UI.

---

## Running the App

You need **two terminals running simultaneously** — one for the backend, one for the frontend.

### Terminal 1 — Start the Backend

```bash
# From oas-enhancer-util/ with backend venv activated
uvicorn backend.server:app --reload --port 8000
```

Backend starts at `http://localhost:8000`
API docs available at `http://localhost:8000/docs`

### Terminal 2 — Start the Frontend

```bash
# From oas-enhancer-util/flask_ui/ with flask_ui venv activated
python app.py
```

Frontend starts at `http://localhost:3000`

Open your browser at **http://localhost:3000**.

---

## Environment Variables

### Backend — `backend/.env`

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes | — | OpenAI API key — used for both reviewer and enhancer model calls |
| `MAX_ITERATIONS` | No | `5` | Maximum number of review → enhance iterations per request (range: 1–20) |

### Frontend — `flask_ui/.env`

| Variable | Required | Default | Description |
|---|---|---|---|
| `BACKEND_URL` | No | `http://127.0.0.1:8000` | Override if backend runs on a different host or port |
| `MAX_ITERATIONS` | No | `5` | Controls the iteration count displayed in the UI — should match the backend value |
| `REDUNDANCY_UTIL_URL` | No | `#` | URL for the API Redundancy Util tool card on the home page |

> `MAX_ITERATIONS` must be set consistently in **both** `.env` files so the UI displays the correct value.

---

## Customising Reviewer Rules

To change what the reviewer checks, edit **only** the `REVIEWER_RULES` block in `backend/agents/prompts.py`:

```python
REVIEWER_RULES = """
- Your rule 1
- Your rule 2
- Your rule 3
"""
```

Everything else — tool call instructions, output format, enhancer prompt — is generated automatically from this block. No other file needs to change.

**Default rules checked:**
- Missing or empty `description` fields on paths, operations, parameters, schemas, and properties
- Missing `example` or `examples` on request bodies, responses, and schema properties
- Missing error responses (400, 401, 403, 404, 409, 422, 500, etc.)
- Incomplete error response schemas (should have `code`, `message`, `details` fields)
- Missing or weak schema definitions (no `type`, no `format`, no constraints)
- Missing `summary` on operations
- Missing `tags` on operations

---

## API Reference

### `GET /config` — get server configuration

**Response** — `application/json`

```json
{
  "max_iterations": 5
}
```

Returns the server-side `MAX_ITERATIONS` value. Useful for clients to discover the configured default.

---

### `POST /enhance` — upload OAS file, receive SSE stream

**Request** — `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `oas_file` | file | Yes | OAS spec — `.json`, `.yaml`, `.yml` (Swagger 2.0 or OAS 3.x) |
| `postman_file` | file | No | Postman Collection v2.1 `.json` — enables breaking change improvements |
| `instructions` | string | No | Additional instructions passed to both reviewer and enhancer agents |
| `max_iterations` | integer | No | Override max iterations for this request (default: server `MAX_ITERATIONS`) |

**Response** — `text/event-stream` (SSE)

Each event is a line in the format `data: <json>\n\n`

| Event type | Payload | Description |
|---|---|---|
| `iteration_start` | `{ iteration }` | A new iteration has begun |
| `review_complete` | `{ iteration, data: { satisfied, summary, suggestions[] } }` | Reviewer has submitted its findings |
| `enhance_start` | `{ iteration }` | Enhancer has started applying suggestions |
| `enhance_complete` | `{ iteration, data: { changes_made[] } }` | Enhancer has saved the updated spec |
| `heartbeat` | `{}` | Keepalive ping sent every 5 seconds during LLM processing — safe to ignore |
| `done` | `{ original_spec, original_spec_yaml, final_spec, final_spec_yaml, iterations[], original_validation_errors[], validation_errors[], summary }` | Loop finished — full result |
| `error` | `{ message }` | Unhandled error in the loop |

---

### `POST /convert` — convert OAS to Postman Collection

**Request** — `multipart/form-data`

| Field | Type | Required |
|---|---|---|
| `oas_file` | file | Yes |

**Response** — `application/json`

```json
{
  "collection": { ... }
}
```

Returns a Postman Collection v2.1 JSON object. Conversion is implemented natively in Python — no Node.js or npm dependency.

---

### `GET /health`

Returns `{ "status": "ok" }`. Use this to verify the backend is running before starting the frontend.

---

## State Flow

Each `/enhance` request creates an isolated `state` dict — no shared state between concurrent requests.

| Key | Set by | Used by | Description |
|---|---|---|---|
| `current_spec` | Loop init, enhancer | Reviewer, enhancer | Live OAS spec dict — mutated each iteration |
| `postman_json` | Loop init | Enhancer | Postman collection string (if provided) |
| `has_postman` | Loop init | Reviewer, enhancer | Controls breaking changes policy |
| `review_satisfied` | Reviewer | Loop | True when no more improvements needed |
| `review_summary` | Reviewer | Loop | Overall assessment text |
| `review_suggestions` | Reviewer | Enhancer | List of actionable improvements for current iteration |
| `last_changes` | Enhancer | Reviewer (next iter) | Changes applied — passed to reviewer to avoid re-flagging fixed issues |

---

## Security Notes

- **No npm dependencies** — OAS → Postman conversion is implemented natively in Python; no Node.js required
- **`.env` is git-ignored** — never commit your `OPENAI_API_KEY`
- **Streamed enhancer** — the enhancer uses `stream=True` on the OpenAI call so tokens flow continuously; this prevents proxy/browser timeouts on large specs
- **SSE heartbeat** — a keepalive ping is sent every 5 seconds while the LLM is processing, preventing the browser from treating the connection as frozen
- **Agent timeout** — each model call is guarded by a 120-second `asyncio` timeout; a timed-out call does not crash the loop
- **Request isolation** — each `/enhance` request gets its own `state` dict; concurrent requests cannot interfere with each other
- **Spec sanitization** — the enhancer output is sanitized before being saved: misplaced keys are rescued, invalid fields are stripped, dropped paths are restored from the previous iteration

---

## Troubleshooting

### Backend does not start — `ModuleNotFoundError`
The virtual environment is not activated or dependencies are not installed.
```bash
backend\venv\Scripts\activate        # Windows
pip install -r backend/requirements.txt
```

### `openai.AuthenticationError` — Invalid API key
The `OPENAI_API_KEY` in `backend/.env` is missing or incorrect.
- Confirm `backend/.env` exists and contains `OPENAI_API_KEY=sk-...`
- Confirm the key has access to `gpt-4.1` and `gpt-4.1-mini`

### Frontend shows "enhance failed" or no SSE events
The backend is not running or is unreachable.
- Confirm the backend is running: `curl http://localhost:8000/health`
- Confirm `BACKEND_URL` is set correctly in `flask_ui/.env` if you changed the backend port

### UI iteration count doesn't match backend
`MAX_ITERATIONS` must be set to the same value in both `backend/.env` and `flask_ui/.env`. The UI reads it from the Flask env at page load; the backend enforces it during processing.

### Enhancer is slow or appears to hang
The enhancer uses `gpt-4.1` with up to 32K output tokens — large specs can take 30–90 seconds per iteration. This is expected behaviour. The SSE heartbeat keeps the connection alive throughout. If you need faster results:
- Reduce `MAX_ITERATIONS` in your `.env` files
- The reviewer will stop early automatically once the spec is satisfactory

### Enhancer returns spec with missing paths
This is handled automatically — the `_restore_dropped_content` function in `loop_runner.py` back-fills any paths the model dropped. Check the backend logs for `Restored N dropped path(s)` warnings.

### Loop runs all iterations but reviewer never reaches `satisfied = true`
The spec may have deep structural issues that additive-only changes cannot fix.
- Try uploading a Postman collection alongside the OAS file — this enables the enhancer to make breaking changes (schema alignment)
- Or add custom instructions in the UI to guide the agents
- Reduce `MAX_ITERATIONS` to limit processing time while you iterate on the spec
