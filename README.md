# OAS Enhancer

An AI-powered web tool that reviews your OpenAPI Specification and suggests improvements — descriptions, examples, x-ai extensions, and schema corrections from Postman. You review each suggestion individually (accept / edit / reject) before anything is applied to the spec.

---

## Table of Contents

- [How it works](#how-it-works)
- [Solution diagram](#solution-diagram)
- [Why this design](#why-this-design)
- [LLM calls explained](#llm-calls-explained)
- [Postman collection support](#postman-collection-support)
- [Caching](#caching)
- [Architecture](#architecture)
- [Project structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Local setup](#local-setup)
- [Docker setup](#docker-setup)
- [Helm / Kubernetes setup](#helm--kubernetes-setup)
- [Environment variables](#environment-variables)
- [Customising rules](#customising-rules)
- [API reference](#api-reference)
- [Troubleshooting](#troubleshooting)

---

## How it works

1. Upload an OAS 3.x file (JSON or YAML). Optionally upload a Postman collection.
2. **Phase 1 — Spec Walker** scans the spec deterministically, producing a precise list of every missing field (descriptions, examples, x-ai sub-tags, info description). Walks into `allOf` / `anyOf` / `oneOf` branches and nested object properties. No LLM involved.
3. **Phase 2 — LLM gap filler** receives the gap list in batches (default: 50 gaps). Each batch gets only the spec sections relevant to its gaps as context. Batches run concurrently (up to 3 at a time).
4. If a Postman collection is provided, the **Postman parser** extracts a clean per-endpoint summary (request fields, response codes, response body fields), stripping all scripts, auth, and env variable noise. A separate set of **LLM Postman batches** (default: 2 endpoints each) cross-checks each endpoint against the spec for naming inconsistencies, missing error codes, missing properties, and type corrections. Batches run concurrently.
5. All suggestions are pre-validated server-side. Any that would fail to apply (e.g. `$ref` sibling violations) are silently dropped.
6. You see every suggestion with its location in the spec. Click **Accept**, **Edit**, or **Reject** for each one.
7. Click **Apply** — only accepted suggestions are written to the spec.
8. A diff view shows exactly what changed. Download the enhanced YAML.

If you change your mind after applying, click **← Back to Review** to adjust and re-apply without re-running the AI.

Your review progress is auto-saved in the browser. If you close the tab mid-review, a **Resume session** banner appears when you reopen the page.

---

## Solution diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│  INPUT                                                              │
│  OAS Spec (JSON / YAML)        Postman Collection v2.1 (optional)  │
└────────────┬────────────────────────────────┬───────────────────────┘
             │                                │
             ▼                                ▼
┌────────────────────────┐      ┌─────────────────────────────────────┐
│  PHASE 1 — SPEC WALKER │      │  POSTMAN PARSER (deterministic)     │
│  (deterministic, free) │      │                                     │
│                        │      │  Walks folders recursively.         │
│  Checks every:         │      │  Per endpoint extracts:             │
│  • info.description    │      │  • HTTP method + normalised path    │
│  • operation desc.     │      │  • request body field names         │
│  • parameter desc.     │      │    (union across all scenarios)     │
│    + example           │      │  • response codes seen              │
│  • requestBody         │      │  • response body field names        │
│    desc. + example     │      │    (per code, unioned)              │
│  • response desc.      │      │                                     │
│    + example           │      │  Strips all noise:                  │
│  • schema property     │      │  • auth headers & OAuth flows       │
│    desc. + example     │      │  • pre-request / test scripts       │
│  • allOf/anyOf/oneOf   │      │  • env variable values              │
│    (recursive)         │      │  • query params / metadata          │
│  • x-ai object         │      │                                     │
│    + each sub-tag      │      │  Normalises URLs:                   │
│                        │      │  • {{baseUrl}}/users → /users       │
│  Rule: field absent?   │      │  • /users/{{id}} → /users/{id}      │
│  YES → GAP             │      │  • /users/:id → /users/{id}         │
│  NO  → skip            │      │  • /users/usr_123 → /users/{id}     │
└──────────┬─────────────┘      └──────────────┬──────────────────────┘
           │                                   │
       Gap list                        Clean structured summary
       (precise locations)             (one block per endpoint)
           │                                   │
           ▼                                   ▼
┌────────────────────────┐      ┌─────────────────────────────────────┐
│  PHASE 2 — GAP FILLER  │      │  PHASE 2 — POSTMAN CROSS-CHECKER    │
│  (LLM, concurrent)     │      │  (LLM, concurrent, optional)        │
│                        │      │                                     │
│  Gaps → batches of 50  │      │  Endpoints → batches of 2           │
│  Up to 3 in parallel   │      │  Up to 3 in parallel                │
│                        │      │                                     │
│  Each batch receives:  │      │  Each batch receives:               │
│  • System: value rules │      │  • System: Postman rules            │
│  • User: relevant spec │      │  • User: full spec YAML             │
│    sections only       │      │    + clean summary for that batch   │
│    + gap list          │      │    (NOT raw Postman JSON)           │
│                        │      │                                     │
│  Output: description,  │      │  Output: schema_property for        │
│  example, x-ai values  │      │  • missing error codes              │
│                        │      │  • missing request fields           │
└──────────┬─────────────┘      │  • missing response fields          │
           │                    │  • naming inconsistencies           │
           │                    │  • type corrections                 │
           │                    └──────────────┬──────────────────────┘
           │                                   │
           └──────────────┬────────────────────┘
                          │
                          ▼
           ┌──────────────────────────────────┐
           │  PHASE 3 — PRE-VALIDATION        │
           │                                  │
           │  Dry-runs every suggestion.      │
           │  Drops suggestions that would:   │
           │  • violate $ref sibling rule     │
           │  • fail navigation path lookup   │
           │  • have missing required fields  │
           └──────────────┬───────────────────┘
                          │
                          ▼
           ┌──────────────────────────────────┐
           │  REVIEW UI                       │
           │                                  │
           │  Accept · Edit · Reject          │
           │  per suggestion                  │
           │  Accept All / Reject All         │
           │  per endpoint group              │
           │  Auto-saved to localStorage      │
           │  Resume session on reload        │
           └──────────────┬───────────────────┘
                          │
                          ▼
           ┌──────────────────────────────────┐
           │  APPLY + DIFF                    │
           │                                  │
           │  Accepted suggestions written.   │
           │  Unified diff: original vs new.  │
           │  Download enhanced YAML.         │
           │  ← Back to Review without re-AI  │
           └──────────────────────────────────┘
```

---

## Why this design

### Spec walker + LLM split

Most LLM-based spec reviewers give the entire spec to the LLM and ask it to find and fix everything. This has a fundamental problem: **LLMs are unreliable at exhaustive search over long documents**. On a 30-operation spec the model will miss fields it saw 50 operations earlier (attention drift). The only "fixes" are retrying (expensive, no convergence guarantee) or adding server-side filters (gameable).

This tool separates the two jobs:

| Job | Owner | Why |
|---|---|---|
| **Finding** missing fields | Spec Walker (code) | Deterministic, 100% reliable, free |
| **Generating** quality values | LLM gap-filler (batched) | What LLMs are actually good at |
| **Catching** schema inconsistencies | LLM Postman checker (batched) | Requires semantic reasoning |
| **Reviewing** output quality | Human | The only reliable quality judge |

**Result:**
- Re-running the tool on an already-enhanced spec finds zero walker gaps — no false positives
- Each LLM batch is focused: "here are 50 specific locations and their spec context — generate a value for each"
- Context per batch is only the operations/schemas relevant to that batch, not the whole spec

### Postman parser vs raw JSON

Sending the raw Postman collection JSON to the LLM is unreliable. A real-world collection contains:
- Pre-request scripts (JavaScript, hundreds of lines)
- Test scripts (assertions, environment variable setters)
- Auth configuration and OAuth flows
- Environment variable references (`{{tenantId}}`, `{{authToken}}`)
- Multiple scenarios for the same endpoint (happy path, error path, edge cases)
- Request IDs, timestamps, folder metadata

All of this is noise. It crowds out the signal (what fields are in the request/response bodies) and causes the model to produce incoherent output.

The Postman parser extracts exactly what the LLM needs — one clean block per endpoint:

```
### POST /orders
  Request body fields : customer_id, items, notes, promo_code, shipping_address
  Response codes seen : 201, 422
  Response 201 fields : createdAt, currency, estimatedDelivery, id, status, total
  Response 422 fields : details, error
```

**Why batch Postman endpoints?**
A single call covering all endpoints causes LLM attention drift — only the first 1-2 endpoints get thorough analysis. Splitting into small batches (default: 2 endpoints per call, configurable via `POSTMAN_BATCH_SIZE`) gives the LLM a bounded task. This mirrors how walker gaps are batched for the same reason.

**Evidence from testing (env-heavy enterprise collection, 7 endpoints):**

| Approach | Suggestions returned | Findings missed |
|---|---|---|
| Raw JSON, single call | 33/45 corrupted strings | Most endpoints |
| Clean summary, single call | 4 valid | 16 out of 20 findings |
| Clean summary, batched (2 per call) | 31 valid | 2 out of 22 findings |

---

## LLM calls explained

The pipeline makes **1 + N calls per run**, where N = number of Postman endpoint batches (0 if no collection uploaded).

### Gap-filler batches (always run if walker finds gaps)

| | Content |
|---|---|
| **System prompt** | `SUGGESTER_INSTRUCTION` — rules for writing descriptions, examples, x-ai values |
| **User message** | Only the spec sections relevant to this batch + the numbered gap list with exact locations |
| **Tool** | `submit_suggestions` — structured output, one entry per gap |
| **Concurrency** | Up to `MAX_CONCURRENT=3` batches in parallel |

Gaps are split into batches of `BATCH_SIZE` (default: 50). The LLM does not see the full spec — only the operations it needs to fill.

### Postman cross-check batches (only when a collection is uploaded)

| | Content |
|---|---|
| **System prompt** | `SUGGESTER_INSTRUCTION` — same rules prompt |
| **User message** | Full spec as YAML + clean Postman summary for this batch only (NOT raw JSON) |
| **Tool** | `submit_suggestions` — same structured output format |
| **Concurrency** | Up to `MAX_CONCURRENT=3` batches in parallel |

Endpoints are split into batches of `POSTMAN_BATCH_SIZE` (default: 2). Each call has a focused, bounded task.

---

## Postman collection support

### What is supported

| Feature | Handled | Notes |
|---|---|---|
| Collection v2.1 | Yes | Standard format from Postman export |
| Nested folders | Yes | Walked recursively |
| Multiple scenarios per endpoint | Yes | Fields and codes are unioned across all scenarios |
| `{{baseUrl}}/path` prefix | Yes | Leading `{{...}}` stripped from URL |
| `{{variable}}` in path segments | Yes | `/users/{{userId}}` → `/users/{userId}` |
| `:param` style path params | Yes | `/users/:id` → `/users/{id}` |
| Concrete IDs in paths | Yes | `/users/usr_abc123` matched to `/users/{id}` spec template |
| `raw` JSON body | Yes | Top-level keys extracted |
| `formdata` body | Yes | Field names extracted |
| `urlencoded` body | Yes | Field names extracted |
| Saved response examples | Yes | Code + body fields extracted |
| `{{variable}}` in body values | Yes | Only keys matter — values are ignored |
| Auth headers | Ignored | Correctly stripped |
| Pre-request / test scripts | Ignored | Correctly stripped |
| Environment variable definitions | Ignored | Values not needed |
| Query parameters | Ignored | Not compared against spec query params |

### Known limitations

| Scenario | Behaviour |
|---|---|
| `{{version}}` in middle of path (e.g. `{{baseUrl}}/{{version}}/users`) | `/{version}/users` won't match `/users` in spec. Hardcode the version in the path or move it into `baseUrl`. |
| Endpoints with no saved responses | Response codes/fields empty — only request body fields extracted |
| GraphQL collections | Not supported |
| Collection v1.x | Not supported — only v2.1 |

---

## Caching

Suggestions are cached in `.cache/` to avoid re-running the LLM on the same spec.

**Cache key** = SHA256 of:
- Canonical YAML of the spec (sorted keys — JSON vs YAML upload gives the same key)
- Postman collection text (if provided)
- Hash of `backend/agents/prompts.py`

**Automatic invalidation**: Editing `prompts.py` changes the prompts hash and busts the cache automatically.

**Force refresh**: Tick **Force refresh (ignore cache)** before uploading to delete the entry and re-run.

**Manual clearing**:
```bash
rm -rf .cache/
```

The cache file path is logged on every cache hit:
```
Cache hit — 51 suggestion(s) | file: abc123.json | to invalidate: DELETE /app/.cache/abc123.json
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
   ├── POST /suggest — walker → parser → LLM batches, streams via SSE
   └── POST /apply   — applies accepted suggestions, returns diff YAML
```

**Why two servers?** Flask handles browser-facing templating and file uploads. FastAPI handles async LLM streaming with proper SSE support. The browser only talks to Flask; Flask proxies to FastAPI.

---

## Project structure

```
oas-enhancer-util/
│
├── backend/                      # FastAPI backend
│   ├── server.py                 # /suggest (SSE), /apply, /health endpoints
│   ├── pipeline.py               # Walker → LLM pipeline, batching, caching, SSE heartbeat
│   ├── spec_walker.py            # Phase 1: deterministic gap finder
│   ├── postman_parser.py         # Postman v2.1 → clean per-endpoint summary
│   ├── requirements.txt
│   ├── .env.example              # ← all tunables documented here
│   ├── Dockerfile
│   └── agents/
│       ├── prompts.py            # ← EDIT THIS — all customisable rules
│       └── tools.py              # OpenAI function schema for submit_suggestions
│
├── flask_ui/                     # Flask frontend
│   ├── app.py                    # Flask routes + SSE proxy
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
│           ├── backend-pvc.yaml  # PVCs for logs + cache
│           ├── backend-deployment.yaml
│           ├── backend-service.yaml
│           ├── ui-deployment.yaml
│           ├── ui-service.yaml
│           └── ingress.yaml
│
├── tests/
│   ├── test_postman_parser.py         # 37 unit tests for the Postman parser
│   ├── complex_test_spec.yaml         # 8-path OAS spec with intentional gaps
│   ├── complex_test_collection.json   # 10-endpoint Postman collection
│   └── env_heavy_collection.json      # Enterprise-style collection with env vars
│
├── logs/                         # Runtime logs (git-ignored)
│   ├── gaps.log                  # Gap list written before each LLM run
│   └── llm_calls.log             # Full request/response log for both call types
│
├── .cache/                       # Suggestion cache (git-ignored)
│   └── {sha256}.json
│
├── docker-compose.yml
└── README.md
```

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.11+ |
| OpenAI API key | Access to the model set in `SUGGESTER_MODEL` |

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

Logs and cache are persisted in named Docker volumes (`backend_logs`, `backend_cache`) so they survive container restarts.

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

Or use an existing Kubernetes secret:

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

### Key Helm values

| Value | Default | Description |
|---|---|---|
| `registry` | `""` | Docker registry prefix, e.g. `ghcr.io/your-org` |
| `backend.image` | `oas-enhancer-backend` | Backend image name |
| `backend.tag` | `latest` | Backend image tag |
| `backend.openaiApiKey` | `""` | API key (creates a Secret) |
| `backend.existingSecret` | `""` | Use a pre-existing Secret instead |
| `backend.env.SUGGESTER_MODEL` | `gpt-4.1-mini` | Model name |
| `backend.env.BATCH_SIZE` | `50` | Walker gaps per LLM batch |
| `backend.env.BATCH_TOKENS` | `32768` | Max output tokens per gap-filler batch |
| `backend.env.POSTMAN_BATCH_SIZE` | `2` | Postman endpoints per LLM batch |
| `backend.env.POSTMAN_TOKENS` | `32768` | Max output tokens per Postman batch |
| `backend.persistence.logs.size` | `1Gi` | PVC size for logs |
| `backend.persistence.cache.size` | `2Gi` | PVC size for cache |
| `ingress.enabled` | `false` | Enable Ingress resource |
| `ingress.host` | `oas-enhancer.example.com` | Ingress hostname |

---

## Environment variables

### Backend — `backend/.env`

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes | — | API key |
| `OPENAI_BASE_URL` | No | `https://api.openai.com/v1` | Override for Azure OpenAI or a corporate AI gateway |
| `SUGGESTER_MODEL` | No | `gpt-4.1-mini` | Model used for all LLM calls |
| `BATCH_SIZE` | No | `50` | Walker gaps per LLM batch — lower improves quality, increases call count |
| `BATCH_TOKENS` | No | `32768` | Max output tokens per gap-filler batch — must not exceed your model's output cap |
| `POSTMAN_BATCH_SIZE` | No | `2` | Postman endpoints per LLM batch — `1` = maximum coverage |
| `POSTMAN_TOKENS` | No | `32768` | Max output tokens per Postman batch — must not exceed your model's output cap |

**Effect of changing values on accuracy:**

| Change | Effect |
|---|---|
| Reduce `BATCH_SIZE` | Improves accuracy — fewer gaps per call, more focused |
| Increase `BATCH_SIZE` | May reduce accuracy if output is truncated |
| Reduce `BATCH_TOKENS` or `POSTMAN_TOKENS` | Hurts accuracy — output truncated mid-response |
| Increase beyond model cap | API returns 400 Bad Request |
| Reduce `POSTMAN_BATCH_SIZE` | Improves Postman coverage — more focused calls |
| Increase `POSTMAN_BATCH_SIZE` | May miss findings on later endpoints |

**Model tuning guide:**

> `BATCH_TOKENS` and `POSTMAN_TOKENS` are **output token caps**, not input/context limits.
> The value must not exceed your model's maximum output token limit.
> Verify the exact limit from your provider before changing — setting it too high returns a 400 error.

| Model | `SUGGESTER_MODEL` | `BATCH_TOKENS` | `BATCH_SIZE` | `POSTMAN_TOKENS` | `POSTMAN_BATCH_SIZE` |
|---|---|---|---|---|---|
| gpt-4.1-mini | `gpt-4.1-mini` | `32768` | `50` | `32768` | `2` |
| gpt-4.1-nano | `gpt-4.1-nano` | `32768` | `50` | `32768` | `2` |
| gpt-5.1-mini | `gpt-5.1-mini` | `65536`* | `200` | `65536`* | `5` |
| gpt-5.1-nano | `gpt-5.1-nano` | `65536`* | `200` | `65536`* | `5` |

*Verify the actual output token cap for gpt-5.1 models with your provider before deploying.

### Frontend — `flask_ui/.env`

| Variable | Required | Default | Description |
|---|---|---|---|
| `BACKEND_URL` | No | `http://127.0.0.1:8000` | Override if backend runs on a different host/port |
| `REDUNDANCY_UTIL_URL` | No | `#` | URL for the redundancy util link on the home page |

---

## Customising rules

All rules live in **`backend/agents/prompts.py`**. Editing this file automatically busts the suggestion cache.

---

### `WALK_RULES` — what the scanner looks for

Controls Phase 1 (spec walker). These are presence checks only — the walker flags a field as missing if it is absent or empty.

```python
WALK_RULES = WalkRules(
    info_description   = True,   # spec-level info.description
    description        = True,   # all operation / parameter / schema descriptions
    example            = True,   # all missing examples
    x_ai               = True,   # x-ai tag + required sub-tags on every operation

    x_ai_required_tags = ["when-to-use-me", "how-to-use-me", "trigger-me-command"],
)
```

To disable a check (e.g. if your company does not use x-ai):
```python
x_ai = False
```

To change which x-ai sub-tags are required:
```python
x_ai_required_tags = ["intent", "trigger-command", "owner-team"]
```

---

### `VALUE_RULES` — how the LLM generates values

Controls quality of generated content for gap-filler batches. Edit to match your company's documentation standards.

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

Controls Postman-driven corrections. Applied per endpoint batch. Five rules:

| Rule | What it does |
|---|---|
| Missing error codes | If Postman shows 400/404/422/500 not in OAS responses, adds the full response schema |
| Missing request fields | Adds any request body field Postman shows that is absent from spec properties |
| Missing response fields | Adds any response body field Postman shows that is absent from spec properties |
| Naming inconsistencies | If Postman uses `userId` but OAS uses `user_id`, adds the camelCase version |
| Type corrections | If spec says `integer` but Postman shows `"usr_abc123"`, corrects the type |

All `schema_property` values include `type`, `description`, and `example` so re-running on the enhanced spec finds zero new gaps.

---

## API reference

### `POST /suggest` — analyse spec, stream suggestions

**Request** — `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `oas_file` | file | Yes | OAS 3.x `.json`, `.yaml`, or `.yml` |
| `postman_file` | file | No | Postman Collection v2.1 `.json` |
| `force_refresh` | string | No | Send `"true"` to bypass cache and re-run |

**Response** — `text/event-stream` (SSE)

| Event | Payload |
|---|---|
| `start` | `{}` |
| `heartbeat` | `{}` — keepalive every 5s |
| `done` | `{ suggestions[], spec, original_yaml, from_cache? }` |
| `error` | `{ message }` |

Each suggestion:
```json
{
  "path": "/users/{id}",
  "method": "get",
  "location": "responses.200.description",
  "field": "description",
  "value": "Returns the user profile for the given ID.",
  "yaml_context": {
    "context_lines": ["...surrounding YAML..."],
    "inserted_line": "  description: \"Returns the user profile for the given ID.\""
  }
}
```

`field`: `description` | `example` | `x-ai` | `schema_property`

`method`: HTTP method lowercase | `component` | `info`

---

### `POST /apply` — apply accepted suggestions

**Request** — `application/json`
```json
{
  "spec": {},
  "accepted": [
    { "path": "/users/{id}", "method": "get", "location": "responses.200.description",
      "field": "description", "value": "Returns the user profile for the given ID." }
  ]
}
```

**Response** — `application/json`
```json
{ "original_yaml": "...", "spec_yaml": "...", "applied": 42, "failed": 0, "failures": [] }
```

---

### `GET /health`

Returns `{"status": "ok"}`.

---

## Troubleshooting

### Backend does not start — `ModuleNotFoundError`
```bash
source venv/bin/activate    # macOS / Linux
venv\Scripts\activate       # Windows
pip install -r backend/requirements.txt
```

### `openai.AuthenticationError`
`OPENAI_API_KEY` in `backend/.env` is missing or invalid.

### Frontend shows no suggestions
```bash
curl http://localhost:8000/health
```
Confirm `BACKEND_URL` in `flask_ui/.env` matches the backend address.

### Walker finds 0 gaps but LLM still runs
A Postman collection is uploaded. The Postman cross-checker runs even with no walker gaps to find naming inconsistencies, missing error codes, and undocumented fields. This is correct.

### Walker finds 0 gaps, no Postman — "spec is complete"
All required fields are present. Check `WALK_RULES` in `prompts.py` — a rule may be disabled.

### Suggestions show 0 after upload
The spec has no `paths`. Confirm you uploaded an OAS 3.x file, not a Postman collection or Swagger 2.0 file.

### Postman parser extracts 0 endpoints
The collection may be v1.x format. Export from Postman using **Collection v2.1**.

### `400 Bad Request` from OpenAI
`BATCH_TOKENS` or `POSTMAN_TOKENS` is set above your model's output token cap. Check the cap with your provider and reduce accordingly.

### `possible output truncation` warning in logs
A batch returned fewer suggestions than gaps sent — the model may have hit the output token limit. Reduce `BATCH_SIZE`:
```
BATCH_SIZE=30
```

### Postman collection has `{{version}}` in path
Paths like `{{baseUrl}}/{{version}}/users` produce `/{version}/users` after normalisation, which won't match `/users`. Hardcode the version in the path or move it into `baseUrl`.

### How to debug LLM output
```
logs/gaps.log       — full gap list sent to LLM call 1
logs/llm_calls.log  — raw request and response for every LLM call
```
The Postman call user message is logged — search for `## Postman collection — observed endpoints` to verify what the parser extracted.

### Clearing the suggestion cache
Tick **Force refresh** in the UI, or delete manually:
```bash
rm -rf .cache/
```
Cache is automatically invalidated when `prompts.py` changes.
