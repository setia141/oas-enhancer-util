"""
Orchestrates the review → enhance loop (max 5 iterations) using Google ADK.

OAS content is passed through session state (not message text) to avoid ADK's
template variable substitution which breaks on path params like {id}.

Yields SSE-ready dicts for streaming to the frontend.
"""
import asyncio
import json
import logging
import uuid
from typing import AsyncGenerator

import yaml

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

from .agents.reviewer import reviewer_agent
from .agents.enhancer import enhancer_agent
from .agents.tools import (
    SPEC_KEY,
    POSTMAN_KEY,
    HAS_POSTMAN_KEY,
    SUGGESTIONS_KEY,
    SATISFIED_KEY,
    SUMMARY_KEY,
    CHANGES_KEY,
)

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5
APP_NAME = "oas_enhancer_app"
AGENT_TIMEOUT = 120  # seconds — max time to wait for a single agent run

_session_service: InMemorySessionService | None = None
_reviewer_runner: Runner | None = None
_enhancer_runner: Runner | None = None


def init_runners() -> None:
    """Initialise ADK session service and runners. Called once at server startup."""
    global _session_service, _reviewer_runner, _enhancer_runner

    _session_service = InMemorySessionService()

    _reviewer_runner = Runner(
        agent=reviewer_agent,
        app_name=APP_NAME,
        session_service=_session_service,
    )
    _enhancer_runner = Runner(
        agent=enhancer_agent,
        app_name=APP_NAME,
        session_service=_session_service,
    )
    logger.info("ADK runners initialised.")


async def _run_agent(runner: Runner, user_id: str, session_id: str, message: str) -> dict:
    """
    Drive an ADK agent to completion, with a timeout guard.

    Returns the accumulated state_delta from all events so the caller can read
    tool-written values without a separate get_session() call.
    """
    async def _inner() -> dict:
        content = Content(role="user", parts=[Part(text=message)])
        state_delta: dict = {}

        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=content,
        ):
            # Collect state changes written by tools during this run
            if event.actions and event.actions.state_delta:
                logger.debug("State delta keys: %s", list(event.actions.state_delta.keys()))
                state_delta.update(event.actions.state_delta)

            # Log tool calls so we can diagnose if agents aren't invoking tools
            calls = event.get_function_calls() if hasattr(event, "get_function_calls") else []
            for call in (calls or []):
                logger.info("Tool call: %s(%s)", call.name, list((call.args or {}).keys()))

            if event.is_final_response():
                text = ""
                if event.content and event.content.parts:
                    text = event.content.parts[0].text or ""
                logger.debug("Agent final response (first 200): %s", text[:200])

        return state_delta

    try:
        return await asyncio.wait_for(_inner(), timeout=AGENT_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("Agent run timed out after %ds — returning partial state", AGENT_TIMEOUT)
        return {}


async def run_enhancement_loop(
    oas_json: str,
    postman_json: str | None,
    instructions: str,
    has_postman: bool,
) -> AsyncGenerator[dict, None]:
    """
    Async generator yielding SSE event dicts.

    Flow per iteration:
      1. Reviewer reads spec from session state via tools → calls submit_review
      2. If satisfied or no suggestions → done
      3. Enhancer reads suggestions + spec via tools → calls save_enhanced_spec
      4. Session state now holds the updated spec for the next iteration

    Event types:
      iteration_start  { iteration }
      review_complete  { iteration, data: {satisfied, summary, suggestions} }
      enhance_complete { iteration, data: {changes_made} }
      done             { original_spec, original_spec_yaml, final_spec, final_spec_yaml, iterations, summary }
    """
    assert _session_service and _reviewer_runner and _enhancer_runner, \
        "Runners not initialised — call init_runners() first"

    current_spec = json.loads(oas_json) if isinstance(oas_json, str) else oas_json
    original_spec = json.loads(json.dumps(current_spec))  # deep copy

    # Each request gets its own isolated session
    user_id = str(uuid.uuid4())
    initial_state = {
        SPEC_KEY:        current_spec,
        POSTMAN_KEY:     postman_json,
        HAS_POSTMAN_KEY: has_postman,
    }

    session = await _session_service.create_session(
        app_name=APP_NAME,
        user_id=user_id,
        state=initial_state,
    )
    session_id = session.id
    logger.info("Session %s created (paths=%d, has_postman=%s)",
                session_id, len(current_spec.get("paths", {})), has_postman)

    all_iterations: list[dict] = []
    last_review: dict = {}

    # Running state overlay — merges session initial state with deltas from each run.
    # This is the authoritative view of session state for our Python code.
    live_state: dict = dict(initial_state)

    for i in range(MAX_ITERATIONS):
        iteration = i + 1
        yield {"type": "iteration_start", "iteration": iteration}

        # ── Reviewer ────────────────────────────────────────────────────
        logger.info("Iteration %d — running reviewer", iteration)
        reviewer_msg = (
            f"Iteration {iteration}: Review the OAS specification stored in session state. "
            "You MUST call submit_review to complete — do not write a text response."
        )
        if instructions:
            reviewer_msg += f" Additional instructions: {instructions}"

        delta = await _run_agent(_reviewer_runner, user_id, session_id, reviewer_msg)
        live_state.update(delta)

        review = {
            "satisfied":   live_state.get(SATISFIED_KEY, False),
            "summary":     live_state.get(SUMMARY_KEY, ""),
            "suggestions": live_state.get(SUGGESTIONS_KEY, []),
        }
        last_review = review
        logger.info("Iteration %d — reviewer: satisfied=%s, suggestions=%d, delta_keys=%s",
                    iteration, review["satisfied"], len(review["suggestions"]), list(delta.keys()))

        yield {"type": "review_complete", "iteration": iteration, "data": review}

        suggestions = review["suggestions"]
        if review["satisfied"] or not suggestions:
            logger.info("Iteration %d — stopping (satisfied=%s, suggestions=%d)",
                        iteration, review["satisfied"], len(suggestions))
            break

        # ── Enhancer ────────────────────────────────────────────────────
        logger.info("Iteration %d — running enhancer (%d suggestions)", iteration, len(suggestions))
        delta = await _run_agent(
            _enhancer_runner, user_id, session_id,
            f"Iteration {iteration}: Apply all review suggestions to the OAS spec in session state. "
            "You MUST call save_enhanced_spec to complete — do not write a text response.",
        )
        live_state.update(delta)

        current_spec = live_state.get(SPEC_KEY, current_spec)
        changes_made = live_state.get(CHANGES_KEY, [])

        logger.info("Iteration %d — enhancer done: %d changes, paths=%d, delta_keys=%s",
                    iteration, len(changes_made), len(current_spec.get("paths", {})), list(delta.keys()))

        all_iterations.append({
            "iteration":      iteration,
            "review_summary": review["summary"],
            "suggestions":    suggestions,
            "changes_made":   changes_made,
        })
        yield {"type": "enhance_complete", "iteration": iteration, "data": {"changes_made": changes_made}}

    def _to_yaml(spec: dict) -> str:
        return yaml.dump(spec, allow_unicode=True, sort_keys=False, default_flow_style=False)

    total_changes = sum(len(it["changes_made"]) for it in all_iterations)
    yield {
        "type":               "done",
        "original_spec":      original_spec,
        "original_spec_yaml": _to_yaml(original_spec),
        "final_spec":         current_spec,
        "final_spec_yaml":    _to_yaml(current_spec),
        "iterations":         all_iterations,
        "summary": {
            "total_iterations":      len(all_iterations),
            "total_changes":         total_changes,
            "completed_by_reviewer": last_review.get("satisfied", False),
        },
    }
