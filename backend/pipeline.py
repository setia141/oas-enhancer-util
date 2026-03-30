"""
Two-phase suggestion engine.

Phase 1 — spec_walker: deterministic tree walk, finds all gaps (no LLM).
Phase 2 — LLM: gaps split into batches; each batch gets only its relevant
           spec sections as context. Batches run concurrently.

Postman analysis runs as a separate single LLM call (needs the full spec).
The raw collection is pre-parsed by postman_parser.py into a clean per-endpoint
summary before being sent to the LLM — scripts, auth, and env variables stripped.

Results are cached in .cache/ keyed on spec + postman content + prompts hash.
Cache is automatically invalidated when prompts.py changes.
"""
import asyncio
import hashlib
import json
import logging
import os
import random
import time
from typing import AsyncGenerator

import httpx
import yaml

from .agents.prompts import SUGGESTER_INSTRUCTION, WALK_RULES
from .agents.tools import SUGGESTER_TOOLS
from .postman_parser import parse as parse_postman, format_for_llm as format_postman
from .spec_walker import walk, Gap

logger = logging.getLogger(__name__)

# ── Directories ───────────────────────────────────────────────────────────────
_BASE_DIR  = os.path.dirname(os.path.dirname(__file__))
_LOG_DIR   = os.path.join(_BASE_DIR, "logs")
_CACHE_DIR = os.path.join(_BASE_DIR, ".cache")
os.makedirs(_LOG_DIR,   exist_ok=True)
os.makedirs(_CACHE_DIR, exist_ok=True)

# ── File logger for LLM calls ─────────────────────────────────────────────────
_llm_logger = logging.getLogger("llm_calls")
_llm_logger.setLevel(logging.DEBUG)
_llm_logger.propagate = False
_llm_handler = logging.FileHandler(os.path.join(_LOG_DIR, "llm_calls.log"), encoding="utf-8")
_llm_handler.setFormatter(logging.Formatter("%(asctime)s\n%(message)s\n"))
_llm_logger.addHandler(_llm_handler)

# ── Prompts hash — used as part of cache key so rule changes bust the cache ───
_PROMPTS_FILE = os.path.join(os.path.dirname(__file__), "agents", "prompts.py")
with open(_PROMPTS_FILE, "rb") as _f:
    _PROMPTS_HASH = hashlib.sha256(_f.read()).hexdigest()[:12]

SUGGESTER_TIMEOUT  = 300
HEARTBEAT_INTERVAL = 5
MAX_CONCURRENT     = 3

# Retry on transient gateway errors (503, 429, 502, 504).
# Permanent errors (400, 401, 422) are not retried.
_RETRYABLE_STATUS  = {429, 502, 503, 504}
MAX_RETRIES        = int(os.environ.get("MAX_RETRIES",   "3"))
RETRY_BASE_DELAY   = float(os.environ.get("RETRY_BASE_DELAY", "2.0"))   # seconds

# All tunables are overridable via .env — see backend/.env.example
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL",  "https://api.openai.com/v1")
OPENAI_API_KEY  = os.environ.get("OPENAI_API_KEY",   "")
SUGGESTER_MODEL  = os.environ.get("SUGGESTER_MODEL",   "gpt-4.1-mini")
BATCH_TOKENS     = int(os.environ.get("BATCH_TOKENS",  "32768"))
BATCH_SIZE       = int(os.environ.get("BATCH_SIZE",    "50"))
POSTMAN_TOKENS      = int(os.environ.get("POSTMAN_TOKENS",      "32768"))
POSTMAN_BATCH_SIZE  = int(os.environ.get("POSTMAN_BATCH_SIZE",  "2"))

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


# ── Cache ─────────────────────────────────────────────────────────────────────

def _cache_key(spec: dict, postman_text: str | None) -> str:
    h = hashlib.sha256()
    h.update(_PROMPTS_HASH.encode())
    # Canonical YAML (sort_keys=True) so JSON vs YAML upload gives same key
    h.update(yaml.dump(spec, sort_keys=True, allow_unicode=True).encode())
    if postman_text:
        h.update(postman_text.encode())
    return h.hexdigest()


def _load_cache(key: str) -> list[dict] | None:
    path = os.path.join(_CACHE_DIR, f"{key}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    logger.info(
        "Cache hit — %d suggestion(s) cached at %s | file: %s | to invalidate: DELETE %s",
        len(data["suggestions"]), data["cached_at"], os.path.basename(path), path,
    )
    return data["suggestions"]


def _save_cache(key: str, suggestions: list[dict]) -> None:
    path = os.path.join(_CACHE_DIR, f"{key}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"suggestions": suggestions, "cached_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")}, f, default=str)
    logger.info("Cache saved — %s", os.path.basename(path))


# ── LLM ───────────────────────────────────────────────────────────────────────

async def _chat(payload: dict) -> str:
    """Single HTTP attempt — no retry logic here. Callers handle retries outside the semaphore."""
    payload = {**payload, "stream": True}
    _llm_logger.debug("REQUEST\n%s", json.dumps(payload, indent=2, default=str))
    async with asyncio.timeout(SUGGESTER_TIMEOUT):
        async with _client.stream("POST", "/chat/completions", json=payload) as resp:
            if resp.status_code in _RETRYABLE_STATUS:
                raise httpx.HTTPStatusError(
                    f"Retryable {resp.status_code}", request=resp.request, response=resp,
                )
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


def _retry_delay(attempt: int) -> float:
    """Exponential backoff with jitter: 2s, 4s, 8s, ... + up to 1s jitter."""
    return RETRY_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 1)


# ── Spec context — only sections relevant to this batch ──────────────────────

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


# ── Gap list formatter ────────────────────────────────────────────────────────

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
        "Every suggestion MUST include path, method, location, field, and value — no field may be omitted.",
        "For component gaps: method='component', path='', location=exactly as shown above (e.g. schemas.User.properties.email.description).",
    ]
    return "\n".join(lines)


# ── Single batch call ─────────────────────────────────────────────────────────

async def _run_batch(batch: list[Gap], spec: dict, num: int, total: int, sem: asyncio.Semaphore) -> list[dict]:
    user_content = f"Relevant spec sections:\n{_spec_context(spec, batch)}\n\n{_format_gaps(batch)}"
    payload = {
        "model":       SUGGESTER_MODEL,
        "messages":    [
            {"role": "system", "content": SUGGESTER_INSTRUCTION},
            {"role": "user",   "content": user_content},
        ],
        "tools":       SUGGESTER_TOOLS,
        "tool_choice": {"type": "function", "function": {"name": "submit_suggestions"}},
        "max_tokens":  BATCH_TOKENS,
    }

    for attempt in range(1, MAX_RETRIES + 1):
        async with sem:                    # semaphore acquired per attempt — released before sleep
            logger.info("Batch %d/%d — %d gaps, max_tokens=%d%s",
                        num, total, len(batch), BATCH_TOKENS,
                        f" (retry {attempt}/{MAX_RETRIES})" if attempt > 1 else "")
            t0 = time.monotonic()
            try:
                tool_args = await _chat(payload)
                elapsed = time.monotonic() - t0

                if not tool_args:
                    logger.warning("Batch %d/%d — no tool call returned (%.1fs)", num, total, elapsed)
                    return []

                suggestions = json.loads(tool_args).get("suggestions", [])
                logger.info("Batch %d/%d done in %.1fs — %d/%d gaps filled", num, total, elapsed, len(suggestions), len(batch))

                if len(suggestions) < len(batch):
                    logger.warning(
                        "Batch %d/%d — got %d suggestions for %d gaps — possible output truncation. "
                        "Consider reducing BATCH_SIZE (currently %d) or increasing BATCH_TOKENS (currently %d).",
                        num, total, len(suggestions), len(batch), BATCH_SIZE, BATCH_TOKENS,
                    )
                return suggestions

            except httpx.HTTPStatusError as e:
                if e.response.status_code not in _RETRYABLE_STATUS or attempt == MAX_RETRIES:
                    logger.error("Batch %d/%d — HTTP %d (not retrying)", num, total, e.response.status_code)
                    return []
                delay = _retry_delay(attempt)
                logger.warning("Batch %d/%d — HTTP %d, retry %d/%d in %.1fs",
                               num, total, e.response.status_code, attempt, MAX_RETRIES, delay)
            except json.JSONDecodeError:
                logger.error("Batch %d/%d — JSON decode failed (max_tokens=%d). Reduce BATCH_SIZE or increase BATCH_TOKENS.",
                             num, total, BATCH_TOKENS)
                return []
            except TimeoutError:
                logger.error("Batch %d/%d — timed out after %ds", num, total, SUGGESTER_TIMEOUT)
                return []
            except Exception as e:
                logger.error("Batch %d/%d — error: %s", num, total, e, exc_info=True)
                return []
        # semaphore released — sleep without holding it
        await asyncio.sleep(delay)

    return []


# ── Postman analysis — one batch per N endpoints, run concurrently ────────────

async def _run_postman_batch(
    batch: list,
    spec_yaml: str,
    num: int,
    total: int,
    sem: asyncio.Semaphore,
) -> list[dict]:
    user_content = (
        f"OAS Spec (YAML):\n{spec_yaml}\n\n"
        f"{format_postman(batch)}\n\n"
        f"Apply Postman rules only — find schema_property gaps."
    )
    payload = {
        "model":       SUGGESTER_MODEL,
        "messages":    [
            {"role": "system", "content": SUGGESTER_INSTRUCTION},
            {"role": "user",   "content": user_content},
        ],
        "tools":       SUGGESTER_TOOLS,
        "tool_choice": {"type": "function", "function": {"name": "submit_suggestions"}},
        "max_tokens":  POSTMAN_TOKENS,
    }

    for attempt in range(1, MAX_RETRIES + 1):
        async with sem:                    # semaphore acquired per attempt — released before sleep
            logger.info("Postman batch %d/%d — %d endpoint(s)%s",
                        num, total, len(batch),
                        f" (retry {attempt}/{MAX_RETRIES})" if attempt > 1 else "")
            t0 = time.monotonic()
            try:
                tool_args = await _chat(payload)
                elapsed = time.monotonic() - t0
                if not tool_args:
                    logger.warning("Postman batch %d/%d — no tool call (%.1fs)", num, total, elapsed)
                    return []
                suggestions = json.loads(tool_args).get("suggestions", [])
                logger.info("Postman batch %d/%d done in %.1fs — %d suggestion(s)", num, total, elapsed, len(suggestions))
                return suggestions

            except httpx.HTTPStatusError as e:
                if e.response.status_code not in _RETRYABLE_STATUS or attempt == MAX_RETRIES:
                    logger.error("Postman batch %d/%d — HTTP %d (not retrying)", num, total, e.response.status_code)
                    return []
                delay = _retry_delay(attempt)
                logger.warning("Postman batch %d/%d — HTTP %d, retry %d/%d in %.1fs",
                               num, total, e.response.status_code, attempt, MAX_RETRIES, delay)
            except Exception as e:
                logger.error("Postman batch %d/%d error: %s", num, total, e, exc_info=True)
                return []
        # semaphore released — sleep without holding it
        await asyncio.sleep(delay)

    return []


async def _run_postman(spec: dict, postman_text: str) -> list[dict]:
    spec_paths = list(spec.get("paths", {}).keys())
    endpoints = parse_postman(postman_text, spec_paths)
    if not endpoints:
        logger.warning("Postman parser extracted 0 endpoints — skipping Postman analysis")
        return []
    logger.info(
        "Postman parser — %d endpoint(s) extracted, batch_size=%d",
        len(endpoints), POSTMAN_BATCH_SIZE,
    )

    spec_yaml = _to_yaml(spec)
    batches   = [endpoints[i:i + POSTMAN_BATCH_SIZE] for i in range(0, len(endpoints), POSTMAN_BATCH_SIZE)]
    sem       = asyncio.Semaphore(MAX_CONCURRENT)
    logger.info("Postman — %d endpoint(s) → %d batch(es), max %d concurrent", len(endpoints), len(batches), MAX_CONCURRENT)

    results = await asyncio.gather(*[
        _run_postman_batch(b, spec_yaml, i + 1, len(batches), sem)
        for i, b in enumerate(batches)
    ])

    all_suggestions: list[dict] = []
    for r in results:
        all_suggestions.extend(r)
    logger.info("Postman analysis done — %d suggestion(s) total", len(all_suggestions))
    return all_suggestions


# ── Main orchestrator ─────────────────────────────────────────────────────────

async def _run_suggester(oas_spec: dict, postman_text: str | None, has_postman: bool) -> list[dict]:
    gaps = walk(oas_spec, WALK_RULES)

    if not gaps and not has_postman:
        logger.info("Walker found no gaps and no Postman collection — spec is complete")
        return []

    all_suggestions: list[dict] = []

    if gaps:
        with open(os.path.join(_LOG_DIR, "gaps.log"), "w", encoding="utf-8") as f:
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


# ── Public entry point ────────────────────────────────────────────────────────

async def get_suggestions(
    oas_spec:      dict,
    postman_text:  str | None,
    has_postman:   bool,
    force_refresh: bool = False,
) -> AsyncGenerator[dict, None]:
    if not _client:
        raise RuntimeError("HTTP client not initialised — call init_client() first")

    if not oas_spec.get("paths"):
        yield {"type": "error", "message": "The uploaded spec has no paths."}
        return

    yield {"type": "start"}

    # Cache check
    key = _cache_key(oas_spec, postman_text if has_postman else None)
    if force_refresh:
        path = os.path.join(_CACHE_DIR, f"{key}.json")
        if os.path.exists(path):
            os.remove(path)
            logger.info("Cache invalidated — %s", os.path.basename(path))
    else:
        cached = _load_cache(key)
        if cached is not None:
            yield {"type": "done", "suggestions": cached, "spec": oas_spec, "original_yaml": _to_yaml(oas_spec), "from_cache": True}
            return

    suggestions = None
    async for item in _await_with_heartbeat(_run_suggester(oas_spec, postman_text, has_postman), "suggester"):
        if isinstance(item, dict) and item.get("type") == "heartbeat":
            yield item
        else:
            suggestions = item

    if not suggestions:
        yield {"type": "error", "message": "No gaps found — the spec appears complete."}
        return

    _save_cache(key, suggestions)
    yield {"type": "done", "suggestions": suggestions, "spec": oas_spec, "original_yaml": _to_yaml(oas_spec)}


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
