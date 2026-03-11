# OAS Enhancer — React + Google ADK

An AI-powered web application that automatically enhances OpenAPI Specification (OAS) files
with descriptions, examples, and error schemas using a multi-agent review loop.
Built with React (frontend) and Google Agent Development Kit / FastAPI (backend),
secured with Azure AD SSO.

---

## Architecture Overview

```
Browser → React Frontend (Vite :5173)
               │
               │  Azure AD SSO (MSAL — auto redirect, no login button)
               │  Group membership via ID token claims (no admin consent)
               │
               ├── POST /enhance  ──→  FastAPI :8000
               │                           └── Enhancement Loop (up to 5 iterations)
               │                                 ├── Reviewer Agent (GPT-4o)
               │                                 │     reads spec from session state
               │                                 │     writes: satisfied, summary, suggestions
               │                                 │
               │                                 └── Enhancer Agent (GPT-4.1-mini)
               │                                       reads suggestions from session state
               │                                       writes: updated spec, changes_made
               │
               └── POST /convert  ──→  FastAPI :8000
                                           └── Native Python OAS → Postman converter
```

All OAS content passes through **ADK session state** (not message text) to avoid ADK's
template variable substitution which would break on OAS path params like `{id}`.

---

## How the Enhancement Loop Works

```
Upload OAS file
      ↓
For each iteration (max 5):
  1. Reviewer agent (gpt-4.1-mini) runs
       → calls get_breaking_changes_policy
       → calls get_oas_spec (reads spec from session state)
       → calls submit_review (writes satisfied/summary/suggestions to session state)
  2. If satisfied = true OR suggestions = [] → stop loop
  3. Enhancer agent (gpt-4o) runs
       → calls get_review_suggestions (reads suggestions from session state)
       → calls get_oas_spec (reads current spec from session state)
       → applies ALL suggestions
       → calls save_enhanced_spec (writes updated spec + changes to session state)
  4. Next iteration reviewer sees the updated spec
      ↓
done event: original spec, final spec (YAML), per-iteration change history
```

Breaking changes are only allowed when a Postman collection is provided.
Without it, the agents make only additive improvements (descriptions, examples, error schemas).

### Why two different models?

The reviewer only needs to read the spec and output a short suggestion list — `gpt-4.1-mini`
handles this well and is fast. The enhancer must read the full spec, apply all suggestions,
and return the **complete modified spec** as a structured tool call argument. This is a large
output task that smaller models consistently fail on (they fall back to generating plain text
instead of calling the tool), causing timeouts. `gpt-4o` handles it reliably.

---

## Features

- **Multi-agent review loop** — Reviewer identifies issues, Enhancer applies fixes; repeated up to 5 times until the reviewer is satisfied
- **Real-time SSE streaming** — iteration progress, reviewer summaries, and applied changes stream live to the UI as they happen
- **YAML output** — final enhanced spec is delivered as YAML; diff view is YAML-based for readability
- **Side-by-side diff view** — line-level diff between original and enhanced spec (added/removed highlighting)
- **Change history** — per-iteration accordion showing reviewer suggestions vs changes applied
- **Endpoint summary** — visual table of all endpoints with HTTP method, summary, and example count
- **Breaking changes policy** — controlled by whether a Postman collection is uploaded
- **OAS → Postman export** — convert the enhanced spec to Postman Collection v2.1 (native Python, no npm)
- **Drag-and-drop uploads** — for both OAS and Postman files
- **Azure AD SSO** — automatic redirect on load, no sign-in button; session persists across refreshes
- **Group-based access control** — only members of a specific Azure AD security group can access the app

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.11+ | |
| Node.js 18+ | |
| OpenAI API key | For GPT-4.1-mini (reviewer) and GPT-4o (enhancer) |
| Azure AD App Registration | See setup below |

---

## Project Structure

```
sample-adk-app/
├── backend/
│   ├── __init__.py
│   ├── server.py               # FastAPI: /enhance (SSE), /convert, /health
│   ├── loop_runner.py          # ADK runner orchestration — review→enhance loop
│   ├── requirements.txt
│   ├── .env                    # OPENAI_API_KEY (git-ignored)
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── prompts.py          # ← swap your own instructions here
│   │   ├── reviewer.py         # ADK Agent: GPT-4o, reviews OAS spec
│   │   ├── enhancer.py         # ADK Agent: GPT-4.1-mini, applies suggestions
│   │   └── tools.py            # Shared session-state tools (get/save spec, submit review)
│   └── tools/
│       ├── __init__.py
│       └── oas_to_postman.py   # Native Python OAS 3.x → Postman v2.1 converter
│
└── frontend/
    ├── index.html
    ├── vite.config.js          # Proxies /enhance, /convert, /health → :8000
    ├── package.json
    ├── .env                    # Azure AD config (git-ignored)
    ├── .env.example            # Template — copy to .env and fill in values
    └── src/
        ├── main.jsx            # MsalProvider + handleRedirectPromise (before first render)
        ├── App.jsx             # Auth gate + SSE reader + phase state machine
        ├── index.css
        ├── auth/
        │   ├── msalConfig.js   # MSAL instance, scopes, allowed group ID
        │   └── useAuth.js      # Auto-redirect SSO + ID token group claim check
        └── components/
            ├── AccessDenied.jsx    # Shown when user is not in the AD group
            ├── UploadForm.jsx      # Drag-and-drop OAS + Postman upload form
            ├── ProgressTracker.jsx # Live iteration timeline (streams in real time)
            ├── ResultViewer.jsx    # Tabs: YAML, Diff, Change History, Endpoints
            ├── DiffViewer.jsx      # Side-by-side YAML diff with add/remove highlighting
            └── IterationSummary.jsx # Per-iteration accordion: suggestions vs changes
```

---

## Docker (single image — frontend + backend)

The Dockerfile uses a two-stage build:
- **Stage 1 (node:20-alpine)** — builds the React app with Vite
- **Stage 2 (python:3.11-slim)** — runs FastAPI, which serves both the API and the built frontend static files

Azure AD values are baked into the frontend bundle at build time (Vite replaces `import.meta.env.*` at compile time), so they must be passed as `--build-arg`. The OpenAI key is a runtime secret passed via `-e`.

### Build

```bash
cd sample-adk-app

docker build \
  --build-arg VITE_AZURE_CLIENT_ID=<client-id> \
  --build-arg VITE_AZURE_TENANT_ID=<tenant-id> \
  --build-arg VITE_AZURE_ALLOWED_GROUP_ID=<group-object-id> \
  --build-arg VITE_REDIRECT_URI=https://your-domain.com \
  -t oas-enhancer .
```

### Run

```bash
docker run -p 8000:8000 \
  -e OPENAI_API_KEY=your_openai_api_key \
  oas-enhancer
```

App is available at `http://localhost:8000`.

> **Note:** Update `VITE_REDIRECT_URI` and the Azure AD App Registration redirect URI to match your deployment URL before building.

---

## Running Locally

### Option 1 — Without Docker (recommended for development)

Two terminals:

**Terminal 1 — Backend:**
```bash
cd sample-adk-app
backend\Scripts\activate        # Windows
# source backend/bin/activate   # macOS/Linux
uvicorn backend.server:app --reload --port 8000
```

**Terminal 2 — Frontend:**
```bash
cd sample-adk-app/frontend
npm run dev
```

Open `http://localhost:5173` — Vite proxies `/enhance`, `/convert`, `/health` to the backend on port 8000.

---

### Option 2 — With Docker locally

```bash
cd sample-adk-app

docker build \
  --build-arg VITE_AZURE_CLIENT_ID=<client-id> \
  --build-arg VITE_AZURE_TENANT_ID=<tenant-id> \
  --build-arg VITE_AZURE_ALLOWED_GROUP_ID=<group-object-id> \
  --build-arg VITE_REDIRECT_URI=http://localhost:8000 \
  -t oas-enhancer .

docker run -p 8000:8000 -e OPENAI_API_KEY=your_key oas-enhancer
```

Open `http://localhost:8000`.

> **Important:** When running via Docker, `VITE_REDIRECT_URI` must be `http://localhost:8000` (not 5173).
> You must also add `http://localhost:8000` as a redirect URI in your Azure AD App Registration.

**Which to use:** Option 1 for day-to-day development (hot reload, no rebuild on changes).
Option 2 to test the Docker image before deploying to production.

---

## First-time Setup

## Setup

### 1. Azure AD App Registration

1. Go to **Azure Portal → Azure Active Directory → App registrations → New registration**
2. Set **Redirect URI**: `http://localhost:5173` (type: **Single-page application**)
3. Note down the **Application (client) ID** and **Directory (tenant) ID**

**Enable group claims** (required for group access control — no admin consent needed):

4. App registration → **Token configuration → Add groups claim**
5. Select **Security groups** → Save

**Get the allowed group Object ID:**

6. Azure Portal → **Azure Active Directory → Groups** → open your group → **Overview** → copy **Object ID**

---

### 2. Backend

```bash
cd sample-adk-app

# Create and activate a virtual environment (recommended)
python -m venv backend/venv
source backend/venv/bin/activate   # Windows: backend\venv\Scripts\activate

# Install dependencies
pip install -r backend/requirements.txt

# Create backend env file
echo "OPENAI_API_KEY=your_openai_api_key_here" > backend/.env

# Start the FastAPI server
uvicorn backend.server:app --reload --port 8000
```

Server runs at `http://localhost:8000`. Interactive API docs at `http://localhost:8000/docs`.

---

### 3. Frontend

```bash
cd sample-adk-app/frontend

# Copy the env template and fill in your Azure AD values
cp .env.example .env
```

Edit `frontend/.env`:

```env
VITE_AZURE_CLIENT_ID=<your-application-client-id>
VITE_AZURE_TENANT_ID=<your-directory-tenant-id>
VITE_AZURE_ALLOWED_GROUP_ID=<your-security-group-object-id>
VITE_REDIRECT_URI=http://localhost:5173
```

```bash
npm install
npm run dev
# → http://localhost:5173
```

> **Note:** Restart the dev server after any change to `.env` — Vite loads env vars at startup only.

---

## Usage

1. Open `http://localhost:5173` — the app immediately redirects to Microsoft login (no button needed)
2. Sign in with your Azure AD account
3. If your account is in the authorized group, the app loads; otherwise you see an Access Denied screen
4. Upload your **OAS spec** (`.json`, `.yaml`, `.yml`) — required
5. Upload a **Postman Collection v2.1** (`.json`) — optional
   - With Postman: breaking changes allowed — agents can align spec with actual API responses
   - Without Postman: additive only — descriptions, examples, error schemas added; no breaking changes
6. Add any **extra instructions** for the agents — optional (e.g. "focus on error responses")
7. Click **Enhance OAS** — the enhancement loop starts, streaming progress live:
   - Each iteration shows reviewer findings and the changes the enhancer applied
   - Loop stops when the reviewer is satisfied or after 5 iterations
8. Review results in four tabs:
   - **Enhanced YAML** — full spec in a dark-theme code block; copy or download
   - **Diff View** — side-by-side YAML diff between original and enhanced
   - **Change History** — per-iteration accordion of suggestions vs applied changes
   - **Endpoint Summary** — per-endpoint table showing method, summary, and example count
9. Click **Export Postman** to convert the enhanced spec to a Postman Collection and download it

---

## Model Selection

| Agent | Model | Reason |
|---|---|---|
| Reviewer | `gpt-4.1-mini` | Simple task — reads spec, returns a short suggestion list; fast and cheap |
| Enhancer | `gpt-4o` | Hard task — must apply all suggestions and return the **complete modified spec** as a tool call argument; mini models time out on large specs |

Models are configured in `backend/agents/reviewer.py` and `backend/agents/enhancer.py`.

---

## Customising Agent Instructions

To use your own reviewer or enhancer prompts, edit **`backend/agents/prompts.py`**:

```python
REVIEWER_INSTRUCTION = """
Your custom reviewer prompt here...
"""

ENHANCER_INSTRUCTION = """
Your custom enhancer prompt here...
"""
```

This is the only file you need to change to swap in different instructions.

---

## Authentication Flow

```
User opens app
      ↓
MSAL initialises + awaits handleRedirectPromise() before first render
      ↓
No active session → loginRedirect() fires automatically
      ↓
Browser navigates to Microsoft / Azure AD login page
      ↓
User authenticates (transparent if already signed into Microsoft in the browser)
      ↓
Azure AD redirects back to app with auth code
      ↓
MSAL exchanges code for tokens and caches them in sessionStorage
      ↓
ID token `groups` claim checked against VITE_AZURE_ALLOWED_GROUP_ID
      ↓
✅ Member of group  →  App loads (name + email shown in header)
🚫 Not in group     →  Access Denied screen with sign-out option
```

### Group membership — no admin consent required

Group membership is read from the `groups` claim in the Azure AD ID token.
This requires enabling **Token configuration → Security groups** in the App Registration,
but does **not** require `GroupMember.Read.All` admin consent.

If the claim is absent (user is in >200 groups — the "overage" scenario),
the code automatically falls back to the Microsoft Graph `checkMemberGroups` API.

---

## API Reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/enhance` | Upload OAS + optional Postman; streams SSE enhancement events |
| `POST` | `/convert` | Upload OAS file; returns Postman Collection v2.1 JSON |
| `GET` | `/health` | Health check |

### `POST /enhance` — request (multipart/form-data)

| Field | Type | Required | Description |
|---|---|---|---|
| `oas_file` | file | ✅ | OAS spec — `.json`, `.yaml`, or `.yml` |
| `postman_file` | file | ❌ | Postman Collection v2.1 `.json` |
| `instructions` | string | ❌ | Additional instructions for the agents |

### `POST /enhance` — SSE event stream

Events are newline-delimited JSON after `data: `:

| Event type | Payload |
|---|---|
| `iteration_start` | `{ iteration }` |
| `review_complete` | `{ iteration, data: { satisfied, summary, suggestions } }` |
| `enhance_complete` | `{ iteration, data: { changes_made } }` |
| `done` | `{ original_spec, original_spec_yaml, final_spec, final_spec_yaml, iterations, summary }` |
| `error` | `{ message }` |

### `POST /convert` — request (multipart/form-data)

| Field | Type | Required | Description |
|---|---|---|---|
| `oas_file` | file | ✅ | OAS spec — `.json`, `.yaml`, or `.yml` |

### `POST /convert` — response

```json
{
  "collection": { }
}
```

---

## ADK Session State Keys

All agents communicate through ADK session state — no OAS content ever appears in message text.

| Key | Written by | Read by | Description |
|---|---|---|---|
| `current_spec` | loop_runner (init), enhancer | reviewer, enhancer | The live OAS spec dict |
| `postman_json` | loop_runner (init) | reviewer, enhancer | Postman collection string |
| `has_postman` | loop_runner (init) | reviewer, enhancer | Whether Postman was provided |
| `review_satisfied` | reviewer | loop_runner | True when no more improvements needed |
| `review_summary` | reviewer | loop_runner | Overall assessment |
| `review_suggestions` | reviewer | enhancer, loop_runner | List of actionable improvements |
| `last_changes` | enhancer | loop_runner | Changes applied in this iteration |

---

## Environment Variables

### Backend — `backend/.env`

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | OpenAI API key — used for GPT-4.1-mini (reviewer) and GPT-4o (enhancer) |

### Frontend — `frontend/.env`

| Variable | Description |
|---|---|
| `VITE_AZURE_CLIENT_ID` | Azure AD App Registration — Application (client) ID |
| `VITE_AZURE_TENANT_ID` | Azure AD — Directory (tenant) ID |
| `VITE_AZURE_ALLOWED_GROUP_ID` | Object ID of the Azure AD security group allowed to access the app |
| `VITE_REDIRECT_URI` | OAuth redirect URI (default: `http://localhost:5173`) |

---

## Security Notes

- **No vulnerable npm packages** — OAS→Postman conversion is implemented natively in Python,
  replacing the vulnerable `openapi-to-postmanv2` npm package (ajv ReDoS, lodash/js-yaml prototype pollution)
- **`.env` files are git-ignored** — never commit secrets; use `.env.example` as the template
- **ID token group claims** are used instead of the Graph API to avoid the `GroupMember.Read.All` admin consent requirement
- **`sessionStorage`** is used for the MSAL token cache — tokens are cleared when the browser tab closes
- **Session isolation** — each `/enhance` request gets its own ADK session with a unique user ID,
  so concurrent requests cannot share or leak state
- **Agent timeout** — each agent run is guarded by a 120-second `asyncio` timeout; if a run
  exceeds this (e.g. model generating a huge text response instead of calling a tool), the loop
  moves on with whatever state was already written by tool calls, preventing the UI from freezing
