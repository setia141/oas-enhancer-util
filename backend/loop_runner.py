"""
Two-phase suggestion engine.

Phase 1 — spec_walker: deterministic tree walk, finds all gaps (no LLM).
Phase 2 — LLM: gaps split into batches; each batch gets only its relevant
           spec sections as context. Batches run concurrently.

Postman analysis runs as a separate single LLM call (needs the full spec).
"""
import asyncio
import json
import logging
import os
import time
from typing import AsyncGenerator

import httpx
import yaml

from .agents.prompts import SUGGESTER_INSTRUCTION, WALK_RULES
from .agents.tools import SUGGESTER_TOOLS
from .spec_walker import walk, Gap

logger = logging.getLogger(__name__)

# ── File loggers ─────────────────────────────────────────────────────────────
import os as _os
_LOG_DIR = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "logs")
_os.makedirs(_LOG_DIR, exist_ok=True)

_llm_logger = logging.getLogger("llm_calls")
_llm_logger.setLevel(logging.DEBUG)
_llm_logger.propagate = False
_llm_handler = logging.FileHandler(_os.path.join(_LOG_DIR, "llm_calls.log"), encoding="utf-8")
_llm_handler.setFormatter(logging.Formatter("%(asctime)s\n%(message)s\n"))
_llm_logger.addHandler(_llm_handler)

SUGGESTER_TIMEOUT  = 300
HEARTBEAT_INTERVAL = 5
SUGGESTER_MODEL    = "gpt-4.1-mini"
BATCH_SIZE         = 100   # gaps per LLM call
MAX_CONCURRENT     = 5     # parallel LLM calls at a time
BATCH_TOKENS       = 32768

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


async def _chat(payload: dict) -> str:
    payload = {**payload, "stream": True}
    _llm_logger.debug("REQUEST\n%s", json.dumps(payload, indent=2, default=str))
    async with asyncio.timeout(SUGGESTER_TIMEOUT):
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


# ── Spec context — only sections relevant to this batch ─────────────────────

def _spec_context(spec: dict, gaps: list[Gap]) -> str:
    sections: dict[str, str] = {}
    for g in gaps:
        if g.method == "info":
            if "info" not in sections:
                sections["info"] = f"info:\n{_to_yaml(spec.get('info', {}))}"
        elif g.method == "component":
            schema_name = g.location.split(".")[1] if g.location.count(".") >= 1 else ""
            key = f"component:{schema_name}"
            if key not in sections and schema_name:
                schema = spec.get("components", {}).get("schemas", {}).get(schema_name, {})
                sections[key] = f"components/schemas/{schema_name}:\n{_to_yaml(schema)}"
        else:
            key = f"{g.method}:{g.path}"
            if key not in sections:
                op = spec.get("paths", {}).get(g.path, {}).get(g.method, {})
                sections[key] = f"{g.method.upper()} {g.path}:\n{_to_yaml(op)}"
    return "\n---\n".join(sections.values())


# ── Gap list formatter ───────────────────────────────────────────────────────

def _format_gaps(gaps: list[Gap]) -> str:
    lines = ["## Gaps to fill", ""]
    current_key = None
    for i, g in enumerate(gaps, 1):
        if g.method == "component":
            op_key = f"Component {g.location.split('.')[1]}" if "." in g.location else "Component"
        elif g.method == "info":
            op_key = "INFO (spec level)"
        else:
            op_key = f"{g.method.upper()} {g.path}"
        if op_key != current_key:
            lines.append(f"### {op_key}")
            current_key = op_key
        lines.append(f"{i}. location: `{g.location}` | field: `{g.field}`")
    lines += [
        "",
        f"Total: {len(gaps)} gaps.",
        "IMPORTANT: Submit ONLY the gaps listed above. Do NOT add suggestions for any other location.",
    ]
    return "\n".join(lines)


# ── Single batch call ────────────────────────────────────────────────────────

async def _run_batch(batch: list[Gap], spec: dict, num: int, total: int, sem: asyncio.Semaphore) -> list[dict]:
    async with sem:
        user_content = f"Relevant spec sections:\n{_spec_context(spec, batch)}\n\n{_format_gaps(batch)}"
        logger.info("Batch %d/%d — %d gaps", num, total, len(batch))
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
                "max_tokens":  BATCH_TOKENS,
            })
            elapsed = time.monotonic() - t0
            if not tool_args:
                logger.warning("Batch %d/%d — no tool call (%.1fs)", num, total, elapsed)
                return []
            suggestions = json.loads(tool_args).get("suggestions", [])
            logger.info("Batch %d/%d done in %.1fs — %d suggestion(s)", num, total, elapsed, len(suggestions))
            return suggestions
        except json.JSONDecodeError:
            logger.error("Batch %d/%d — output truncated or malformed", num, total)
        except TimeoutError:
            logger.error("Batch %d/%d — timed out", num, total)
        except Exception as e:
            logger.error("Batch %d/%d — error: %s", num, total, e, exc_info=True)
        return []


# ── Postman analysis (needs full spec — separate call) ───────────────────────

async def _run_postman(spec: dict, postman_text: str) -> list[dict]:
    user_content = (
        f"OAS Spec (YAML):\n{_to_yaml(spec)}\n\n"
        f"Postman Collection — apply Postman rules only, find schema_property gaps:\n{postman_text}"
    )
    logger.info("Postman analysis — sending full spec")
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
            "max_tokens":  8192,
        })
        elapsed = time.monotonic() - t0
        if not tool_args:
            logger.warning("Postman analysis — no tool call (%.1fs)", elapsed)
            return []
        suggestions = json.loads(tool_args).get("suggestions", [])
        logger.info("Postman analysis done in %.1fs — %d suggestion(s)", elapsed, len(suggestions))
        return suggestions
    except Exception as e:
        logger.error("Postman analysis error: %s", e, exc_info=True)
        return []


# ── Main orchestrator ────────────────────────────────────────────────────────

async def _run_suggester(oas_spec: dict, postman_text: str | None, has_postman: bool) -> list[dict]:
    gaps = walk(oas_spec, WALK_RULES)

    if not gaps and not has_postman:
        logger.info("Walker found no gaps and no Postman collection — spec is complete")
        return []

    all_suggestions: list[dict] = []

    if gaps:
        _gaps_log = _os.path.join(_LOG_DIR, "gaps.log")
        with open(_gaps_log, "w", encoding="utf-8") as f:
            f.write(f"=== GAPS ({len(gaps)}) ===\n")
            for i, g in enumerate(gaps, 1):
                label = f"{g.method.upper()} {g.path}" if g.path else g.method.upper()
                f.write(f"{i:4}. {label} → {g.location} ({g.field})\n")

        batches = [gaps[i:i + BATCH_SIZE] for i in range(0, len(gaps), BATCH_SIZE)]
        sem     = asyncio.Semaphore(MAX_CONCURRENT)
        logger.info("%d gap(s) → %d batch(es), max %d concurrent", len(gaps), len(batches), MAX_CONCURRENT)

        results = await asyncio.gather(*[
            _run_batch(b, oas_spec, i + 1, len(batches), sem)
            for i, b in enumerate(batches)
        ])
        for r in results:
            all_suggestions.extend(r)
        logger.info("All batches done — %d suggestion(s) total", len(all_suggestions))

    if has_postman and postman_text:
        all_suggestions.extend(await _run_postman(oas_spec, postman_text))

    return all_suggestions


async def _await_with_heartbeat(coro, label: str = ""):
    task = asyncio.create_task(coro)
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

    if not oas_spec.get("paths"):
        yield {"type": "error", "message": "The uploaded spec has no paths."}
        return

    yield {"type": "start"}

    suggestions = None
    async for item in _await_with_heartbeat(_run_suggester(oas_spec, postman_text, has_postman), "suggester"):
        if isinstance(item, dict) and item.get("type") == "heartbeat":
            yield item
        else:
            suggestions = item

    if not suggestions:
        yield {"type": "error", "message": "No gaps found — the spec appears complete."}
        return

    yield {"type": "done", "suggestions": suggestions, "spec": oas_spec, "original_yaml": _to_yaml(oas_spec)}
