"""
Integration examples for embedding OAS Enhancer into an existing app.

FastAPI backend — add 3 things to your existing server.py:
  1. Import the router and init_client
  2. Call init_client() inside your existing @app.on_event("startup")
  3. app.include_router(oas_router)

Flask frontend — add 2 things to your existing app.py:
  1. Import the blueprint
  2. app.register_blueprint(oas_blueprint)

See comments below for each.
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


# ══════════════════════════════════════════════════════════════════════════════
# Flask frontend integration (your existing flask app.py)
# ══════════════════════════════════════════════════════════════════════════════
#
# from flask_ui.blueprint import oas_blueprint   # ← 1. import
#
# app.register_blueprint(oas_blueprint)          # ← 2. register
#
# Routes added: GET  /oas-enhancer/         — UI page
#               POST /oas-enhancer/suggest  — SSE proxy to backend
#               POST /oas-enhancer/apply    — apply proxy to backend
