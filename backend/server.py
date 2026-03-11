"""FastAPI server — OAS enhancement loop with SSE streaming."""
import json
import logging
import warnings
from contextlib import asynccontextmanager
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s: %(message)s")

# Suppress noisy LiteLLM/Pydantic version-mismatch serialization warnings
warnings.filterwarnings("ignore", category=UserWarning, message="Pydantic serializer warnings")

import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from .loop_runner import init_runners, run_enhancement_loop  # noqa: E402
from .tools.oas_to_postman import oas_to_postman             # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_runners()
    yield


app = FastAPI(title="OAS Enhancer API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _to_json_str(content: bytes, filename: str) -> str:
    text = content.decode("utf-8")
    if filename.endswith((".yaml", ".yml")):
        data = yaml.safe_load(text)
        return json.dumps(data)
    return text


@app.post("/enhance")
async def enhance_oas(
    oas_file: UploadFile = File(...),
    postman_file: UploadFile = File(None),
    instructions: str = Form(""),
):
    """
    Streams SSE events for the review→enhance loop (max 5 iterations).

    Event types (newline-delimited JSON after 'data: '):
      iteration_start   { iteration }
      review_complete   { iteration, data: { satisfied, summary, suggestions } }
      enhance_complete  { iteration, data: { changes_made } }
      done              { original_spec, final_spec, iterations, summary }
    """
    try:
        oas_json = _to_json_str(await oas_file.read(), oas_file.filename or "spec.json")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse OAS file: {e}")

    postman_json = None
    has_postman = False
    if postman_file and postman_file.filename:
        try:
            postman_json = _to_json_str(await postman_file.read(), postman_file.filename)
            has_postman = True
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not parse Postman file: {e}")

    async def event_stream():
        try:
            async for event in run_enhancement_loop(oas_json, postman_json, instructions, has_postman):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/convert")
async def convert_oas_to_postman(oas_file: UploadFile = File(...)):
    """Converts an OAS 3.x spec to a Postman Collection v2.1."""
    try:
        oas_json = _to_json_str(await oas_file.read(), oas_file.filename or "spec.json")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse OAS file: {e}")

    result = oas_to_postman(oas_json)
    try:
        collection = json.loads(result)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Conversion failed: {e}")

    if "error" in collection:
        raise HTTPException(status_code=400, detail=collection["error"])

    return {"collection": collection}


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Serve built React frontend (production / Docker only) ─────────────────
_frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"

if _frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=_frontend_dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        # Serve any file that exists in dist directly (favicons, etc.)
        requested = _frontend_dist / full_path
        if requested.is_file():
            return FileResponse(requested)
        # Fall back to index.html for SPA client-side routing
        return FileResponse(_frontend_dist / "index.html")
