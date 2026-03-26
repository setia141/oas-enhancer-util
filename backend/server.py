"""FastAPI server — OAS enhancement loop with SSE streaming."""
import json
import logging
import warnings
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s: %(message)s")

# Suppress noisy LiteLLM/Pydantic version-mismatch serialization warnings
warnings.filterwarnings("ignore", category=UserWarning, message="Pydantic serializer warnings")

import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

load_dotenv()

from .loop_runner import init_client, run_enhancement_loop, MAX_ITERATIONS   # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_client()
    yield


app = FastAPI(title="OAS Enhancer API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _to_json_str(content: bytes, filename: str) -> str:
    text = content.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    if filename.endswith((".yaml", ".yml")):
        data = yaml.safe_load(text)
        return json.dumps(data)
    return text


@app.get("/config")
async def get_config():
    """Returns server-side configuration visible to the UI."""
    return {"max_iterations": MAX_ITERATIONS}


@app.post("/enhance")
async def enhance_oas(
    oas_file: UploadFile = File(...),
    postman_file: UploadFile = File(None),
    instructions: str = Form(""),
    max_iterations: int = Form(MAX_ITERATIONS),
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
            async for event in run_enhancement_loop(oas_json, postman_json, instructions, has_postman, max_iterations):
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


@app.get("/health")
async def health():
    return {"status": "ok"}
