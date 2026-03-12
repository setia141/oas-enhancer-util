"""
Orchestrates the review → enhance loop (max 5 iterations) using the OpenAI API directly.
Yields SSE-ready dicts for streaming to the frontend.
"""
import asyncio
import json
import logging
from typing import AsyncGenerator

import yaml
from openai import AsyncOpenAI
from openapi_spec_validator import validate as _oas_validate

from .agents.prompts import REVIEWER_INSTRUCTION, ENHANCER_INSTRUCTION
from .agents.tools import REVIEWER_TOOLS, ENHANCER_TOOLS, get_breaking_changes_policy

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5
AGENT_TIMEOUT  = 120        # seconds per agent call
REVIEWER_MODEL = "gpt-4.1-mini"
ENHANCER_MODEL = "gpt-4.1"

_OAS_TOP_LEVEL      = {"openapi", "info", "servers", "paths", "components", "security", "tags", "externalDocs"}
_HTTP_METHODS       = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
_SWAGGER2_OP_FIELDS = {"produces", "consumes"}   # Swagger 2.0 fields invalid in OAS 3.x

_client: AsyncOpenAI | None = None


# ── Spec post-processing ───────────────────────────────────────────────────────

def _sanitize_spec(spec: dict) -> dict:
    """Fix model-injected structural mistakes before saving the enhanced spec."""
    # Rescue path items the model placed at the top level instead of inside paths
    for k in [k for k in list(spec.keys()) if k.startswith("/")]:
        logger.warning("Moving misplaced path from top-level into paths: %s", k)
        spec.setdefault("paths", {})[k] = spec.pop(k)

    # Remove non-OAS top-level keys (e.g. changes_made accidentally embedded in spec)
    for k in [k for k in list(spec.keys()) if k not in _OAS_TOP_LEVEL and not k.startswith("x-")]:
        logger.warning("Stripping non-OAS top-level key: %s", k)
        del spec[k]

    # Remove non-path entries from paths dict
    if isinstance(spec.get("paths"), dict):
        for k in [k for k in list(spec["paths"].keys()) if not k.startswith("/")]:
            logger.warning("Stripping non-path key from paths dict: %s", k)
            del spec["paths"][k]

    # Strip Swagger 2.0 operation fields that are invalid in OAS 3.x
    if str(spec.get("openapi", "")).startswith("3."):
        for path_item in spec.get("paths", {}).values():
            if not isinstance(path_item, dict):
                continue
            for method, operation in path_item.items():
                if method not in _HTTP_METHODS or not isinstance(operation, dict):
                    continue
                for field in _SWAGGER2_OP_FIELDS & operation.keys():
                    logger.warning("Stripping Swagger 2.0 field '%s' from %s operation", field, method)
                    del operation[field]

    return spec


def _restore_dropped_content(original: dict, enhanced: dict) -> dict:
    """Back-fill any paths/operations the model dropped. Enhanced content takes priority."""
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


def _fix_duplicate_operation_ids(spec: dict) -> dict:
    """Rename any duplicate operationIds by appending _2, _3, … to disambiguate."""
    seen: dict[str, int] = {}
    for path_item in spec.get("paths", {}).values():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            op_id = operation.get("operationId")
            if not op_id:
                continue
            if op_id in seen:
                seen[op_id] += 1
                new_id = f"{op_id}_{seen[op_id]}"
                logger.warning("Duplicate operationId '%s' → renamed to '%s'", op_id, new_id)
                operation["operationId"] = new_id
            else:
                seen[op_id] = 1
    return spec


def _validate_spec(spec: dict, label: str) -> list[str]:
    """Validate spec against its declared OAS/Swagger version. Returns list of error strings (empty = valid)."""
    try:
        _oas_validate(spec)
        logger.info("%s passed OAS validation", label)
        return []
    except Exception as exc:
        errors = str(exc).splitlines()
        logger.warning("%s has %d OAS validation error(s):", label, len(errors))
        for e in errors[:10]:
            logger.warning("  %s", e)
        return errors


# ── OpenAI client ──────────────────────────────────────────────────────────────

def init_client() -> None:
    global _client
    _client = AsyncOpenAI()
    logger.info("OpenAI client initialised (reviewer=%s, enhancer=%s).", REVIEWER_MODEL, ENHANCER_MODEL)


# ── Agent calls ────────────────────────────────────────────────────────────────

async def _run_reviewer(state: dict, instructions: str, iteration: int) -> dict:
    spec_json = json.dumps(state["current_spec"], indent=2)
    logger.info("Iteration %d — reviewer sees spec of %d bytes", iteration, len(spec_json))

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
            timeout=AGENT_TIMEOUT,
        )
        choice = response.choices[0]
        if not choice.message.tool_calls:
            logger.warning("Iteration %d — reviewer returned no tool call (finish_reason=%s)", iteration, choice.finish_reason)
            return {"satisfied": False, "summary": "", "suggestions": []}

        args        = json.loads(choice.message.tool_calls[0].function.arguments)
        suggestions = args.get("suggestions", [])
        logger.info("Iteration %d — reviewer: satisfied=%s, suggestions=%d", iteration, args.get("satisfied"), len(suggestions))
        for i, s in enumerate(suggestions, 1):
            logger.info("Iteration %d — suggestion %d: %s", iteration, i, s)
        return {
            "satisfied":   bool(args.get("satisfied", False)),
            "summary":     args.get("summary", ""),
            "suggestions": suggestions,
        }
    except asyncio.TimeoutError:
        logger.warning("Iteration %d — reviewer timed out after %ds", iteration, AGENT_TIMEOUT)
    except Exception as e:
        logger.error("Iteration %d — reviewer error: %s", iteration, e)

    return {"satisfied": False, "summary": "", "suggestions": []}


async def _run_enhancer(state: dict, iteration: int) -> dict:
    spec_json   = json.dumps(state["current_spec"], indent=2)
    suggestions = state.get("review_suggestions", [])
    path_count  = len(state["current_spec"].get("paths", {}))

    user_content = (
        f"CRITICAL — BREAKING CHANGES POLICY (obey strictly): {get_breaking_changes_policy(state)}\n\n"
        f"Iteration {iteration}: Apply ALL suggestions to the OAS spec below.\n\n"
        f"IMPORTANT: The input spec has {path_count} paths. Your output MUST contain all {path_count} paths.\n\n"
        f"Suggestions:\n{json.dumps(suggestions, indent=2)}\n\n"
        f"Current OAS Spec:\n{spec_json}"
    )
    if state.get("postman_json"):
        user_content += f"\n\nPostman Collection:\n{state['postman_json']}"

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
            timeout=AGENT_TIMEOUT,
        )
        choice = response.choices[0]
        if not choice.message.tool_calls:
            logger.warning("Iteration %d — enhancer returned no tool call (finish_reason=%s)", iteration, choice.finish_reason)
            return {"enhanced_spec": state["current_spec"], "changes_made": [], "validation_errors": []}

        args     = json.loads(choice.message.tool_calls[0].function.arguments)
        enhanced = args.get("enhanced_spec", state["current_spec"])

        if isinstance(enhanced, str):
            try:
                enhanced = json.loads(enhanced)
            except Exception:
                logger.warning("Iteration %d — enhanced_spec was unparseable string; keeping original", iteration)
                enhanced = state["current_spec"]

        before_paths = len(state["current_spec"].get("paths", {}))
        enhanced     = _sanitize_spec(enhanced)
        enhanced     = _restore_dropped_content(state["current_spec"], enhanced)
        enhanced     = _fix_duplicate_operation_ids(enhanced)
        after_paths  = len(enhanced.get("paths", {}))
        changes      = args.get("changes_made", [])

        spec_changed      = json.dumps(enhanced, sort_keys=True) != json.dumps(state["current_spec"], sort_keys=True)
        validation_errors = _validate_spec(enhanced, f"Iteration {iteration}")
        logger.info("Iteration %d — enhancer: %d changes, spec_changed=%s, valid=%s, paths %d→%d",
                    iteration, len(changes), spec_changed, not validation_errors, before_paths, after_paths)
        if not spec_changed:
            logger.warning("Iteration %d — enhancer returned the original spec unchanged", iteration)

        return {"enhanced_spec": enhanced, "changes_made": changes, "validation_errors": validation_errors}

    except asyncio.TimeoutError:
        logger.warning("Iteration %d — enhancer timed out after %ds", iteration, AGENT_TIMEOUT)
    except Exception as e:
        logger.error("Iteration %d — enhancer error: %s", iteration, e)

    return {"enhanced_spec": state["current_spec"], "changes_made": [], "validation_errors": []}


# ── Main loop ──────────────────────────────────────────────────────────────────

async def run_enhancement_loop(
    oas_json:     str,
    postman_json: str | None,
    instructions: str,
    has_postman:  bool,
) -> AsyncGenerator[dict, None]:
    """
    Async generator yielding SSE event dicts:
      iteration_start  { iteration }
      review_complete  { iteration, data: {satisfied, summary, suggestions} }
      enhance_start    { iteration }
      enhance_complete { iteration, data: {changes_made} }
      done             { original_spec, original_spec_yaml, final_spec, final_spec_yaml, iterations, validation_errors, summary }
    """
    assert _client, "OpenAI client not initialised — call init_client() first"

    current_spec  = json.loads(oas_json) if isinstance(oas_json, str) else oas_json
    original_spec = json.loads(json.dumps(current_spec))  # deep copy

    original_validation = _validate_spec(original_spec, "Original spec")

    state: dict = {
        "current_spec":       current_spec,
        "postman_json":       postman_json,
        "has_postman":        has_postman,
        "review_suggestions": [],
        "review_satisfied":   False,
        "review_summary":     "",
        "last_changes":       [],
    }

    all_iterations:        list[dict] = []
    last_review:           dict       = {}
    prev_suggestion_count: int        = -1
    stalled_iterations:    int        = 0

    for i in range(MAX_ITERATIONS):
        iteration = i + 1
        yield {"type": "iteration_start", "iteration": iteration}

        # ── Reviewer ──────────────────────────────────────────────
        review = await _run_reviewer(state, instructions, iteration)
        state["review_satisfied"]   = review["satisfied"]
        state["review_summary"]     = review["summary"]
        state["review_suggestions"] = review["suggestions"]
        last_review = review

        yield {"type": "review_complete", "iteration": iteration, "data": review}

        suggestion_count = len(review["suggestions"])
        if prev_suggestion_count > 0 and suggestion_count >= prev_suggestion_count:
            stalled_iterations += 1
        else:
            stalled_iterations = 0
        prev_suggestion_count = suggestion_count

        if review["satisfied"] or not review["suggestions"]:
            logger.info("Iteration %d — stopping: reviewer satisfied", iteration)
            break
        if stalled_iterations >= 3:
            logger.info("Iteration %d — stopping: no improvement for 3 consecutive iterations", iteration)
            break

        # ── Enhancer ──────────────────────────────────────────────
        yield {"type": "enhance_start", "iteration": iteration}
        result = await _run_enhancer(state, iteration)
        state["current_spec"] = result["enhanced_spec"]
        state["last_changes"] = result["changes_made"]
        logger.info("Iteration %d — spec updated, next reviewer will see %d paths",
                    iteration, len(state["current_spec"].get("paths", {})))

        all_iterations.append({
            "iteration":      iteration,
            "review_summary": review["summary"],
            "suggestions":    review["suggestions"],
            "changes_made":   result["changes_made"],
        })
        yield {"type": "enhance_complete", "iteration": iteration, "data": {"changes_made": result["changes_made"]}}

    def _to_yaml(spec: dict) -> str:
        return yaml.dump(spec, allow_unicode=True, sort_keys=False, default_flow_style=False)

    # Skip re-validation when the enhancer never ran (spec is identical to original)
    final_validation = (
        _validate_spec(state["current_spec"], "Final spec")
        if all_iterations else original_validation
    )
    total_changes    = sum(len(it["changes_made"]) for it in all_iterations)

    yield {
        "type":               "done",
        "original_spec":      original_spec,
        "original_spec_yaml": _to_yaml(original_spec),
        "final_spec":         state["current_spec"],
        "final_spec_yaml":    _to_yaml(state["current_spec"]),
        "iterations":                all_iterations,
        "original_validation_errors": original_validation,
        "validation_errors":          final_validation,
        "summary": {
            "total_iterations":      len(all_iterations),
            "total_changes":         total_changes,
            "completed_by_reviewer": last_review.get("satisfied", False),
        },
    }
