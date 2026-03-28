# OAS Enhancer

An AI-powered web tool that reviews your OpenAPI Specification and suggests improvements — descriptions, examples, x-ai extensions, and schema corrections from Postman. You review each suggestion individually (accept / edit / reject) before anything is applied to the spec.

---

## Table of Contents

- [How it works](#how-it-works)
- [Solution diagram](#solution-diagram)
- [Why this design](#why-this-design)
- [Architecture](#architecture)
- [Project structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Local setup](#local-setup)
- [Docker setup](#docker-setup)
- [Environment variables](#environment-variables)
- [Customising rules](#customising-rules)
- [Using a Postman collection](#using-a-postman-collection)
- [API reference](#api-reference)
- [Troubleshooting](#troubleshooting)

---

## How it works

1. Upload an OAS 3.x file (JSON or YAML). Optionally upload a Postman collection.
2. **Phase 1 — Spec Walker** scans the spec deterministically, producing a precise list of every missing field (descriptions, examples, x-ai sub-tags, info description).
3. **Phase 2 — LLM** receives only the gap list and generates high-quality values for each one. If a Postman collection is provided, the LLM also finds schema differences (missing properties, type corrections, error codes, naming inconsistencies).
4. You see every suggestion with its location in the spec. Click **Accept**, **Edit**, or **Reject** for each one.
5. Click **Apply** — only accepted suggestions are written to the spec.
6. A diff view shows exactly what changed. Download the enhanced YAML.

If you change your mind after applying, click **← Back to Review** to adjust and re-apply without re-running the AI.

Your review progress is auto-saved in the browser. If you close the tab mid-review, a **Resume session** banner appears when you reopen the page.

---

## Solution diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│  INPUT                                                              │
│  OAS Spec (JSON / YAML)          Postman Collection (optional)      │
└──────────────────────┬──────────────────────────┬───────────────────┘
                       │                          │
          ┌────────────▼────────────┐             │
          │   PHASE 1 — SPEC WALKER │             │
          │   (deterministic code)  │             │
          │                         │             │
          │  Walks every:           │             │
          │  • info.description     │             │
          │  • operation description│             │
          │  • parameter description│             │
          │    + example            │             │
          │  • requestBody          │             │
          │    description + example│             │
          │  • response description │             │
          │    + example            │             │
          │  • schema property      │             │
          │    description + example│             │
          │  • x-ai (full object    │             │
          │    + each sub-tag)      │             │
          │                         │             │
          │  Rule: field absent?    │             │
          │  YES → GAP              │             │
          │  NO  → skip (no quality │             │
          │        judgement)       │             │
          └────────────┬────────────┘             │
                       │                          │
                  Gap list                        │
                  (precise locations)             │
                       │                          │
          ┌────────────▼──────────────────────────▼───────┐
          │   PHASE 2 — LLM  (gpt-4.1-mini)               │
          │                                                │
          │  Given the gap list + spec for context:        │
          │  • Generates values for every gap              │
          │    (no searching — gaps are already known)     │
          │                                                │
          │  If Postman provided:                          │
          │  • Naming inconsistencies → schema_property    │
          │  • Missing fields → schema_property            │
          │  • Type corrections → schema_property          │
          │  • Missing error codes → response object       │
          │  • Required fields → required array            │
          └────────────────────────┬───────────────────────┘
                                   │
                              Suggestions
                         (path · method · location
                          · field · value · reason)
                                   │
          ┌────────────────────────▼───────────────────────┐
          │   PHASE 3 — PRE-VALIDATION (server.py)         │
          │                                                │
          │  Dry-runs each suggestion against spec.        │
          │  Drops any that would fail to apply:           │
          │  • $ref sibling violations (OAS 3.0 rule)      │
          │  • Navigation path not found                   │
          └────────────────────────┬───────────────────────┘
                                   │
          ┌────────────────────────▼───────────────────────┐
          │   REVIEW UI                                     │
          │                                                │
          │  Accept · Edit · Reject  (per suggestion)      │
          │  Accept All / Reject All (per endpoint)        │
          │  Auto-saved to localStorage                     │
          │  Resume session on page reload                  │
          └────────────────────────┬───────────────────────┘
                                   │
          ┌────────────────────────▼───────────────────────┐
          │   APPLY + DIFF                                  │
          │                                                │
          │  Accepted suggestions written to spec.         │
          │  Unified diff view (original vs enhanced).     │
          │  Download enhanced YAML.                       │
          │  ← Back to Review without re-running AI.       │
          └────────────────────────────────────────────────┘
```

---

## Why this design

Most LLM-based spec reviewers give the entire spec to the LLM and ask it to find and fix everything. This has a fundamental problem: **LLMs are unreliable at exhaustive search over long documents**. On a 30-operation spec, the model will miss fields it saw 50 operations earlier (attention drift). The only "fixes" are retrying (expensive, no convergence guarantee) or adding server-side filters (gameable).

This tool separates the two jobs:

| Job | Owner | Why |
|---|---|---|
| **Finding** missing fields | Spec Walker (code) | Deterministic, 100% reliable, free |
| **Generating** quality values | LLM | What LLMs are actually good at |
| **Catching** schema inconsistencies | LLM + Postman | Requires semantic reasoning |
| **Reviewing** quality of output | Human | The only reliable quality judge |

**Result:**
- Re-running the tool on an already-enhanced spec finds zero walker gaps — no false positives
- The LLM prompt is focused: "here are 47 specific locations, generate a value for each" — not "review the whole spec"
- Quality is enforced at generation time (VALUE_RULES) and review time (human accepts/edits/rejects), not by gaming-prone static checks

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
   ├── POST /suggest — runs walker → LLM, streams suggestions via SSE
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
│   ├── loop_runner.py            # Walker → LLM pipeline, heartbeat, SSE
│   ├── spec_walker.py            # ← Phase 1: deterministic gap finder
│   ├── requirements.txt
│   ├── .env.example
│   └── agents/
│       ├── prompts.py            # ← EDIT THIS — all customisable rules
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
python -m venv venv
source venv/bin/activate        # macOS / Linux
venv\Scripts\activate           # Windows

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
source venv/bin/activate        # macOS / Linux
venv\Scripts\activate           # Windows

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

## Customising rules

All rules live in **`backend/agents/prompts.py`**. There are three sections to edit.

---

### `WALK_RULES` — what the scanner looks for

Controls the **spec walker** (Phase 1). These are presence checks only — the walker flags a field as a gap if it is absent or empty. There is no quality judgement here; that is the LLM's job.

```python
WALK_RULES = WalkRules(
    info_description   = True,   # spec-level info.description
    description        = True,   # all operation / parameter / schema descriptions
    example            = True,   # all missing examples
    x_ai               = True,   # x-ai tag + required sub-tags on every operation

    x_ai_required_tags = ["when-to-use-me", "how-to-use-me", "trigger-me-command"],
)
```

To disable a check entirely (e.g. if your company does not use x-ai):
```python
x_ai = False
```

To change which x-ai sub-tags are required:
```python
x_ai_required_tags = ["intent", "trigger-command", "owner-team"]
```

---

### `VALUE_RULES` — how the LLM generates values

Controls **quality of generated content** (Phase 2). The LLM follows these rules when writing values for every gap the walker found. This is where you encode your company's documentation standards.

Current rules (edit to match your standards):

```
description  — one sentence starting with a verb. For info.description: outline
               the business purpose. For schemas: specific to the business context.

example      — realistic, production-like. ISO 8601 dates. Prefixed IDs (usr_abc123).
               Never "string", "123", or placeholders.

x-ai         — complete object with:
                 when-to-use-me:     business scenario that triggers this endpoint
                 how-to-use-me:      required inputs, auth, expected output
                 trigger-me-command: a realistic slash command, e.g. /create-user email=... role=...
```

---

### `POSTMAN_RULES` — what to cross-check from Postman

Controls **Postman-driven corrections** (Phase 2, only when a collection is uploaded). Five rules are applied:

| Rule | What it does |
|---|---|
| Naming inconsistencies | If Postman uses `userId` but OAS uses `user_id`, adds the Postman-named property |
| Error codes | If Postman shows 400/404/422/500 not in OAS responses, adds the full response schema |
| Missing properties | Adds any request/response field Postman shows that is absent from spec `properties` |
| Required fields | If Postman always sends a field, adds it to the schema's `required` array |
| Type corrections | If spec says `integer` but Postman shows `"usr_abc123"`, corrects the type |

All `schema_property` values from Postman rules include `type`, `description`, and `example` so re-running the tool on the enhanced spec finds zero new gaps.

---

## Using a Postman collection

Upload a **Postman Collection v2.1** alongside your OAS spec.

Suggested corrections from Postman appear with an orange **schema_property** badge in the UI. The value shown is the full property schema. Accept to add it to the spec, or edit the schema before accepting.

Test files are included in the repo:
- `test_postman_spec.yaml` — a spec with intentional gaps and type mismatches
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
  "reason": "Response has no description.",
  "yaml_context": {
    "context_lines": ["...surrounding YAML lines..."],
    "inserted_line": "  description: \"Returns the user with the given ID.\""
  }
}
```

`field` is one of: `description`, `example`, `x-ai`, `schema_property`

`method` is one of: HTTP method lowercase (`get`, `post`, …), `component`, `info`

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

All suggestions are pre-validated before being shown in the UI, so `failed` should always be 0.

---

### `GET /health`

Returns `{"status": "ok"}`.

---

## Troubleshooting

### Backend does not start — `ModuleNotFoundError`
Virtual environment is not activated or dependencies not installed.
```bash
source venv/bin/activate          # macOS / Linux
venv\Scripts\activate             # Windows
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

### Walker finds 0 gaps but LLM still runs
This happens when a Postman collection is uploaded. The walker found no missing fields, but the LLM still runs to check Postman differences (naming, types, error codes). This is correct behaviour.

### Walker finds 0 gaps and no Postman — tool returns "spec is complete"
The spec already has all required fields. No LLM call is made. If you believe fields are missing, enable `DEBUG` logging to trace the walker's decisions field by field.

### Suggestions show 0 after upload
The spec may have no `paths`. Confirm you uploaded an OAS 3.x file with a `paths` key, not a Postman collection or Swagger 2.0 file.

### Resume banner not appearing after reload
The banner only appears if you had previously loaded suggestions and made at least one accept/reject decision.
