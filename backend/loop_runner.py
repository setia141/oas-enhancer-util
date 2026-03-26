"""
Orchestrates the review → enhance loop using the OpenAI API directly.
Max iterations is configurable via MAX_ITERATIONS env var (default 5).
Yields SSE-ready dicts for streaming to the frontend.
"""
import asyncio
import json
import logging
import os
import time
from typing import AsyncGenerator

import yaml
from openai import AsyncOpenAI
from openapi_spec_validator import validate as _oas_validate

from .agents.prompts import REVIEWER_INSTRUCTION, ENHANCER_INSTRUCTION
from .agents.tools import REVIEWER_TOOLS, ENHANCER_TOOLS, get_breaking_changes_policy

logger = logging.getLogger(__name__)

MAX_ITERATIONS     = int(os.environ.get("MAX_ITERATIONS", 5))
REVIEWER_TIMEOUT   = 120   # seconds
ENHANCER_TIMEOUT   = 300   # seconds — large specs can take time
HEARTBEAT_INTERVAL = 5     # seconds between SSE keepalive pings
REVIEWER_MODEL     = "gpt-4.1-mini"
ENHANCER_MODEL     = "gpt-4.1"

_OAS_TOP_LEVEL = {"openapi", "info", "servers", "paths", "components", "security", "tags", "externalDocs"}
_HTTP_METHODS  = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}

_client: AsyncOpenAI | None = None


# ── Spec post-processing ───────────────────────────────────────────────────────

def _sanitize_spec(spec: dict) -> dict:
    """Fix common model mistakes in the returned spec."""
    # Move paths accidentally placed at the top level into paths dict
    for k in [k for k in list(spec.keys()) if k.startswith("/")]:
        logger.warning("Moving misplaced top-level path into paths: %s", k)
        spec.setdefault("paths", {})[k] = spec.pop(k)

    # Remove junk top-level keys the model sometimes adds (e.g. "changes_made")
    for k in [k for k in list(spec.keys()) if k not in _OAS_TOP_LEVEL and not k.startswith("x-")]:
        logger.warning("Removing unexpected top-level key: %s", k)
        del spec[k]

    # Remove non-path keys from paths dict — but preserve x- extensions
    if isinstance(spec.get("paths"), dict):
        for k in [k for k in list(spec["paths"].keys())
                  if not k.startswith("/") and not k.startswith("x-")]:
            logger.warning("Removing non-path key from paths: %s", k)
            del spec["paths"][k]

    return spec


def _restore_dropped_paths(original: dict, enhanced: dict) -> dict:
    """
    Re-insert any paths or operations the model omitted from its output.
    Models sometimes truncate large specs — this ensures no endpoints are lost.
    Enhanced content takes priority; we only fill in what's missing.
    """
    for key, value in original.items():
        if key not in enhanced:
            enhanced[key] = value

    orig_paths = {k: v for k, v in original.get("paths", {}).items() if k.startswith("/")}
    enh_paths  = enhanced.setdefault("paths", {})
    restored   = []
    for path, path_item in orig_paths.items():
        if path not in enh_paths:
            enh_paths[path] = path_item
            restored.append(path)
        else:
            for method, operation in path_item.items():
                if method not in enh_paths[path]:
                    enh_paths[path][method] = operation

    if restored:
        logger.warning("Restored %d dropped path(s): %s", len(restored), restored)
    return enhanced


def _validate_spec(spec: dict, label: str) -> list[str]:
    """Returns list of OAS validation error strings (empty = valid)."""
    try:
        _oas_validate(spec)
        return []
    except Exception as exc:
        errors = str(exc).splitlines()
        logger.warning("%s: %d OAS validation error(s)", label, len(errors))
        return errors


# ── OpenAI client ──────────────────────────────────────────────────────────────

def init_client() -> None:
    global _client
    _client = AsyncOpenAI()
    logger.info("OpenAI client ready — reviewer=%s, enhancer=%s", REVIEWER_MODEL, ENHANCER_MODEL)


# ── Agent calls ────────────────────────────────────────────────────────────────

async def _run_reviewer(state: dict, instructions: str, iteration: int) -> dict:
    spec_json = json.dumps(state["current_spec"], indent=2)
    logger.info("Iter %d | reviewer starting — %d bytes, %d paths",
                iteration, len(spec_json), len(state["current_spec"].get("paths", {})))

    user_content = (
        f"Iteration {iteration}: Review the OAS specification below.\n\n"
        f"Breaking changes policy: {get_breaking_changes_policy(state)}\n\n"
        f"OAS Spec:\n{spec_json}"
    )
    if state.get("postman_json"):
        user_content += f"\n\nPostman Collection:\n{state['postman_json']}"
    if instructions:
        user_content += f"\n\nAdditional instructions: {instructions}"
    if iteration > 1 and state.get("last_changes"):
        user_content += (
            "\n\nNote: The previous iteration already applied these changes:\n"
            + "\n".join(f"- {c}" for c in state["last_changes"])
            + "\nOnly flag issues still present in the spec above."
        )

    t0 = time.monotonic()
    try:
        response = await asyncio.wait_for(
            _client.chat.completions.create(
                model=REVIEWER_MODEL,
                messages=[
                    {"role": "system", "content": REVIEWER_INSTRUCTION},
                    {"role": "user",   "content": user_content},
                ],
                tools=REVIEWER_TOOLS,
                tool_choice={"type": "function", "function": {"name": "submit_review"}},
            ),
            timeout=REVIEWER_TIMEOUT,
        )
        elapsed = time.monotonic() - t0
        choice  = response.choices[0]

        if not choice.message.tool_calls:
            logger.warning("Iter %d | reviewer returned no tool call (finish_reason=%s, %.1fs)",
                           iteration, choice.finish_reason, elapsed)
            return {"satisfied": False, "summary": "", "suggestions": []}

        args = json.loads(choice.message.tool_calls[0].function.arguments)
        logger.info("Iter %d | reviewer done in %.1fs — satisfied=%s, %d suggestion(s)",
                    iteration, elapsed, args.get("satisfied"), len(args.get("suggestions", [])))
        return {
            "satisfied":   bool(args.get("satisfied", False)),
            "summary":     args.get("summary", ""),
            "suggestions": args.get("suggestions", []),
        }
    except asyncio.TimeoutError:
        logger.error("Iter %d | reviewer timed out after %ds", iteration, REVIEWER_TIMEOUT)
    except Exception as e:
        logger.error("Iter %d | reviewer error: %s", iteration, e, exc_info=True)

    return {"satisfied": False, "summary": "", "suggestions": []}


async def _run_enhancer(state: dict, iteration: int) -> dict:
    spec_json   = json.dumps(state["current_spec"], indent=2)
    suggestions = state.get("review_suggestions", [])
    path_count  = len(state["current_spec"].get("paths", {}))
    logger.info("Iter %d | enhancer starting — %d bytes, %d paths, %d suggestion(s)",
                iteration, len(spec_json), path_count, len(suggestions))

    user_content = (
        f"CRITICAL — BREAKING CHANGES POLICY (obey strictly): {get_breaking_changes_policy(state)}\n\n"
        f"Iteration {iteration}: Apply ALL suggestions to the OAS spec below.\n\n"
        f"IMPORTANT: The input spec has {path_count} paths. Your output MUST contain all {path_count} paths.\n\n"
        f"Suggestions:\n{json.dumps(suggestions, indent=2)}\n\n"
        f"Current OAS Spec:\n{spec_json}"
    )
    if state.get("postman_json"):
        user_content += f"\n\nPostman Collection:\n{state['postman_json']}"

    t0 = time.monotonic()
    try:
        response = await asyncio.wait_for(
            _client.chat.completions.create(
                model=ENHANCER_MODEL,
                messages=[
                    {"role": "system", "content": ENHANCER_INSTRUCTION},
                    {"role": "user",   "content": user_content},
                ],
                tools=ENHANCER_TOOLS,
                tool_choice={"type": "function", "function": {"name": "save_enhanced_spec"}},
                max_tokens=32768,
            ),
            timeout=ENHANCER_TIMEOUT,
        )
        elapsed = time.monotonic() - t0
        choice  = response.choices[0]

        if not choice.message.tool_calls:
            logger.warning("Iter %d | enhancer returned no tool call (finish_reason=%s, %.1fs)",
                           iteration, choice.finish_reason, elapsed)
            return {"enhanced_spec": state["current_spec"], "changes_made": []}

        args     = json.loads(choice.message.tool_calls[0].function.arguments)
        enhanced = args.get("enhanced_spec", state["current_spec"])

        if isinstance(enhanced, str):
            try:
                enhanced = json.loads(enhanced)
            except Exception:
                logger.warning("Iter %d | enhanced_spec was not valid JSON — keeping original", iteration)
                return {"enhanced_spec": state["current_spec"], "changes_made": []}

        enhanced = _sanitize_spec(enhanced)
        enhanced = _restore_dropped_paths(state["current_spec"], enhanced)
        changes  = args.get("changes_made", [])

        spec_changed = json.dumps(enhanced, sort_keys=True) != json.dumps(state["current_spec"], sort_keys=True)
        logger.info("Iter %d | enhancer done in %.1fs — %d change(s), paths %d→%d, spec_changed=%s",
                    iteration, elapsed, len(changes),
                    path_count, len(enhanced.get("paths", {})), spec_changed)

        if not spec_changed:
            logger.warning("Iter %d | enhancer returned spec unchanged", iteration)

        return {"enhanced_spec": enhanced, "changes_made": changes}

    except asyncio.TimeoutError:
        logger.error("Iter %d | enhancer timed out after %ds", iteration, ENHANCER_TIMEOUT)
    except Exception as e:
        logger.error("Iter %d | enhancer error: %s", iteration, e, exc_info=True)

    return {"enhanced_spec": state["current_spec"], "changes_made": []}


# ── Heartbeat helper ───────────────────────────────────────────────────────────

async def _await_with_heartbeat(coro):
    """Run a coroutine, yielding heartbeat pings every HEARTBEAT_INTERVAL seconds."""
    task = asyncio.create_task(coro)
    while not task.done():
        done, _ = await asyncio.wait({task}, timeout=HEARTBEAT_INTERVAL)
        if not done:
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
        raise RuntimeError("OpenAI client not initialised — call init_client() first")

    current_spec  = json.loads(oas_json) if isinstance(oas_json, str) else oas_json
    original_spec = json.loads(json.dumps(current_spec))  # deep copy

    path_count = len(current_spec.get("paths", {}))
    spec_title = current_spec.get("info", {}).get("title", "untitled")
    logger.info("Loop starting — %r, %d paths, %d bytes, max_iterations=%d, has_postman=%s",
                spec_title, path_count, len(oas_json), max_iterations, has_postman)

    original_validation = _validate_spec(original_spec, "original spec")

    state: dict = {
        "current_spec":       current_spec,
        "postman_json":       postman_json,
        "has_postman":        has_postman,
        "review_suggestions": [],
        "last_changes":       [],
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
        async for _hb in _await_with_heartbeat(_run_reviewer(state, instructions, iteration)):
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

        async for _hb in _await_with_heartbeat(_run_enhancer(state, iteration)):
            if _hb.get("type") == "heartbeat":
                yield _hb
            else:
                result = _hb

        state["current_spec"] = result["enhanced_spec"]
        state["last_changes"] = result["changes_made"]

        all_iterations.append({
            "iteration":      iteration,
            "review_summary": review["summary"],
            "suggestions":    review["suggestions"],
            "changes_made":   result["changes_made"],
        })
        yield {"type": "enhance_complete", "iteration": iteration,
               "data": {"changes_made": result["changes_made"]}}

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

    def _to_yaml(spec: dict) -> str:
        return yaml.dump(spec, allow_unicode=True, sort_keys=False, default_flow_style=False)

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
