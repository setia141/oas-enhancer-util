# OAS Enhancer

An AI-powered web tool that reviews your OpenAPI Specification and suggests improvements — descriptions, examples, x-ai extensions, and schema corrections from Postman. You review each suggestion individually (accept / edit / reject) before anything is applied to the spec.

---

## Table of Contents

- [How it works](#how-it-works)
- [Solution diagram](#solution-diagram)
- [Why this design](#why-this-design)
- [LLM calls explained](#llm-calls-explained)
- [Caching](#caching)
- [Architecture](#architecture)
- [Project structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Local setup](#local-setup)
- [Docker setup](#docker-setup)
- [Helm / Kubernetes setup](#helm--kubernetes-setup)
- [Environment variables](#environment-variables)
- [Customising rules](#customising-rules)
- [Using a Postman collection](#using-a-postman-collection)
- [API reference](#api-reference)
- [Troubleshooting](#troubleshooting)

---

## How it works

1. Upload an OAS 3.x file (JSON or YAML). Optionally upload a Postman collection.
2. **Phase 1 — Spec Walker** scans the spec deterministically, producing a precise list of every missing field (descriptions, examples, x-ai sub-tags, info description). Walks into `allOf` / `anyOf` / `oneOf` branches and nested object properties.
3. **Phase 2 — LLM batches** receive the gap list in batches of 100. Each batch gets only the spec sections relevant to its gaps as context. Batches run concurrently (up to 3 at a time). If a Postman collection is provided, a **separate LLM call** cross-checks schema differences.
4. Suggestions are pre-validated server-side before being shown. Any that would fail to apply (e.g. `$ref` sibling violations) are silently dropped.
5. You see every suggestion with its location in the spec. Click **Accept**, **Edit**, or **Reject** for each one.
6. Click **Apply** — only accepted suggestions are written to the spec.
7. A diff view shows exactly what changed. Download the enhanced YAML.

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
          │  • allOf/anyOf/oneOf    │             │
          │    branches (recursive) │             │
          │  • x-ai (full object    │             │
          │    + each sub-tag)      │             │
          │                         │             │
          │  Rule: field absent?    │             │
          │  YES → GAP              │             │
          │  NO  → skip             │             │
          └────────────┬────────────┘             │
                       │                          │
                  Gap list                        │
                  (precise locations)             │
                       │                          │
          ┌────────────▼────────────┐             │
          │   PHASE 2 — LLM CALL 1  │             │
          │   Gap filler            │             │
          │                         │             │
          │  Gaps split into        │             │
          │  batches of 100.        │             │
          │  Each batch sends:      │             │
          │  • System: rules prompt │             │
          │  • User: relevant spec  │             │
          │    sections only (not   │             │
          │    full spec) + gap list│             │
          │  Up to 3 run in         │             │
          │  parallel.              │             │
          │                         │             │
          │  Fills: description,    │             │
          │  example, x-ai fields   │             │
          └────────────┬────────────┘             │
                       │                          │
                       │            ┌─────────────▼──────────────┐
                       │            │  PHASE 2 — LLM CALL 2       │
                       │            │  Postman analyser           │
                       │            │  (only when collection      │
                       │            │   is uploaded)              │
                       │            │                             │
                       │            │  Sends:                     │
                       │            │  • System: rules prompt     │
                       │            │  • User: full spec YAML     │
                       │            │    + full Postman collection │
                       │            │                             │
                       │            │  Finds:                     │
                       │            │  • Naming inconsistencies   │
                       │            │  • Missing properties       │
                       │            │  • Type corrections         │
                       │            │  • Missing error codes      │
                       │            │  • Required fields          │
                       │            └─────────────┬──────────────┘
                       │                          │
          ┌────────────▼──────────────────────────▼───────┐
          │   PHASE 3 — PRE-VALIDATION (server.py)         │
          │                                                │
          │  Dry-runs each suggestion against spec.        │
          │  Drops any that would fail to apply:           │
          │  • $ref sibling violations (OAS 3.0 rule)      │
          │  • Navigation path not found                   │
          │  • Missing required fields                     │
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
| **Generating** quality values | LLM Call 1 (batches) | What LLMs are actually good at |
| **Catching** schema inconsistencies | LLM Call 2 (Postman) | Requires semantic reasoning |
| **Reviewing** quality of output | Human | The only reliable quality judge |

**Result:**
- Re-running the tool on an already-enhanced spec finds zero walker gaps — no false positives
- Each LLM batch is focused: "here are 100 specific locations and their spec context — generate a value for each"
- Context sent per batch is only the operations/schemas relevant to that batch, not the whole spec
- Quality is enforced at generation time (VALUE_RULES) and review time (human accepts/edits/rejects)

---

## LLM calls explained

The pipeline makes **up to 2 LLM calls per run** (1 if no Postman collection is uploaded).

### Call 1 — Gap filler (always runs if walker finds gaps)

| | Content |
|---|---|
| **System prompt** | `SUGGESTER_INSTRUCTION` — rules for writing descriptions, examples, x-ai values |
| **User message** | Only the spec sections relevant to this batch (e.g. `GET /users` YAML if that batch has gaps in that operation) + the numbered gap list with exact locations and fields |
| **Tool** | `submit_suggestions` — structured output, one entry per gap |
| **Why scoped context?** | Keeps token usage low and reduces hallucination. The LLM does not see the full spec — only the operations it needs to fill. |

If there are more than `BATCH_SIZE` gaps, they are split into multiple batches which run concurrently (up to `MAX_CONCURRENT=3`).

### Call 2 — Postman analyser (only when a collection is uploaded)

| | Content |
|---|---|
| **System prompt** | `SUGGESTER_INSTRUCTION` — same rules prompt |
| **User message** | Full spec as YAML + full Postman collection text |
| **Tool** | `submit_suggestions` — same structured output format |
| **Why full spec?** | Postman comparison requires cross-referencing request/response bodies against the entire spec — it is not scoped to specific operations. |

Both calls produce suggestions in the same format and go through the same pre-validation step before being shown in the UI.

---

## Caching

Suggestions are cached in `.cache/` to avoid re-running the LLM on the same spec.

**Cache key** = SHA256 of:
- Canonical YAML of the spec (sorted keys, so JSON vs YAML upload gives the same key)
- Postman collection text (if provided)
- Hash of `backend/agents/prompts.py`

**Automatic invalidation**: When you edit `prompts.py` (change rules), the prompts hash changes and the cache is automatically busted — no manual deletion needed.

**Force refresh**: Tick the **Force refresh (ignore cache)** checkbox before uploading to delete the cache entry and re-run the LLM even if results are cached.

**Manual clearing**:
```bash
rm -rf .cache/
```

The cache file path is logged on every cache hit so you can delete a single entry if needed:
```
Cache hit — 51 suggestion(s) cached at 2026-03-28T… | file: abc123.json | to invalidate: DELETE /app/.cache/abc123.json
```

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
   ├── POST /suggest — runs walker → LLM batches, streams suggestions via SSE
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
│   ├── pipeline.py               # Walker → LLM pipeline, batching, caching, heartbeat
│   ├── spec_walker.py            # Phase 1: deterministic gap finder
│   ├── requirements.txt
│   ├── .env.example
│   ├── Dockerfile
│   └── agents/
│       ├── prompts.py            # ← EDIT THIS — all customisable rules
│       └── tools.py              # OpenAI function schema for submit_suggestions
│
├── flask_ui/                     # Flask frontend
│   ├── app.py                    # Flask routes + proxy
│   ├── requirements.txt
│   ├── .env.example
│   ├── Dockerfile
│   └── templates/
│       ├── home.html             # Tool home page
│       └── index.html            # Single-page review UI
│
├── helm/                         # Helm chart for Kubernetes deployment
│   └── oas-enhancer/
│       ├── Chart.yaml
│       ├── values.yaml           # All tunables — registry, images, resources, ingress
│       └── templates/
│           ├── _helpers.tpl
│           ├── secret.yaml       # OPENAI_API_KEY
│           ├── backend-pvc.yaml  # Persistent volumes for logs + cache
│           ├── backend-deployment.yaml
│           ├── backend-service.yaml
│           ├── ui-deployment.yaml
│           ├── ui-service.yaml
│           └── ingress.yaml
│
├── logs/                         # Runtime logs (git-ignored)
│   ├── gaps.log                  # Gap list written before each LLM run
│   └── llm_calls.log             # Full LLM request/response log
│
├── .cache/                       # Suggestion cache (git-ignored)
│   └── {sha256}.json             # Cached suggestions keyed on spec+postman+rules hash
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
| OpenAI API key | Access to `gpt-4.1-mini` (or any model set in `SUGGESTER_MODEL`) |

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
# Edit backend/.env — set OPENAI_API_KEY at minimum
```

Start the backend:
```bash
uvicorn backend.server:app --reload --port 8000
```

### 2. Frontend

Open a **new terminal**:

```bash
pip install -r flask_ui/requirements.txt
cp flask_ui/.env.example flask_ui/.env
python flask_ui/app.py
```

Open **http://localhost:3000/oas-enhancer** in your browser.

---

## Docker setup

```bash
cp backend/.env.example backend/.env
# Set OPENAI_API_KEY in backend/.env

docker compose up --build
```

- Frontend: http://localhost:3000
- Backend:  http://localhost:8000

Logs and cache are persisted in named Docker volumes (`backend_logs`, `backend_cache`) so they survive container restarts. The UI waits for the backend healthcheck to pass before starting.

---

## Helm / Kubernetes setup

### 1. Build and push images

```bash
docker build -f backend/Dockerfile  -t your-registry/oas-enhancer-backend:latest .
docker build -f flask_ui/Dockerfile -t your-registry/oas-enhancer-ui:latest .
docker push your-registry/oas-enhancer-backend:latest
docker push your-registry/oas-enhancer-ui:latest
```

### 2. Install the chart

```bash
helm install oas-enhancer ./helm/oas-enhancer \
  --namespace oas-enhancer --create-namespace \
  --set registry=your-registry \
  --set backend.openaiApiKey=sk-...
```

Or use an existing Kubernetes secret that already holds `OPENAI_API_KEY`:

```bash
helm install oas-enhancer ./helm/oas-enhancer \
  --namespace oas-enhancer --create-namespace \
  --set registry=your-registry \
  --set backend.existingSecret=my-openai-secret
```

### 3. Enable ingress (optional)

```bash
helm upgrade oas-enhancer ./helm/oas-enhancer \
  --set ingress.enabled=true \
  --set ingress.className=nginx \
  --set ingress.host=oas-enhancer.your-domain.com
```

### Key values

| Value | Default | Description |
|---|---|---|
| `registry` | `""` | Docker registry prefix, e.g. `ghcr.io/your-org` |
| `backend.image` | `oas-enhancer-backend` | Backend image name |
| `backend.tag` | `latest` | Backend image tag |
| `backend.openaiApiKey` | `""` | API key (creates a Secret) |
| `backend.existingSecret` | `""` | Use a pre-existing Secret instead |
| `backend.env.SUGGESTER_MODEL` | `gpt-4.1-mini` | Model name |
| `backend.env.BATCH_TOKENS` | `32768` | Max output tokens per batch |
| `backend.env.BATCH_SIZE` | `100` | Gaps per LLM batch |
| `backend.persistence.logs.size` | `1Gi` | PVC size for logs |
| `backend.persistence.cache.size` | `2Gi` | PVC size for suggestion cache |
| `ingress.enabled` | `false` | Enable Ingress resource |
| `ingress.host` | `oas-enhancer.example.com` | Ingress hostname |

---

## Environment variables

### Backend — `backend/.env`

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes | — | OpenAI API key |
| `OPENAI_BASE_URL` | No | `https://api.openai.com/v1` | Override for Azure OpenAI or a corporate AI gateway |
| `SUGGESTER_MODEL` | No | `gpt-4.1-mini` | Model used for both LLM calls |
| `BATCH_SIZE` | No | `100` | Number of gaps per LLM batch (Call 1) |
| `BATCH_TOKENS` | No | `32768` | Max output tokens per batch — must not exceed your model's output limit |

**Model tuning guide:**

| Model | `SUGGESTER_MODEL` | `BATCH_TOKENS` | `BATCH_SIZE` |
|---|---|---|---|
| gpt-4.1-mini | `gpt-4.1-mini` | `32768` | `100` |
| gpt-5-mini | `gpt-5-mini` | `120000` | `500` |
| gpt-5-nano | `gpt-5-nano` | `120000` | `500` |

### Frontend — `flask_ui/.env`

| Variable | Required | Default | Description |
|---|---|---|---|
| `BACKEND_URL` | No | `http://127.0.0.1:8000` | Override if backend runs on a different host/port |
| `REDUNDANCY_UTIL_URL` | No | `#` | URL for the redundancy util link on the home page |

---

## Customising rules

All rules live in **`backend/agents/prompts.py`**. There are three sections to edit.

> Editing `prompts.py` automatically busts the suggestion cache — no manual cache clearing needed.

---

### `WALK_RULES` — what the scanner looks for

Controls the **spec walker** (Phase 1). These are presence checks only — the walker flags a field as a gap if it is absent or empty. No quality judgement here; that is the LLM's job.

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

Controls **quality of generated content** (Phase 2, LLM Call 1). The LLM follows these rules when writing values for every gap the walker found. This is where you encode your company's documentation standards.

Current rules (edit to match your standards):

```
description  — one sentence starting with a verb. Explain business purpose,
               not just what the field is. For enums: describe each value.
               For format/constraint fields: mention the format or constraint.

example      — realistic, production-like. ISO 8601 dates. Prefixed IDs.
               Never "string", "123", or placeholders.
               For enums: pick the most commonly used value.

x-ai         — complete object with:
                 when-to-use-me:     business scenario that triggers this endpoint
                 how-to-use-me:      required inputs, auth, expected output
                 trigger-me-command: a realistic slash command, e.g. /create-user email=... role=...
```

---

### `POSTMAN_RULES` — what to cross-check from Postman

Controls **Postman-driven corrections** (Phase 2, LLM Call 2 — only when a collection is uploaded). Five rules are applied:

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

| Field | Type | Required | Description |
|---|---|---|---|
| `oas_file` | file | Yes | OAS 3.x `.json`, `.yaml`, or `.yml` |
| `postman_file` | file | No | Postman Collection v2.1 `.json` |
| `force_refresh` | string | No | Send `"true"` to bypass cache and re-run the LLM |

**Response** — `text/event-stream` (SSE)

Each event: `data: <json>\n\n`

| Event | Payload |
|---|---|
| `start` | `{}` — analysis has begun |
| `heartbeat` | `{}` — keepalive every 5s, safe to ignore |
| `done` | `{ suggestions[], spec, original_yaml, from_cache? }` |
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

`from_cache: true` appears on the `done` event when results were served from cache.

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
`OPENAI_API_KEY` in `backend/.env` is missing or invalid. Confirm the key has access to the model set in `SUGGESTER_MODEL`.

### Frontend shows error or no suggestions appear
Confirm the backend is running:
```bash
curl http://localhost:8000/health
```
Confirm `BACKEND_URL` in `flask_ui/.env` matches the backend host/port.

### Walker finds 0 gaps but LLM still runs
This happens when a Postman collection is uploaded. The walker found no missing fields, but LLM Call 2 still runs to check Postman differences (naming, types, error codes). This is correct behaviour.

### Walker finds 0 gaps and no Postman — tool returns "spec is complete"
The spec already has all required fields. No LLM call is made. If you believe fields are missing, check `WALK_RULES` in `backend/agents/prompts.py` — a rule may be disabled.

### Suggestions show 0 after upload
The spec may have no `paths`. Confirm you uploaded an OAS 3.x file with a `paths` key, not a Postman collection or Swagger 2.0 file.

### Resume banner not appearing after reload
The banner only appears if you had previously loaded suggestions and made at least one accept/reject decision.

### How to debug LLM issues
After each run, check the `logs/` directory:
- `logs/gaps.log` — full list of gaps sent to LLM Call 1
- `logs/llm_calls.log` — raw request and response payloads for both LLM calls (DEBUG level)

### `possible output truncation` warning in logs
A batch returned fewer suggestions than gaps sent, which may indicate the model hit the output token limit. Reduce `BATCH_SIZE` or increase `BATCH_TOKENS` in `backend/.env`:
```
BATCH_SIZE=50
BATCH_TOKENS=32768
```

### Clearing the suggestion cache
Tick **Force refresh (ignore cache)** in the UI to clear just the current spec's cache entry and re-run the LLM.

To clear all cached results:
```bash
rm -rf .cache/
```

The cache is automatically invalidated when `backend/agents/prompts.py` changes (rules update = new cache key). No manual clearing needed for rule changes.

### Tuning batch size for your model

Set in `backend/.env` (no code changes needed):

| Model | `SUGGESTER_MODEL` | `BATCH_TOKENS` | `BATCH_SIZE` |
|---|---|---|---|
| `gpt-4.1-mini` | `gpt-4.1-mini` | `32768` | `100` |
| `gpt-5-mini` | `gpt-5-mini` | `120000` | `500` |
| `gpt-5-nano` | `gpt-5-nano` | `120000` | `500` |
