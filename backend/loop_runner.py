"""
Single-pass OAS enhancer using direct HTTP calls to the OpenAI API.
Sends the full spec, receives only changed paths/components, merges back.
Yields SSE-ready dicts for streaming to the frontend.
"""
import asyncio
import json
import logging
import os
import time
from typing import AsyncGenerator

import httpx
import yaml
from openapi_spec_validator import validate as _oas_validate

from .agents.prompts import ENHANCER_INSTRUCTION
from .agents.tools import ENHANCER_TOOLS, get_breaking_changes_policy

logger = logging.getLogger(__name__)

# ── LLM call logger (writes to llm_calls.log) ──────────────────────────────────
_llm_logger = logging.getLogger("llm_calls")
_llm_logger.setLevel(logging.DEBUG)
_llm_logger.propagate = False
_llm_log_handler = logging.FileHandler("llm_calls.log", encoding="utf-8")
_llm_log_handler.setFormatter(logging.Formatter("%(asctime)s\n%(message)s\n"))
_llm_logger.addHandler(_llm_log_handler)

ENHANCER_TIMEOUT   = 600   # seconds
HEARTBEAT_INTERVAL = 5     # seconds between SSE keepalive pings
ENHANCER_MODEL     = "gpt-4.1-mini"

OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_API_KEY  = os.environ.get("OPENAI_API_KEY", "")

_client: httpx.AsyncClient | None = None


# ── Spec helpers ───────────────────────────────────────────────────────────────

def _validate_spec(spec: dict, label: str) -> list[str]:
    """Returns list of OAS validation error strings (empty = valid)."""
    try:
        _oas_validate(spec)
        return []
    except Exception as exc:
        errors = str(exc).splitlines()
        logger.warning("%s: %d OAS validation error(s)", label, len(errors))
        return errors


def _to_yaml(spec: dict) -> str:
    return yaml.dump(spec, allow_unicode=True, sort_keys=False, default_flow_style=False)


# ── HTTP client ────────────────────────────────────────────────────────────────

def init_client() -> None:
    global _client
    _client = httpx.AsyncClient(
        base_url=OPENAI_BASE_URL,
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        http2=False,
        timeout=httpx.Timeout(ENHANCER_TIMEOUT + 30, connect=10.0),
    )
    logger.info("HTTP client ready — base=%s, model=%s", OPENAI_BASE_URL, ENHANCER_MODEL)


async def _chat(payload: dict, timeout: int) -> str:
    """POST /chat/completions with stream=True. Returns concatenated tool call arguments."""
    payload = {**payload, "stream": True}
    _llm_logger.debug("REQUEST\n%s", json.dumps(payload, indent=2, default=str))
    async with asyncio.timeout(timeout):
        async with _client.stream("POST", "/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            tool_args = ""
            async for line in resp.aiter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                chunk = json.loads(line[6:])
                for choice in chunk.get("choices", []):
                    for tc in (choice.get("delta", {}).get("tool_calls") or []):
                        tool_args += tc.get("function", {}).get("arguments", "")
    _llm_logger.debug("RESPONSE\n%s", tool_args)
    return tool_args


# ── Enhancer call ──────────────────────────────────────────────────────────────

async def _run_enhancer(oas_spec: dict, postman_text: str | None, has_postman: bool,
                        validation_errors: list[str]) -> dict:
    spec_yaml = _to_yaml(oas_spec)
    logger.info("Enhancer starting — %d bytes, %d paths", len(spec_yaml), len(oas_spec.get("paths", {})))

    user_content = (
        f"Breaking changes policy: {get_breaking_changes_policy(has_postman)}\n\n"
        f"OAS Spec (YAML):\n{spec_yaml}"
    )
    if validation_errors:
        user_content += (
            f"\n\nOAS validation errors to fix:\n"
            + "\n".join(f"- {e}" for e in validation_errors[:20])
        )
    if postman_text:
        user_content += f"\n\nPostman Collection:\n{postman_text}"

    t0 = time.monotonic()
    try:
        tool_args = await _chat({
            "model":       ENHANCER_MODEL,
            "messages":    [{"role": "system", "content": ENHANCER_INSTRUCTION},
                            {"role": "user",   "content": user_content}],
            "tools":       ENHANCER_TOOLS,
            "tool_choice": {"type": "function", "function": {"name": "save_enhanced_spec"}},
            "max_tokens":  16384,
        }, ENHANCER_TIMEOUT)

        elapsed = time.monotonic() - t0
        if not tool_args:
            logger.warning("Enhancer returned no tool call (%.1fs)", elapsed)
            return {"changed_paths": {}, "changed_components": {}, "changes_made": []}

        try:
            args = json.loads(tool_args)
        except json.JSONDecodeError:
            logger.error("Enhancer output truncated (max_tokens hit)")
            return {"changed_paths": {}, "changed_components": {}, "changes_made": [], "truncated": True}

        changed_paths      = args.get("changed_paths", {})
        changed_components = args.get("changed_components", {})
        changes_made       = args.get("changes_made", [])

        logger.info("Enhancer done in %.1fs — %d path(s) changed, %d change(s)",
                    elapsed, len(changed_paths), len(changes_made))
        return {
            "changed_paths":      changed_paths,
            "changed_components": changed_components,
            "changes_made":       changes_made,
            "truncated":          False,
        }

    except TimeoutError:
        logger.error("Enhancer timed out after %ds", ENHANCER_TIMEOUT)
    except Exception as e:
        logger.error("Enhancer error: %s", e, exc_info=True)

    return {"changed_paths": {}, "changed_components": {}, "changes_made": [], "truncated": True}


# ── Heartbeat helper ───────────────────────────────────────────────────────────

async def _await_with_heartbeat(coro, label: str = ""):
    """Run a coroutine, yielding heartbeat pings every HEARTBEAT_INTERVAL seconds."""
    task    = asyncio.create_task(coro)
    elapsed = 0
    while not task.done():
        done, _ = await asyncio.wait({task}, timeout=HEARTBEAT_INTERVAL)
        if not done:
            elapsed += HEARTBEAT_INTERVAL
            if elapsed % 30 == 0:
                logger.info("Still waiting for %s — %ds elapsed", label, elapsed)
            yield {"type": "heartbeat"}
    yield task.result()


# ── Main ──────────────────────────────────────────────────────────────────────

async def run_enhancement_loop(
    oas_spec:     dict,
    postman_text: str | None,
    has_postman:  bool,
) -> AsyncGenerator[dict, None]:
    if not _client:
        raise RuntimeError("HTTP client not initialised — call init_client() first")

    original_spec = json.loads(json.dumps(oas_spec))  # deep copy

    path_count = len(oas_spec.get("paths", {}))
    spec_title = oas_spec.get("info", {}).get("title", "untitled")
    logger.info("Enhancement starting — %r, %d paths, has_postman=%s",
                spec_title, path_count, has_postman)

    if path_count == 0:
        yield {"type": "error", "message": "The uploaded spec has no paths. Please upload a valid OpenAPI spec (JSON or YAML) with a 'paths' key."}
        return

    original_validation = _validate_spec(original_spec, "original spec")

    yield {"type": "enhance_start"}

    result = None
    async for _hb in _await_with_heartbeat(
        _run_enhancer(oas_spec, postman_text, has_postman, original_validation),
        "enhancer"
    ):
        if _hb.get("type") == "heartbeat":
            yield _hb
        else:
            result = _hb

    if result.get("truncated"):
        yield {"type": "error", "message": "Enhancer output was truncated or failed. Your spec may be too large — consider splitting it by tag."}
        return

    # Merge changed paths/components back into the original spec
    final_spec = json.loads(json.dumps(original_spec))

    changed_paths = result["changed_paths"]
    if changed_paths:
        for path, content in changed_paths.items():
            final_spec["paths"][path] = content
        logger.info("Merged %d changed path(s) into spec", len(changed_paths))

    changed_components = result.get("changed_components") or {}
    if changed_components:
        final_spec.setdefault("components", {})
        for section, items in changed_components.items():
            final_spec["components"].setdefault(section, {})
            final_spec["components"][section].update(items)
        logger.info("Merged changed components: %s", list(changed_components.keys()))

    final_validation = _validate_spec(final_spec, "final spec")

    logger.info("Enhancement done — %d change(s), validation errors: %d → %d",
                len(result["changes_made"]), len(original_validation), len(final_validation))

    yield {
        "type":                       "done",
        "original_spec":              original_spec,
        "original_spec_yaml":         _to_yaml(original_spec),
        "final_spec":                 final_spec,
        "final_spec_yaml":            _to_yaml(final_spec),
        "changes_made":               result["changes_made"],
        "original_validation_errors": original_validation,
        "validation_errors":          final_validation,
    }
