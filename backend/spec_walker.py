"""
Phase 1 — Deterministic OAS spec walker.

Walks the spec tree and returns a list of Gaps: locations where a required
field is absent (None, empty string, or not present in the dict at all).

Completeness checker only — answers "is the field there?"
Quality of existing content is not judged here; that is the LLM's job.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class WalkRules:
    description:        bool = True   # flag missing descriptions
    example:            bool = True   # flag missing examples
    x_ai:               bool = True   # flag missing x-ai object or sub-tags
    info_description:   bool = True   # flag missing spec-level info.description
    x_ai_required_tags: list = field(default_factory=lambda: [
        "when-to-use-me",
        "how-to-use-me",
        "trigger-me-command",
    ])


@dataclass
class Gap:
    path:     str   # API path e.g. /users/{id}. Empty for info/components.
    method:   str   # HTTP method lowercase, "component", or "info"
    location: str   # dot-notation within the root object
    field:    str   # "description" | "example" | "x-ai"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _missing(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _has_ref(obj) -> bool:
    return isinstance(obj, dict) and "$ref" in obj


def _gap(path, method, location, field_name) -> Gap:
    label = f"{method.upper()} {path}" if path else method.upper()
    logger.debug("  GAP %s → %s (%s)", label, location, field_name)
    return Gap(path, method, location, field_name)


def _skip(reason: str, context: str) -> None:
    logger.debug("  SKIP %s — %s", context, reason)


# ── Schema walker (properties + allOf/anyOf/oneOf) ───────────────────────────

def _walk_schema(
    path: str, method: str,
    schema: dict, loc: str,
    rules: WalkRules, gaps: list[Gap],
    _depth: int = 0,
) -> None:
    """Recursively walk schema properties and composed schema branches."""
    if _depth > 5 or not isinstance(schema, dict) or _has_ref(schema):
        return

    for prop_name, prop_schema in schema.get("properties", {}).items():
        base = f"{loc}.{prop_name}"
        if not isinstance(prop_schema, dict):
            _skip("not a dict", base)
            continue
        if _has_ref(prop_schema):
            _skip("$ref — cannot add siblings in OAS 3.0", base)
            continue
        if rules.description and _missing(prop_schema.get("description")):
            gaps.append(_gap(path, method, f"{base}.description", "description"))
        elif rules.description:
            logger.debug("    OK  %s.description", base)
        if rules.example and "example" not in prop_schema:
            gaps.append(_gap(path, method, f"{base}.example", "example"))
        elif rules.example:
            logger.debug("    OK  %s.example", base)
        if prop_schema.get("type") == "object" or prop_schema.get("properties"):
            _walk_schema(path, method, prop_schema, f"{base}.properties", rules, gaps, _depth + 1)

    for keyword in ("allOf", "anyOf", "oneOf"):
        for branch in schema.get(keyword, []):
            if isinstance(branch, dict) and not _has_ref(branch):
                _walk_schema(path, method, branch, loc, rules, gaps, _depth + 1)


# ── x-ai checker ─────────────────────────────────────────────────────────────

def _check_x_ai(path: str, method: str, operation: dict, rules: WalkRules, gaps: list[Gap]) -> None:
    xai = operation.get("x-ai")
    if xai is None:
        gaps.append(Gap(path, method, "x-ai", "x-ai"))
        logger.debug("  GAP %s %s → x-ai (entire object missing)", method.upper(), path)
        return
    if not isinstance(xai, dict):
        _skip(f"x-ai is {type(xai).__name__}, not a dict", f"{method.upper()} {path}")
        return
    for tag in rules.x_ai_required_tags:
        if tag not in xai or _missing(xai.get(tag)):
            gaps.append(_gap(path, method, f"x-ai.{tag}", "x-ai"))
        else:
            logger.debug("  OK  x-ai.%s", tag)


# ── Public API ────────────────────────────────────────────────────────────────

def walk(spec: dict, rules: WalkRules) -> list[Gap]:
    """Walk the OAS spec and return every Gap where a required field is absent."""
    gaps: list[Gap] = []
    paths      = spec.get("paths", {})
    components = spec.get("components", {}).get("schemas", {})

    logger.info(
        "Walker starting — %d path(s), %d component schema(s)",
        len(paths), len(components),
    )

    # info.description
    if rules.info_description:
        if _missing(spec.get("info", {}).get("description")):
            gaps.append(_gap("", "info", "description", "description"))
        else:
            logger.debug("OK  info.description")

    # Paths
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method in ("get", "post", "put", "patch", "delete", "head", "options"):
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue

            logger.debug("Checking %s %s", method.upper(), path)

            if rules.description and _missing(operation.get("description")):
                gaps.append(_gap(path, method, "description", "description"))

            if rules.x_ai:
                _check_x_ai(path, method, operation, rules, gaps)

            for i, param in enumerate(operation.get("parameters", [])):
                if not isinstance(param, dict) or _has_ref(param):
                    continue
                schema = param.get("schema") or {}
                if _has_ref(schema):
                    continue
                if rules.description and _missing(param.get("description")):
                    gaps.append(_gap(path, method, f"parameters.{i}.description", "description"))
                if rules.example and "example" not in schema:
                    gaps.append(_gap(path, method, f"parameters.{i}.schema.example", "example"))

            req_body = operation.get("requestBody")
            if req_body and not _has_ref(req_body):
                if rules.description and _missing(req_body.get("description")):
                    gaps.append(_gap(path, method, "requestBody.description", "description"))
                for ct, content in req_body.get("content", {}).items():
                    if not isinstance(content, dict):
                        continue
                    schema = content.get("schema") or {}
                    if _has_ref(schema):
                        continue
                    loc = f"requestBody.content.{ct}.schema"
                    if rules.example and "example" not in schema:
                        gaps.append(_gap(path, method, f"{loc}.example", "example"))
                    _walk_schema(path, method, schema, f"{loc}.properties", rules, gaps)

            for status_code, response in operation.get("responses", {}).items():
                if not isinstance(response, dict) or _has_ref(response):
                    continue
                if rules.description and _missing(response.get("description")):
                    gaps.append(_gap(path, method, f"responses.{status_code}.description", "description"))
                for ct, content in response.get("content", {}).items():
                    if not isinstance(content, dict):
                        continue
                    schema = content.get("schema") or {}
                    if _has_ref(schema):
                        continue
                    loc = f"responses.{status_code}.content.{ct}.schema"
                    if rules.example and "example" not in schema:
                        gaps.append(_gap(path, method, f"{loc}.example", "example"))
                    _walk_schema(path, method, schema, f"{loc}.properties", rules, gaps)

    # Component schemas
    for schema_name, schema in components.items():
        if not isinstance(schema, dict) or _has_ref(schema):
            continue
        if rules.description and _missing(schema.get("description")):
            gaps.append(_gap("", "component", f"schemas.{schema_name}.description", "description"))
        _walk_schema("", "component", schema, f"schemas.{schema_name}.properties", rules, gaps)

    logger.info("Walker done — %d gap(s)", len(gaps))
    return gaps
