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
- [Docker Setup](#docker-setup)
- [Environment Variables](#environment-variables)
- [Running the App](#running-the-app)
- [Customising Reviewer Rules](#customising-reviewer-rules)
- [API Reference](#api-reference)
- [Large Specs](#large-specs)
- [Security Notes](#security-notes)
- [Troubleshooting](#troubleshooting)

---

## Overview

Upload an OAS file (JSON or YAML, OAS 3.x). The app runs a multi-agent loop where:

1. A **Reviewer** agent reads the spec and identifies issues (missing descriptions, examples, error schemas, etc.)
2. An **Enhancer** agent applies all suggestions and returns the complete improved spec
3. The loop repeats up to a configurable number of iterations (default: 5) until the reviewer is satisfied

Progress streams live to the browser via Server-Sent Events (SSE). The final enhanced spec is available as YAML with a side-by-side diff against the original.

Optionally upload a Postman collection alongside the OAS file to enable breaking change improvements (schema alignment).

---

## Architecture

```
Browser
   │
   │  HTTP / SSE
   ▼
Flask Frontend  (flask_ui — port 3000)
   │  app.py — serves UI, proxies /enhance to backend
   │
   │  POST /enhance  (proxied SSE stream)
   ▼
FastAPI Backend  (backend — port 8000)
   │  server.py — /enhance (SSE), /config, /health
   │
   └── Enhancement Loop  (loop_runner.py — configurable iterations via MAX_ITERATIONS)
         │
         ├── Reviewer Agent  (gpt-4.1-mini)
         │     reads current spec (YAML) + previous changes context
         │     calls submit_review tool
         │     outputs: satisfied, summary, suggestions[]
         │
         └── Enhancer Agent  (gpt-4.1)
               reads current spec (YAML) + reviewer suggestions
               calls save_enhanced_spec tool
               outputs: full updated spec, changes_made[]
```

**Why two separate servers?**
Flask handles the browser-facing UI (templating, file uploads, SSE proxying). FastAPI handles the async agent loop with proper SSE streaming and multipart file handling. The Flask frontend proxies all `/enhance` requests to FastAPI — the browser never calls FastAPI directly.

---

## How the Enhancement Loop Works

```
Upload OAS file (+ optional Postman collection)
      │
      ▼
Normalise line endings, parse YAML/JSON → internal dict
Validate original spec — record baseline errors
      │
      ▼
For each iteration (up to MAX_ITERATIONS, default 5):
  │
  ├── 1. Check stall guard — if no improvement for 3 consecutive iterations → stop
  │
  ├── 2. Reviewer (gpt-4.1-mini) reads current spec as YAML
  │         → calls submit_review(satisfied, summary, suggestions[])
  │
  ├── 3. If satisfied = true OR suggestions = [] → stop
  │
  ├── 4. Enhancer (gpt-4.1) reads full spec as YAML + all suggestions
  │         → calls save_enhanced_spec(enhanced_spec, changes_made[])
  │         timeout: 10 minutes
  │
  └── 5. Validate updated spec — track errors for next reviewer pass
      │
      ▼
done event:
  original spec (JSON + YAML), final spec (JSON + YAML),
  per-iteration history, original validation errors, final validation errors
```

**Breaking changes policy:**
- Without Postman collection → additive only (add descriptions, examples, new error responses). Existing paths, schemas, types, formats are never changed.
- With Postman collection → breaking changes allowed. Enhancer may align schemas with actual Postman responses.

**Why two different models?**

| Agent | Model | Reason |
|---|---|---|
| Reviewer | `gpt-4.1-mini` | Only reads spec and outputs a short suggestion list — fast and cost-efficient |
| Enhancer | `gpt-4.1` | Must read the full spec, apply all changes, and return the **complete modified spec** as a structured tool call — large output task requiring the stronger model |

**Why YAML instead of JSON for LLM prompts?**
YAML is ~30–40% more compact than equivalent JSON for OAS specs. This reduces input token usage and leaves more room in the context window for the model's output — especially important for large specs.

---

## Project Structure

```
oas-enhancer-util/
│
├── backend/                        # FastAPI backend
│   ├── __init__.py
│   ├── server.py                   # API endpoints: /enhance (SSE), /config, /health
│   ├── loop_runner.py              # Multi-agent loop, OAS validation, SSE event stream, heartbeat
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── .env                        # OPENAI_API_KEY (+ MAX_ITERATIONS) — git-ignored
│   ├── .env.example                # Template for backend env vars
│   └── agents/
│       ├── __init__.py
│       ├── prompts.py              # ← edit REVIEWER_RULES here to change what gets checked
│       └── tools.py                # OpenAI function schemas + breaking-changes policy helper
│
├── flask_ui/                       # Flask frontend
│   ├── app.py                      # Flask server — UI routes + proxy to backend
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── .env                        # BACKEND_URL (+ MAX_ITERATIONS) — git-ignored
│   ├── .env.example                # Template for frontend env vars
│   └── templates/
│       ├── home.html               # Landing page
│       └── index.html              # OAS Enhancer single-page app (SSE reader, diff viewer)
│
├── docker-compose.yml
├── sample_spec.yaml                # Sample E-Commerce API spec for testing
└── README.md
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

## Docker Setup

```bash
cp backend/.env.example backend/.env
# fill in OPENAI_API_KEY in backend/.env

docker-compose up --build
```

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:8000`

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

Open your browser at **http://localhost:3000/oas-enhancer**.

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

---

### `POST /enhance` — upload OAS file, receive SSE stream

**Request** — `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `oas_file` | file | Yes | OAS spec — `.json`, `.yaml`, `.yml` (OAS 3.x) |
| `postman_file` | file | No | Postman Collection v2.1 `.json` — enables breaking change improvements |
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

### `GET /health`

Returns `{ "status": "ok" }`. Use this to verify the backend is running before starting the frontend.

---

## Large Specs

The single-spec enhancement approach works reliably up to roughly **20–30 paths**. Beyond that:

| Spec size | Recommendation |
|---|---|
| < 80 KB | Works fine — no action needed |
| 80 KB – 200 KB | Warning shown in UI — results may vary, consider splitting |
| 200 KB+ | Hard stop recommended — split by tag before uploading |

**How to split a large spec:**
Group paths by their `tags` field into separate smaller spec files (e.g. one file for `Auth`, one for `Products`, one for `Orders`). Enhance each file separately, then merge the `paths` sections back into your main spec. Aim for 10–15 paths per file.

The UI shows a warning for files over 80 KB and blocks submission for files under 200 bytes (too small to be a valid spec).

---

## Security Notes

- **`.env` is git-ignored** — never commit your `OPENAI_API_KEY`
- **SSE heartbeat** — a keepalive ping is sent every 5 seconds while the LLM is processing, preventing the browser from treating the connection as frozen
- **Agent timeouts** — reviewer: 120s, enhancer: 600s — timed-out calls do not crash the loop
- **Request isolation** — each `/enhance` request gets its own `state` dict; concurrent requests cannot interfere with each other
- **Line ending normalisation** — uploaded files have `\r\n` normalised to `\n` at ingestion to prevent noise in LLM prompts
- **OAS validation** — spec is validated before and after enhancement; validation errors are tracked and passed to the reviewer for fixing

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
The enhancer uses `gpt-4.1` with up to 32K output tokens — large specs can take 2–5 minutes per iteration. This is expected. The SSE heartbeat keeps the connection alive and the UI timer shows elapsed time. The enhancer timeout is 10 minutes.

### Loop runs all iterations but reviewer never reaches `satisfied = true`
The spec may have deep structural issues that additive-only changes cannot fix.
- Try uploading a Postman collection alongside the OAS file — this enables breaking changes (schema alignment)
- Reduce `MAX_ITERATIONS` to limit processing time
- For very large specs, split by tag and enhance each section separately

### Uploaded file shows 0 paths
You may have uploaded a Postman collection or non-OAS file as the OAS spec. The app only accepts valid OAS 3.x JSON/YAML files with a `paths` key.
