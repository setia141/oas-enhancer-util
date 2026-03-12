# OAS Enhancer — React + Google ADK

An AI-powered web application that enhances OpenAPI Specification (OAS) files with
request/response examples extracted from Postman collections. Built with React (frontend)
and Google Agent Development Kit / FastAPI (backend), secured with Azure AD SSO.

---

## Architecture

```
Browser (React/Vite :5173)
    │
    │  Azure AD SSO (MSAL — redirect flow, no login button)
    │  Group membership verified via ID token claims
    │
    ├── POST /enhance   → FastAPI :8000
    │                       └── ADK Runner
    │                             └── Gemini 2.0 Flash Agent
    │                                   ├── Tool: parse_postman_collection
    │                                   ├── Tool: enhance_oas_with_examples
    │                                   └── Tool: oas_to_postman
    │
    └── POST /convert   → FastAPI :8000
                            └── Native Python OAS→Postman converter
                                (no npm dependency, no vulnerabilities)
```

---

## Features

- **Azure AD SSO** — automatic redirect on load, no sign-in button; session persists across page refreshes
- **Group-based access control** — only members of a specific Azure AD security group can access the app; verified via ID token group claims (no admin consent required)
- **OAS enhancement** — upload an OAS spec (JSON/YAML) + Postman Collection; the ADK agent injects matched examples and generates synthetic ones for unmatched endpoints
- **OAS → Postman export** — convert the enhanced spec to a Postman Collection v2.1 using a native Python converter (no vulnerable npm packages)
- **Drag-and-drop uploads** — for both OAS and Postman files
- **Endpoint summary view** — visual table of all endpoints showing how many examples were added
- **Dark-theme JSON viewer** — copy or download the enhanced spec directly from the UI

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.11+ |
| Node.js | 18+ |
| Google Gemini API key | [Get one at aistudio.google.com](https://aistudio.google.com) |
| Azure AD App Registration | See setup below |

---

## Project Structure

```
sample-adk-app/
├── backend/
│   ├── __init__.py
│   ├── agent.py                    # ADK agent with 3 tools
│   ├── server.py                   # FastAPI: /enhance, /convert, /health
│   ├── requirements.txt
│   ├── .env                        # GOOGLE_API_KEY (git-ignored)
│   └── tools/
│       ├── postman_parser.py       # Tool: parse Postman Collection v2.1
│       ├── oas_enhancer.py         # Tool: inject examples into OAS
│       └── oas_to_postman.py       # Tool: convert OAS 3.x → Postman v2.1
│
└── frontend/
    ├── index.html
    ├── vite.config.js              # Proxies /enhance, /convert, /health → :8000
    ├── package.json
    ├── .env                        # Azure AD config (git-ignored)
    ├── .env.example                # Template — copy to .env and fill in values
    └── src/
        ├── main.jsx                # MsalProvider + handleRedirectPromise
        ├── App.jsx                 # Auth gate → Upload → Result flow
        ├── index.css
        ├── auth/
        │   ├── msalConfig.js       # MSAL instance, scopes, allowed group ID
        │   └── useAuth.js          # Auto-redirect SSO + group claim check
        └── components/
            ├── AzureLogin.jsx      # "Redirecting..." splash (shown < 1 sec)
            ├── AccessDenied.jsx    # Shown when user is not in the AD group
            ├── UploadForm.jsx      # Drag-and-drop file upload form
            └── ResultViewer.jsx    # Enhanced OAS viewer, summary, download
```

---

## Setup

### 1. Azure AD App Registration

1. Go to **Azure Portal → Azure Active Directory → App registrations → New registration**
2. Set **Redirect URI**: `http://localhost:5173` (type: **Single-page application**)
3. Note down the **Application (client) ID** and **Directory (tenant) ID**

**Enable group claims** (required for group access control — no admin consent needed):

4. In your app registration → **Token configuration → Add groups claim**
5. Select **Security groups** → Save

**Get the allowed group Object ID:**

6. Azure Portal → **Azure Active Directory → Groups** → open your group → **Overview** → copy **Object ID**

---

### 2. Backend

```bash
cd sample-adk-app

# Install Python dependencies
pip install -r backend/requirements.txt

# Create backend env file
echo "GOOGLE_API_KEY="" > backend/.env

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

> **Important:** Restart the dev server after any change to `.env` — Vite loads env vars at startup only.

---

## Usage

1. Open `http://localhost:5173` — the app immediately redirects to Microsoft login (no button)
2. Sign in with your Microsoft / Azure AD account
3. If your account is in the authorized group, the app loads directly
4. Upload your **OAS spec** (`.json`, `.yaml`, `.yml`) — required
5. Upload your **Postman Collection v2.1** (`.json`) — optional
6. Add any **extra instructions** for the AI agent — optional
7. Click **Enhance OAS** — the ADK agent will:
   - Parse the Postman collection to extract request/response examples
   - Match Postman endpoints to OAS paths (handles `{param}` vs `:param` styles)
   - Inject real examples into matching endpoints
   - Generate synthetic examples from schemas for unmatched endpoints
8. Review results:
   - **Enhanced JSON tab** — full spec with dark-theme syntax view
   - **Endpoint Summary tab** — per-endpoint example count badge
9. Actions:
   - **Copy** — copy JSON to clipboard
   - **Download** — save enhanced OAS as `*_enhanced.json`
   - **Export Postman** — convert enhanced OAS to Postman Collection v2.1 and download

---

## Authentication Flow

```
User opens app
    ↓
MSAL initializes + processes any redirect response (awaited before first render)
    ↓
No active session → loginRedirect() fires automatically
    ↓
Browser navigates to Microsoft / Azure AD login
    ↓
User authenticates (transparent if already signed into Microsoft in the browser)
    ↓
Azure AD redirects back to app with auth code
    ↓
MSAL exchanges code for tokens
    ↓
ID token groups claim checked against VITE_AZURE_ALLOWED_GROUP_ID
    ↓
✅ Member of group  →  App loads (display name + email shown in header)
🚫 Not in group     →  Access Denied screen with sign-out option
```

### Group membership check — no admin consent needed

Group membership is verified using the `groups` claim embedded in the Azure AD ID token.
This approach requires configuring **Token configuration → Security groups claim** in the
Azure AD App Registration, but does **not** require `GroupMember.Read.All` admin consent.

If the groups claim is absent (e.g. user is in >200 groups — the "overage" scenario),
the code automatically falls back to the Microsoft Graph `checkMemberGroups` API.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/enhance` | Upload OAS + optional Postman file; returns enhanced OAS JSON |
| `POST` | `/convert` | Upload OAS file; returns Postman Collection v2.1 JSON |
| `GET` | `/health` | Health check — returns agent name and status |

### `POST /enhance` — request (multipart/form-data)

| Field | Type | Required | Description |
|---|---|---|---|
| `oas_file` | file | ✅ | OAS spec — `.json`, `.yaml`, or `.yml` |
| `postman_file` | file | ❌ | Postman Collection v2.1 `.json` |
| `instructions` | string | ❌ | Additional instructions for the agent |

### `POST /enhance` — response

```json
{
  "enhanced_oas": { /* full OAS object with examples injected */ }
}
```

### `POST /convert` — request (multipart/form-data)

| Field | Type | Required | Description |
|---|---|---|---|
| `oas_file` | file | ✅ | OAS spec — `.json`, `.yaml`, or `.yml` |

### `POST /convert` — response

```json
{
  "collection": { /* Postman Collection v2.1 object */ }
}
```

---

## ADK Agent Tools

| Tool | Description |
|---|---|
| `parse_postman_collection` | Parses Postman Collection v2.1 JSON; extracts request bodies, response examples, headers per endpoint; normalizes URL paths to OAS `{param}` style |
| `enhance_oas_with_examples` | Injects examples into OAS `requestBody.content.examples` and `responses.content.examples`; smart path matching handles `{param}` vs `:param` style differences |
| `oas_to_postman` | Converts OAS 3.x to Postman Collection v2.1; groups endpoints by tag into folders; generates example values from JSON Schema; pure Python — no npm dependency |

---

## Environment Variables

### Backend — `backend/.env`

| Variable | Description |
|---|---|
| `GOOGLE_API_KEY` | Gemini API key from [aistudio.google.com](https://aistudio.google.com) |

### Frontend — `frontend/.env`

| Variable | Description |
|---|---|
| `VITE_AZURE_CLIENT_ID` | Azure AD App Registration — Application (client) ID |
| `VITE_AZURE_TENANT_ID` | Azure AD — Directory (tenant) ID |
| `VITE_AZURE_ALLOWED_GROUP_ID` | Object ID of the Azure AD security group allowed to access the app |
| `VITE_REDIRECT_URI` | OAuth redirect URI (default: `http://localhost:5173`) |

---

## Security Notes

- **No vulnerable npm packages** — OAS→Postman conversion is implemented natively in Python, replacing the vulnerable `openapi-to-postmanv2` npm package (`ajv` ReDoS, `lodash`/`js-yaml` prototype pollution)
- **`.env` files are git-ignored** — never commit secrets; use `.env.example` as the template
- **ID token group claims** are used instead of Graph API to avoid `GroupMember.Read.All` admin consent requirement
- **`sessionStorage`** is used for MSAL token cache — tokens are cleared when the browser tab closes
