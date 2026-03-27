# OAS Enhancer

An AI-powered web tool that reviews your OpenAPI Specification and suggests improvements — descriptions, examples, custom extensions, and schema corrections. You review each suggestion individually (accept / edit / reject) before anything is applied to the spec.

---

## Table of Contents

- [How it works](#how-it-works)
- [Architecture](#architecture)
- [Project structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Local setup](#local-setup)
- [Docker setup](#docker-setup)
- [Environment variables](#environment-variables)
- [Customising enhancement rules](#customising-enhancement-rules)
- [Using a Postman collection](#using-a-postman-collection)
- [API reference](#api-reference)
- [Troubleshooting](#troubleshooting)

---

## How it works

1. Upload an OAS 3.x file (JSON or YAML). Optionally upload a Postman collection.
2. The AI reviews the spec and returns a list of suggestions — one per field (description, example, x-ai tag, or missing schema property).
3. You see every suggestion with its location in the spec. Click **Accept**, **Edit**, or **Reject** for each one.
4. Click **Apply** — only the accepted suggestions are written to the spec.
5. A diff view shows exactly what changed. Download the enhanced YAML.

If you change your mind after applying, click **← Back to Review** to adjust and re-apply without re-running the AI.

Your review progress is auto-saved in the browser. If you close the tab mid-review, a **Resume session** banner appears when you reopen the page.

---

## Architecture

```
Browser
   │  HTTP / SSE
   ▼
Flask Frontend  (flask_ui — port 3000)
   │  Serves UI, proxies /suggest and /apply to backend
   ▼
FastAPI Backend  (backend — port 8000)
   │
   ├── POST /suggest — runs LLM, streams suggestions via SSE
   └── POST /apply   — applies accepted suggestions, returns diff YAML
```

**Why two servers?**
Flask handles browser-facing templating and file uploads. FastAPI handles async LLM streaming with proper SSE support. The browser only talks to Flask; Flask proxies to FastAPI.

---

## Project structure

```
oas-enhancer-util/
│
├── backend/                      # FastAPI backend
│   ├── server.py                 # /suggest (SSE), /apply, /health endpoints
│   ├── loop_runner.py            # LLM call, heartbeat, SSE event stream
│   ├── requirements.txt
│   ├── .env.example
│   └── agents/
│       ├── prompts.py            # ← EDIT THIS to change enhancement rules
│       └── tools.py              # OpenAI function schema for submit_suggestions
│
├── flask_ui/                     # Flask frontend
│   ├── app.py                    # Flask routes + proxy
│   ├── requirements.txt
│   ├── .env.example
│   └── templates/
│       └── index.html            # Single-page review UI
│
├── docker-compose.yml
├── test_postman_spec.yaml        # Sample spec for testing
├── test_postman_collection.json  # Sample Postman collection for testing
└── README.md
```

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.11+ |
| OpenAI API key | Access to `gpt-4.1-mini` |

---

## Local setup

### 1. Backend

```bash
# From oas-enhancer-util/
python -m venv backend/venv

# Windows
backend\venv\Scripts\activate
# macOS / Linux
source backend/venv/bin/activate

pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
# Edit backend/.env and set OPENAI_API_KEY
```

Start the backend:
```bash
uvicorn backend.server:app --reload --port 8000
```

### 2. Frontend

Open a **new terminal**:

```bash
cd flask_ui
python -m venv venv

# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
python app.py
```

Open **http://localhost:3000/oas-enhancer** in your browser.

---

## Docker setup

```bash
cp backend/.env.example backend/.env
# Set OPENAI_API_KEY in backend/.env

docker-compose up --build
```

- Frontend: http://localhost:3000
- Backend:  http://localhost:8000

---

## Environment variables

### Backend — `backend/.env`

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes | — | OpenAI API key |
| `OPENAI_BASE_URL` | No | `https://api.openai.com/v1` | Override for Azure OpenAI or a proxy |

### Frontend — `flask_ui/.env`

| Variable | Required | Default | Description |
|---|---|---|---|
| `BACKEND_URL` | No | `http://127.0.0.1:8000` | Override if backend runs on a different host/port |
| `REDUNDANCY_UTIL_URL` | No | `#` | URL for the redundancy util link on the home page |

---

## Customising enhancement rules

Open **`backend/agents/prompts.py`**. There are two clearly marked sections to edit:

### `ENHANCEMENT_RULES` — what the AI suggests on every spec

Replace this block with your company's documentation standards:

```python
ENHANCEMENT_RULES = """
- `description` — suggest a concise one-sentence description for any operation,
  parameter, request body, response, or schema property that is missing one
- `example` — suggest a realistic short example for any field missing one
- `x-ai: true` — suggest this on every operation that does not already have it
"""
```

Examples of company-specific rules you might add:
```python
ENHANCEMENT_RULES = """
- `description` — one sentence, must start with a verb (e.g. "Returns...", "Creates...")
- `example` — must use realistic production-like values, not placeholders like 'string' or 123
- `x-internal: true` — add to any operation whose path contains /internal/ or /admin/
- `x-rate-limit` — suggest a rate limit annotation on all POST and PUT operations
"""
```

### `POSTMAN_RULES` — what to cross-check when a Postman collection is provided

Replace this block to control Postman-driven corrections:

```python
POSTMAN_RULES = """
- For any request body or response field that Postman shows but is absent from
  the spec's properties: suggest adding it as a schema_property with the inferred type.
- If a field's type in the spec contradicts what Postman shows, suggest the corrected schema.
"""
```

**Do not edit** `_FORMAT_RULES` or `SUGGESTER_INSTRUCTION` — those control OAS structural correctness and the tool-call format the LLM must follow.

---

## Using a Postman collection

Upload a **Postman Collection v2.1** alongside your OAS spec. The AI will:

1. **Find fields missing from the spec** — if Postman's request body or response contains fields not in the spec's `properties`, they are suggested as new `schema_property` additions (orange badge in the UI) with type inferred from the Postman data.

2. **Flag type mismatches** — if the spec says `type: integer` but Postman shows a string value (e.g. `"usr_abc123"`), the corrected schema is suggested.

Suggested new properties appear in the review UI with an orange **schema_property** badge. The value shown is the full property schema (e.g. `{"type": "string", "description": "User role"}`). Accept to add the entire property to the spec, or edit the schema before accepting.

Test files are included in the repo:
- `test_postman_spec.yaml` — a spec with intentional gaps
- `test_postman_collection.json` — a Postman collection that reveals them

---

## API reference

### `POST /suggest` — analyse spec, stream suggestions

**Request** — `multipart/form-data`

| Field | Type | Required |
|---|---|---|
| `oas_file` | file | Yes — OAS 3.x `.json`, `.yaml`, or `.yml` |
| `postman_file` | file | No — Postman Collection v2.1 `.json` |

**Response** — `text/event-stream` (SSE)

Each event: `data: <json>\n\n`

| Event | Payload |
|---|---|
| `start` | `{}` — analysis has begun |
| `heartbeat` | `{}` — keepalive every 5s, safe to ignore |
| `done` | `{ suggestions[], spec, original_yaml }` |
| `error` | `{ message }` |

Each suggestion object:

```json
{
  "path": "/users/{id}",
  "method": "get",
  "location": "responses.200.description",
  "field": "description",
  "value": "Returns the user with the given ID.",
  "reason": "Operation response has no description.",
  "yaml_context": {
    "context_lines": ["...surrounding YAML lines..."],
    "inserted_line": "  description: \"Returns the user with the given ID.\""
  }
}
```

`field` is one of: `description`, `example`, `x-ai`, `schema_property`

---

### `POST /apply` — apply accepted suggestions

**Request** — `application/json`

```json
{
  "spec": { },
  "accepted": [
    {
      "path": "/users/{id}",
      "method": "get",
      "location": "responses.200.description",
      "field": "description",
      "value": "Returns the user with the given ID."
    }
  ]
}
```

**Response** — `application/json`

```json
{
  "original_yaml": "...",
  "spec_yaml": "...",
  "applied": 42,
  "failed": 0,
  "failures": []
}
```

All suggestions are validated against the spec before being shown in the UI, so `failed` should always be 0.

---

### `GET /health`

Returns `{"status": "ok"}`.

---

## Troubleshooting

### Backend does not start — `ModuleNotFoundError`
Virtual environment is not activated or dependencies not installed.
```bash
backend\venv\Scripts\activate   # Windows
pip install -r backend/requirements.txt
```

### `openai.AuthenticationError`
`OPENAI_API_KEY` in `backend/.env` is missing or invalid. Confirm the key has access to `gpt-4.1-mini`.

### Frontend shows error or no suggestions appear
Confirm the backend is running:
```bash
curl http://localhost:8000/health
```
Confirm `BACKEND_URL` in `flask_ui/.env` matches the backend host/port.

### Resume banner not appearing after reload
The banner only appears if you had previously loaded suggestions and made at least one accept/reject decision. If you closed the tab before the AI finished or before interacting, there is nothing saved to resume.

### Suggestions show 0 after upload
The spec may have no `paths`. Confirm you uploaded an OAS 3.x file with a `paths` key, not a Postman collection or Swagger 2.0 file.
