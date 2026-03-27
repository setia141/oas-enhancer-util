"""FastAPI server — suggestion-based OAS review."""
import json
import logging
import warnings
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s: %(message)s")
warnings.filterwarnings("ignore", category=UserWarning, message="Pydantic serializer warnings")

import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

load_dotenv()

from .loop_runner import init_client, get_suggestions  # noqa: E402

logger = logging.getLogger(__name__)


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


def _parse_oas(content: bytes, filename: str) -> dict:
    text = content.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    if filename.endswith((".yaml", ".yml")):
        return yaml.safe_load(text)
    return json.loads(text)


def _to_yaml(spec: dict) -> str:
    return yaml.dump(spec, allow_unicode=True, sort_keys=False, default_flow_style=False)


def _get_yaml_context(spec: dict, suggestion: dict) -> dict:
    """
    Returns the YAML lines of the parent object where the suggestion would be inserted,
    plus the formatted line that would be added.
    """
    path     = suggestion.get("path", "")
    method   = suggestion.get("method", "")
    location = suggestion.get("location", "")
    field    = suggestion.get("field", "")
    value    = suggestion.get("value", "")

    # Resolve root object for this suggestion
    try:
        if method == "component":
            root = spec.get("components", {})
        else:
            root = spec.get("paths", {}).get(path, {}).get(method, {})
        if not root:
            return {"context_lines": [], "inserted_line": ""}
    except Exception:
        return {"context_lines": [], "inserted_line": ""}

    # Navigate to the parent of the target field
    parts  = location.split(".")
    target = root
    try:
        for part in parts[:-1]:
            if isinstance(target, list):
                target = target[int(part)]
            elif isinstance(target, dict):
                target = target.get(part, {})
    except (KeyError, IndexError, TypeError):
        target = root

    # Dump parent object — cap at 10 lines to keep context readable
    try:
        context_yaml  = yaml.dump(target, allow_unicode=True, sort_keys=False, default_flow_style=False)
        context_lines = [l for l in context_yaml.split("\n") if l.strip()][:10]
    except Exception:
        context_lines = []

    # Format the line that would be inserted
    final_key = parts[-1]
    if field == "x-ai":
        inserted_line = f"{final_key}: true"
    elif isinstance(value, str):
        # Quote if contains special YAML chars
        inserted_line = f"{final_key}: {json.dumps(value)}"
    else:
        inserted_line = f"{final_key}: {json.dumps(value)}"

    return {"context_lines": context_lines, "inserted_line": inserted_line}


def _enrich_suggestions(spec: dict, suggestions: list[dict]) -> list[dict]:
    """Attach yaml_context to each suggestion."""
    enriched = []
    for s in suggestions:
        ctx = _get_yaml_context(spec, s)
        enriched.append({**s, "yaml_context": ctx})
    return enriched


@app.post("/suggest")
async def suggest(
    oas_file: UploadFile = File(...),
    postman_file: UploadFile = File(None),
):
    """Streams SSE events: start → heartbeat* → done{suggestions, spec, original_yaml} | error"""
    try:
        oas_spec = _parse_oas(await oas_file.read(), oas_file.filename or "spec.json")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse OAS file: {e}")

    postman_text = None
    has_postman  = False
    if postman_file and postman_file.filename:
        try:
            postman_text = (await postman_file.read()).decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
            has_postman  = True
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not read Postman file: {e}")

    async def event_stream():
        try:
            async for event in get_suggestions(oas_spec, postman_text, has_postman):
                if event.get("type") == "done":
                    # Enrich suggestions with YAML context before sending
                    event["suggestions"] = _enrich_suggestions(event["spec"], event["suggestions"])
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/apply")
async def apply_suggestions(payload: dict):
    """
    Apply accepted suggestions to the spec and return the final YAML.
    Payload: { "spec": {...}, "accepted": [ {path, method, location, field, value}, ... ] }
    """
    spec     = payload.get("spec")
    accepted = payload.get("accepted", [])

    if not spec:
        raise HTTPException(status_code=400, detail="spec is required")

    applied  = []
    failures = []

    for s in accepted:
        try:
            _apply_suggestion(spec, s)
            applied.append(s)
        except Exception as e:
            logger.warning("Could not apply suggestion %s: %s", s, e)
            failures.append({"suggestion": s, "error": str(e)})

    return {
        "spec":      spec,
        "spec_yaml": _to_yaml(spec),
        "applied":   len(applied),
        "failed":    len(failures),
        "failures":  failures,
    }


def _apply_suggestion(spec: dict, suggestion: dict) -> None:
    path     = suggestion["path"]
    method   = suggestion["method"]
    location = suggestion["location"]
    value    = suggestion["value"]

    if method == "component":
        root = spec.get("components", {})
    else:
        root = spec.get("paths", {}).get(path, {}).get(method, {})
        if not root:
            raise ValueError(f"Operation not found: {method.upper()} {path}")

    parts  = location.split(".")
    target = root
    for part in parts[:-1]:
        if isinstance(target, list):
            target = target[int(part)]
        else:
            target = target[part]

    final_key = parts[-1]
    if isinstance(target, list):
        target[int(final_key)] = value
    else:
        target[final_key] = value


@app.get("/health")
async def health():
    return {"status": "ok"}
