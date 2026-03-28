"""FastAPI server — suggestion-based OAS review."""
import datetime
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

from .pipeline import init_client, get_suggestions  # noqa: E402

logger = logging.getLogger(__name__)


class _SafeEncoder(json.JSONEncoder):
    """Converts types that yaml.safe_load produces but json cannot handle."""
    def default(self, obj):
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()
        return super().default(obj)


def _dumps(obj) -> str:
    return json.dumps(obj, cls=_SafeEncoder)


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
    Returns YAML of the full operation (or component section) with the suggested
    insertion line marked, preserving indentation.
    """
    path     = suggestion.get("path", "")
    method   = suggestion.get("method", "")
    location = suggestion.get("location", "")
    field    = suggestion.get("field", "")
    value    = suggestion.get("value", "")

    try:
        if method == "component":
            # Navigate to the specific schema, not the whole section
            parts_loc = location.split(".")
            section    = parts_loc[0]                          # e.g. "schemas"
            schema_name = parts_loc[1] if len(parts_loc) > 1 else None  # e.g. "User"
            section_dict = spec.get("components", {}).get(section, {})
            root = section_dict.get(schema_name, {}) if schema_name else section_dict
        elif method == "info":
            root = spec.get("info", {})
        else:
            # Show the full operation object for context
            root = spec.get("paths", {}).get(path, {}).get(method, {})
        if not root:
            return {"context_lines": [], "inserted_line": ""}
    except Exception:
        return {"context_lines": [], "inserted_line": ""}

    # Dump the operation/section — this gives full indented YAML context
    try:
        context_yaml  = yaml.dump(root, allow_unicode=True, sort_keys=False, default_flow_style=False)
        context_lines = context_yaml.split("\n")
        # Remove trailing empty lines, cap at 40 lines
        context_lines = [l for l in context_lines if l.strip()][:40]
    except Exception:
        context_lines = []

    # Determine indentation of the insertion point by navigating to parent
    parts  = location.split(".")
    target = root
    indent = 0
    try:
        for part in parts[:-1]:
            if isinstance(target, list):
                target = target[int(part)]
                indent += 2
            elif isinstance(target, dict):
                target = target.get(part, {})
                indent += 2
    except (KeyError, IndexError, TypeError):
        pass

    # Format the inserted line with matching indentation
    final_key = parts[-1]
    pad = " " * indent
    inserted_line = f"{pad}{final_key}: {json.dumps(value)}"

    return {"context_lines": context_lines, "inserted_line": inserted_line}


def _enrich_suggestions(spec: dict, suggestions: list[dict]) -> list[dict]:
    """Validate, then attach yaml_context to each suggestion.

    Any suggestion that would fail to apply (wrong location, $ref sibling,
    path not found, etc.) is dropped and logged to drops_debug.log.
    """
    import copy
    enriched = []
    dropped  = 0
    for s in suggestions:
        try:
            _apply_suggestion(copy.deepcopy(spec), s)
        except Exception as e:
            logger.warning(
                "Dropping %s %s → %s: %s",
                s.get("method", ""), s.get("path", ""), s.get("location", ""), e,
            )
            dropped += 1
            continue
        enriched.append({**s, "yaml_context": _get_yaml_context(spec, s)})

    if dropped:
        logger.warning("%d suggestion(s) dropped during validation", dropped)

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
                    event["suggestions"] = _enrich_suggestions(event["spec"], event["suggestions"])
                    if not event["suggestions"]:
                        yield f"data: {_dumps({'type': 'error', 'message': 'No applicable suggestions found. The spec may already be complete, or all suggestions were invalid (e.g. targeting $ref sibling locations). Check server logs for details.'})} \n\n"
                        return
                yield f"data: {_dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {_dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/apply")
async def apply_suggestions(payload: dict):
    """
    Apply accepted suggestions to the spec and return original + final YAML.
    Payload: { "spec": {...}, "accepted": [ {path, method, location, field, value}, ... ] }
    """
    import copy
    spec     = payload.get("spec")
    accepted = payload.get("accepted", [])

    if not spec:
        raise HTTPException(status_code=400, detail="spec is required")

    original_yaml = _to_yaml(spec)
    working_spec  = copy.deepcopy(spec)

    applied  = []
    failures = []

    for s in accepted:
        try:
            _apply_suggestion(working_spec, s)
            applied.append(s)
        except Exception as e:
            logger.warning("Could not apply suggestion %s: %s", s, e)
            failures.append({"suggestion": s, "error": str(e)})

    return {
        "original_yaml": original_yaml,
        "spec_yaml":     _to_yaml(working_spec),
        "applied":       len(applied),
        "failed":        len(failures),
        "failures":      failures,
    }


def _apply_suggestion(spec: dict, suggestion: dict) -> None:
    path     = suggestion["path"]
    method   = suggestion["method"]
    location = suggestion["location"]
    value    = suggestion["value"]

    if method == "component":
        root = spec.get("components", {})
    elif method == "info":
        root = spec.get("info")
        if not root:
            raise ValueError("spec has no 'info' section")
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
    if isinstance(target, dict) and "$ref" in target:
        raise ValueError(f"Cannot add '{final_key}' alongside $ref at '{location}' — invalid in OAS 3.0")
    if isinstance(target, list):
        target[int(final_key)] = value
    else:
        target[final_key] = value


@app.get("/health")
async def health():
    return {"status": "ok"}
