"""
Orchestrates the review → enhance loop using direct HTTP calls to the OpenAI API.
Max iterations is configurable via MAX_ITERATIONS env var (default 5).
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

from .agents.prompts import REVIEWER_INSTRUCTION, ENHANCER_INSTRUCTION
from .agents.tools import REVIEWER_TOOLS, ENHANCER_TOOLS, get_breaking_changes_policy

logger = logging.getLogger(__name__)

MAX_ITERATIONS     = int(os.environ.get("MAX_ITERATIONS", 5))
REVIEWER_TIMEOUT   = 120   # seconds
ENHANCER_TIMEOUT   = 600   # seconds
HEARTBEAT_INTERVAL = 5     # seconds between SSE keepalive pings
REVIEWER_MODEL     = "gpt-4.1-mini"
ENHANCER_MODEL     = "gpt-4.1"

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
    logger.info("HTTP client ready — base=%s, reviewer=%s, enhancer=%s",
                OPENAI_BASE_URL, REVIEWER_MODEL, ENHANCER_MODEL)


async def _chat(payload: dict, timeout: int) -> str:
    """POST /chat/completions with stream=True. Returns concatenated tool call arguments."""
    payload = {**payload, "stream": True}
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
            return tool_args


# ── Agent calls ────────────────────────────────────────────────────────────────

async def _run_reviewer(state: dict, instructions: str, iteration: int) -> dict:
    spec_yaml = _to_yaml(state["current_spec"])
    logger.info("Iter %d | reviewer starting — %d bytes, %d paths",
                iteration, len(spec_yaml), len(state["current_spec"].get("paths", {})))

    user_content = (
        f"Iteration {iteration}: Review the OAS specification below.\n\n"
        f"Breaking changes policy: {get_breaking_changes_policy(state)}\n\n"
        f"OAS Spec (YAML):\n{spec_yaml}"
    )
    if state.get("postman_json"):
        user_content += f"\n\nPostman Collection:\n{state['postman_json']}"
    if instructions:
        user_content += f"\n\nAdditional instructions: {instructions}"
    if state.get("validation_errors"):
        user_content += (
            f"\n\nOAS validation errors that must be fixed ({len(state['validation_errors'])} total):\n"
            + "\n".join(f"- {e}" for e in state["validation_errors"][:20])
        )
    if iteration > 1 and state.get("last_changes"):
        user_content += (
            "\n\nNote: The previous iteration already applied these changes:\n"
            + "\n".join(f"- {c}" for c in state["last_changes"])
            + "\nOnly flag issues still present in the spec above."
        )

    t0 = time.monotonic()
    try:
        tool_args = await _chat({
            "model":       REVIEWER_MODEL,
            "messages":    [{"role": "system", "content": REVIEWER_INSTRUCTION},
                            {"role": "user",   "content": user_content}],
            "tools":       REVIEWER_TOOLS,
            "tool_choice": {"type": "function", "function": {"name": "submit_review"}},
        }, REVIEWER_TIMEOUT)

        elapsed = time.monotonic() - t0
        if not tool_args:
            logger.warning("Iter %d | reviewer returned no tool call (%.1fs)", iteration, elapsed)
            return {"satisfied": False, "summary": "", "suggestions": []}

        args = json.loads(tool_args)
        logger.info("Iter %d | reviewer done in %.1fs — satisfied=%s, %d suggestion(s)",
                    iteration, elapsed, args.get("satisfied"), len(args.get("suggestions", [])))
        return {
            "satisfied":   bool(args.get("satisfied", False)),
            "summary":     args.get("summary", ""),
            "suggestions": args.get("suggestions", []),
        }
    except TimeoutError:
        logger.error("Iter %d | reviewer timed out after %ds", iteration, REVIEWER_TIMEOUT)
    except Exception as e:
        logger.error("Iter %d | reviewer error: %s", iteration, e, exc_info=True)

    return {"satisfied": False, "summary": "", "suggestions": []}


async def _run_enhancer(state: dict, iteration: int) -> dict:
    spec_yaml   = _to_yaml(state["current_spec"])
    suggestions = state.get("review_suggestions", [])

    user_content = (
        f"Breaking changes policy: {get_breaking_changes_policy(state)}\n\n"
        f"Suggestions to apply:\n{json.dumps(suggestions, indent=2)}\n\n"
        f"OAS Spec to enhance (YAML):\n{spec_yaml}"
    )
    if state.get("validation_errors"):
        user_content += (
            f"\n\nOAS validation errors to fix:\n"
            + "\n".join(f"- {e}" for e in state["validation_errors"][:20])
        )
    if state.get("postman_json"):
        user_content += f"\n\nPostman Collection:\n{state['postman_json']}"

    logger.info("Iter %d | enhancer starting — %d bytes", iteration, len(spec_yaml))
    t0 = time.monotonic()
    try:
        tool_args = await _chat({
            "model":       ENHANCER_MODEL,
            "messages":    [{"role": "system", "content": ENHANCER_INSTRUCTION},
                            {"role": "user",   "content": user_content}],
            "tools":       ENHANCER_TOOLS,
            "tool_choice": {"type": "function", "function": {"name": "save_enhanced_spec"}},
            "max_tokens":  32768,
        }, ENHANCER_TIMEOUT)

        elapsed = time.monotonic() - t0
        if not tool_args:
            logger.warning("Iter %d | enhancer returned no tool call (%.1fs)", iteration, elapsed)
            return {"enhanced_spec": state["current_spec"], "changes_made": []}

        try:
            args = json.loads(tool_args)
        except json.JSONDecodeError:
            logger.error("Iter %d | enhancer output truncated (max_tokens hit) — spec too large, no changes applied", iteration)
            return {"enhanced_spec": state["current_spec"], "changes_made": [], "truncated": True}

        enhanced = args.get("enhanced_spec", state["current_spec"])
        changes  = args.get("changes_made", [])

        logger.info("Iter %d | enhancer done in %.1fs — %d change(s), %d paths",
                    iteration, elapsed, len(changes), len(enhanced.get("paths", {})))
        return {"enhanced_spec": enhanced, "changes_made": changes, "truncated": False}

    except TimeoutError:
        logger.error("Iter %d | enhancer timed out after %ds", iteration, ENHANCER_TIMEOUT)
    except Exception as e:
        logger.error("Iter %d | enhancer error: %s", iteration, e, exc_info=True)

    return {"enhanced_spec": state["current_spec"], "changes_made": [], "truncated": True}


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


# ── Main loop ──────────────────────────────────────────────────────────────────

async def run_enhancement_loop(
    oas_json:       str,
    postman_json:   str | None,
    instructions:   str,
    has_postman:    bool,
    max_iterations: int = MAX_ITERATIONS,
) -> AsyncGenerator[dict, None]:
    if not _client:
        raise RuntimeError("HTTP client not initialised — call init_client() first")

    current_spec  = json.loads(oas_json) if isinstance(oas_json, str) else oas_json
    original_spec = json.loads(json.dumps(current_spec))  # deep copy

    path_count = len(current_spec.get("paths", {}))
    spec_title = current_spec.get("info", {}).get("title", "untitled")
    logger.info("Loop starting — %r, %d paths, %d bytes, max_iterations=%d, has_postman=%s",
                spec_title, path_count, len(oas_json), max_iterations, has_postman)

    if path_count == 0:
        logger.error("Spec has no paths — check that the uploaded file is a valid OAS spec")
        yield {"type": "error", "message": "The uploaded spec has no paths. Please upload a valid OpenAPI spec (JSON or YAML) with a 'paths' key."}
        return

    original_validation = _validate_spec(original_spec, "original spec")

    state: dict = {
        "current_spec":       current_spec,
        "postman_json":       postman_json,
        "has_postman":        has_postman,
        "review_suggestions": [],
        "last_changes":       [],
        "validation_errors":  original_validation,
    }

    all_iterations:        list[dict] = []
    last_review:           dict       = {}
    prev_suggestion_count: int        = -1
    stalled_iterations:    int        = 0
    loop_start             = time.monotonic()

    max_iterations = max(1, min(max_iterations, 20))
    for i in range(max_iterations):
        iteration = i + 1

        if stalled_iterations >= 3:
            logger.info("Stopping — no improvement for 3 consecutive iterations")
            break

        yield {"type": "iteration_start", "iteration": iteration}

        # ── Reviewer ──────────────────────────────────────────────────────────
        async for _hb in _await_with_heartbeat(_run_reviewer(state, instructions, iteration), f"iter-{iteration} reviewer"):
            if _hb.get("type") == "heartbeat":
                yield _hb
            else:
                review = _hb

        state["review_suggestions"] = review["suggestions"]
        last_review = review

        yield {"type": "review_complete", "iteration": iteration, "data": review}

        if review["satisfied"] or not review["suggestions"]:
            logger.info("Iter %d | reviewer satisfied, stopping", iteration)
            break

        # ── Enhancer ──────────────────────────────────────────────────────────
        yield {"type": "enhance_start", "iteration": iteration}

        async for _hb in _await_with_heartbeat(_run_enhancer(state, iteration), f"iter-{iteration} enhancer"):
            if _hb.get("type") == "heartbeat":
                yield _hb
            else:
                result = _hb

        if result.get("truncated"):
            logger.warning("Iter %d | enhancer failed — stopping loop", iteration)
            yield {"type": "error", "message": "Enhancer output was truncated or failed. Your spec may be too large — consider splitting it by tag."}
            break

        state["current_spec"]      = result["enhanced_spec"]
        state["last_changes"]      = result["changes_made"]
        state["validation_errors"] = _validate_spec(state["current_spec"], f"iter-{iteration}")
        all_changes                = result["changes_made"]

        all_iterations.append({
            "iteration":      iteration,
            "review_summary": review["summary"],
            "suggestions":    review["suggestions"],
            "changes_made":   all_changes,
        })
        yield {"type": "enhance_complete", "iteration": iteration,
               "data": {"changes_made": all_changes}}

        # Stop if suggestions are not decreasing across iterations
        suggestion_count = len(review["suggestions"])
        if prev_suggestion_count > 0 and suggestion_count >= prev_suggestion_count:
            stalled_iterations += 1
            logger.warning("Stall detected — suggestions %d → %d (stall count %d/3)",
                           prev_suggestion_count, suggestion_count, stalled_iterations)
        else:
            stalled_iterations = 0
        prev_suggestion_count = suggestion_count

    total_elapsed = time.monotonic() - loop_start

    final_validation = (
        _validate_spec(state["current_spec"], "final spec")
        if all_iterations else original_validation
    )
    total_changes = sum(len(it["changes_made"]) for it in all_iterations)

    logger.info("Loop done — %d iteration(s), %d change(s), %.1fs, validation errors: %d → %d",
                len(all_iterations), total_changes, total_elapsed,
                len(original_validation), len(final_validation))

    yield {
        "type":                       "done",
        "original_spec":              original_spec,
        "original_spec_yaml":         _to_yaml(original_spec),
        "final_spec":                 state["current_spec"],
        "final_spec_yaml":            _to_yaml(state["current_spec"]),
        "iterations":                 all_iterations,
        "original_validation_errors": original_validation,
        "validation_errors":          final_validation,
        "summary": {
            "total_iterations":      len(all_iterations),
            "total_changes":         total_changes,
            "completed_by_reviewer": last_review.get("satisfied", False),
        },
    }
