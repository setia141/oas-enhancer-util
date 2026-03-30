"""
Example: your existing FastAPI app with OAS Enhancer router plugged in.

Only 3 things added to your existing server.py:
  1. Import the router and init_client
  2. Call init_client() inside your existing @app.on_event("startup")
  3. app.include_router(oas_router)

Everything else below is your existing code — untouched.
"""
import logging

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

# ── 1. Import OAS Enhancer router ─────────────────────────────────────────────
from backend.router import router as oas_router          # noqa: E402
from backend.pipeline import init_client                 # noqa: E402

logger = logging.getLogger(__name__)

app = FastAPI(title="Your App")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # adjust to match your existing CORS config
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 2. Call init_client() inside your existing startup ────────────────────────
@app.on_event("startup")
async def startup():
    init_client()          # ← add this one line; rest of your startup is unchanged
    logger.info("OAS Enhancer ready")
    # ... your other startup logic here ...


# ── 3. Register the OAS Enhancer router ───────────────────────────────────────
app.include_router(oas_router)
# Routes added: POST /oas-enhancer/suggest
#               POST /oas-enhancer/apply
#               GET  /oas-enhancer/health


# ── Your existing routes below — completely unchanged ─────────────────────────

@app.get("/")
async def root():
    return {"message": "Your existing app"}

# ... rest of your routes ...
