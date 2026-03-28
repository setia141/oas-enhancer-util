"""
Two-phase suggestion engine.

Phase 1 — spec_walker: deterministic tree walk, finds all gaps (no LLM).
Phase 2 — LLM: generates values only for the gaps found by the walker.

Postman analysis (schema_property gaps) is appended as a separate task
to the same LLM call when a Postman collection is provided.
"""
import asyncio
import json
import logging
import os
import time
from typing import AsyncGenerator

import httpx
import yaml

from .agents.prompts import SUGGESTER_INSTRUCTION, WALK_RULES, POSTMAN_RULES
from .agents.tools import SUGGESTER_TOOLS
from .spec_walker import walk, Gap

logger = logging.getLogger(__name__)

# ── LLM call logger ────────────────────────────────────────────────────────────
_llm_logger = logging.getLogger("llm_calls")
_llm_logger.setLevel(logging.DEBUG)
_llm_logger.propagate = False
_llm_log_handler = logging.FileHandler("llm_calls.log", encoding="utf-8")
_llm_log_handler.setFormatter(logging.Formatter("%(asctime)s\n%(message)s\n"))
_llm_logger.addHandler(_llm_log_handler)

SUGGESTER_TIMEOUT  = 300
HEARTBEAT_INTERVAL = 5
SUGGESTER_MODEL    = "gpt-4.1-mini"

OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_API_KEY  = os.environ.get("OPENAI_API_KEY", "")

_client: httpx.AsyncClient | None = None


def _to_yaml(spec: dict) -> str:
    return yaml.dump(spec, allow_unicode=True, sort_keys=False, default_flow_style=False)


def init_client() -> None:
    global _client
    _client = httpx.AsyncClient(
        base_url=OPENAI_BASE_URL,
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        http2=False,
        timeout=httpx.Timeout(SUGGESTER_TIMEOUT + 30, connect=10.0),
    )
    logger.info("HTTP client ready — base=%s, model=%s", OPENAI_BASE_URL, SUGGESTER_MODEL)


async def _chat(payload: dict, timeout: int) -> str:
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


def _format_gaps_for_prompt(gaps: list[Gap]) -> str:
    """
    Format the gap list as a numbered section for the LLM prompt.
    Gaps are grouped by operation so the LLM sees them in context.
    """
    if not gaps:
        return ""

    lines = ["## Gaps to fill", ""]
    current_key = None
    gap_num = 0

    for g in gaps:
        op_key = f"{g.method.upper()} {g.path}" if g.method != "component" else f"Component {g.location.split('.')[1] if '.' in g.location else g.location}"
        if op_key != current_key:
            lines.append(f"### {op_key}")
            current_key = op_key

        gap_num += 1
        update_note = " [UPDATE — current value is poor quality]" if g.is_update else ""
        lines.append(f"{gap_num}. location: `{g.location}` | field: `{g.field}`{update_note}")

    lines.append("")
    lines.append(f"Total: {gap_num} gaps. You MUST include all {gap_num} in submit_suggestions.")
    return "\n".join(lines)


async def _run_suggester(
    oas_spec:     dict,
    postman_text: str | None,
    has_postman:  bool,
) -> list[dict]:
    # ── Phase 1: deterministic walker ────────────────────────────────────────
    gaps = walk(oas_spec, WALK_RULES)

    if not gaps and not has_postman:
        logger.info("Walker found no gaps and no Postman collection — spec is complete")
        return []

    # ── Phase 2: LLM generates values ────────────────────────────────────────
    spec_yaml   = _to_yaml(oas_spec)
    gaps_prompt = _format_gaps_for_prompt(gaps)

    user_content = f"OAS Spec (YAML):\n{spec_yaml}"
    if gaps_prompt:
        user_content += f"\n\n{gaps_prompt}"
    if has_postman and postman_text:
        user_content += f"\n\nPostman Collection (find schema_property gaps only):\n{postman_text}"

    logger.info(
        "Sending %d gaps to LLM%s",
        len(gaps),
        " + Postman analysis" if has_postman else "",
    )

    t0 = time.monotonic()
    try:
        tool_args = await _chat({
            "model":       SUGGESTER_MODEL,
            "messages":    [
                {"role": "system", "content": SUGGESTER_INSTRUCTION},
                {"role": "user",   "content": user_content},
            ],
            "tools":       SUGGESTER_TOOLS,
            "tool_choice": {"type": "function", "function": {"name": "submit_suggestions"}},
            "max_tokens":  16384,
        }, SUGGESTER_TIMEOUT)

        elapsed = time.monotonic() - t0
        if not tool_args:
            logger.warning("LLM returned no tool call (%.1fs)", elapsed)
            return []

        try:
            args = json.loads(tool_args)
        except json.JSONDecodeError:
            logger.error("LLM output truncated or malformed")
            return []

        suggestions = args.get("suggestions", [])
        logger.info("LLM done in %.1fs — %d suggestion(s)", elapsed, len(suggestions))
        return suggestions

    except TimeoutError:
        logger.error("LLM timed out after %ds", SUGGESTER_TIMEOUT)
    except Exception as e:
        logger.error("LLM error: %s", e, exc_info=True)

    return []


async def _await_with_heartbeat(coro, label: str = ""):
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


async def get_suggestions(
    oas_spec:     dict,
    postman_text: str | None,
    has_postman:  bool,
) -> AsyncGenerator[dict, None]:
    if not _client:
        raise RuntimeError("HTTP client not initialised — call init_client() first")

    path_count = len(oas_spec.get("paths", {}))
    if path_count == 0:
        yield {"type": "error", "message": "The uploaded spec has no paths."}
        return

    yield {"type": "start"}

    suggestions = None
    async for _hb in _await_with_heartbeat(
        _run_suggester(oas_spec, postman_text, has_postman),
        "suggester"
    ):
        if isinstance(_hb, dict) and _hb.get("type") == "heartbeat":
            yield _hb
        else:
            suggestions = _hb

    if suggestions is None or (not suggestions and not has_postman):
        yield {"type": "error", "message": "No gaps found — the spec appears complete."}
        return

    yield {"type": "done", "suggestions": suggestions, "spec": oas_spec, "original_yaml": _to_yaml(oas_spec)}
