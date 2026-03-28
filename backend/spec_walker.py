"""
Phase 1 — Deterministic OAS spec walker.

Walks the spec tree and returns a list of Gaps: locations where a required
field is absent (None, empty string, or not present in the dict at all).

The walker is a COMPLETENESS checker only — it answers "is the field there?"
Quality of existing content is not judged here. That is the LLM's job at
generation time and the human reviewer's job at review time.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class WalkRules:
    description:      bool = True   # flag missing descriptions
    example:          bool = True   # flag missing examples
    x_ai:             bool = True   # flag missing x-ai object or sub-tags
    info_description: bool = True   # flag missing spec-level info.description

    # Sub-tags that must be present inside every x-ai object
    x_ai_required_tags: list = field(default_factory=lambda: [
        "when-to-use-me",
        "how-to-use-me",
        "trigger-me-command",
    ])


# ─────────────────────────────────────────────────────────────────────────────
# Gap
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Gap:
    path:     str  # API path, e.g. /users/{id}. Empty for info/components.
    method:   str  # HTTP method lowercase, "component", or "info"
    location: str  # dot-notation within the root object
    field:    str  # "description" | "example" | "x-ai"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _missing(value) -> bool:
    """True only if the value is absent, None, or empty string."""
    return value is None or (isinstance(value, str) and not value.strip())


def _has_ref(obj) -> bool:
    return isinstance(obj, dict) and "$ref" in obj


def _gap(path, method, location, field) -> Gap:
    label = f"{method.upper()} {path}" if path else method.upper()
    logger.debug("  GAP %s → %s (%s)", label, location, field)
    return Gap(path, method, location, field)


def _skip(reason: str, context: str) -> None:
    logger.debug("  SKIP %s — %s", context, reason)


def _walk_schema_properties(
    path: str, method: str,
    schema: dict, props_location: str,
    rules: WalkRules, gaps: list[Gap],
) -> None:
    for prop_name, prop_schema in schema.get("properties", {}).items():
        base = f"{props_location}.{prop_name}"
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


def _check_x_ai(path: str, method: str, operation: dict, rules: WalkRules, gaps: list[Gap]) -> None:
    xai = operation.get("x-ai")

    if xai is None:
        logger.debug("  GAP %s %s → x-ai (entire object missing)", method.upper(), path)
        gaps.append(Gap(path, method, "x-ai", "x-ai"))
        return

    if not isinstance(xai, dict):
        _skip(f"x-ai is {type(xai).__name__}, not a dict — cannot inspect sub-tags", f"{method.upper()} {path}")
        return

    for tag in rules.x_ai_required_tags:
        if tag not in xai or _missing(xai.get(tag)):
            gaps.append(_gap(path, method, f"x-ai.{tag}", "x-ai"))
        else:
            logger.debug("  OK  x-ai.%s", tag)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def walk(spec: dict, rules: WalkRules) -> list[Gap]:
    """
    Walk the OAS spec and return every Gap where a required field is absent.
    Presence only — no quality judgement on existing content.
    """
    gaps: list[Gap] = []

    paths      = spec.get("paths", {})
    components = spec.get("components", {}).get("schemas", {})
    logger.info(
        "Walker starting — %d path(s), %d component schema(s), "
        "rules: info_description=%s description=%s example=%s x_ai=%s x_ai_tags=%s",
        len(paths), len(components),
        rules.info_description, rules.description, rules.example, rules.x_ai,
        rules.x_ai_required_tags,
    )

    # ── spec info.description ─────────────────────────────────────────────────
    if rules.info_description:
        val = spec.get("info", {}).get("description")
        if _missing(val):
            gaps.append(_gap("", "info", "description", "description"))
        else:
            logger.debug("OK  info.description")

    # ── Paths ────────────────────────────────────────────────────────────────
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            _skip("path item is not a dict", path)
            continue

        for method in ("get", "post", "put", "patch", "delete", "head", "options"):
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue

            op_label = f"{method.upper()} {path}"
            logger.debug("Checking %s", op_label)

            if rules.description:
                if _missing(operation.get("description")):
                    gaps.append(_gap(path, method, "description", "description"))
                else:
                    logger.debug("  OK  description")

            if rules.x_ai:
                _check_x_ai(path, method, operation, rules, gaps)

            # Parameters
            for i, param in enumerate(operation.get("parameters", [])):
                p_label = f"{op_label} param[{i}] {param.get('name', '?')!r}"
                if not isinstance(param, dict):
                    _skip("not a dict", p_label)
                    continue
                if _has_ref(param):
                    _skip("$ref parameter", p_label)
                    continue
                schema = param.get("schema") or {}
                if _has_ref(schema):
                    _skip("$ref schema", p_label)
                    continue
                if rules.description and _missing(param.get("description")):
                    gaps.append(_gap(path, method, f"parameters.{i}.description", "description"))
                elif rules.description:
                    logger.debug("  OK  %s description", p_label)
                if rules.example and "example" not in schema:
                    gaps.append(_gap(path, method, f"parameters.{i}.schema.example", "example"))
                elif rules.example:
                    logger.debug("  OK  %s example", p_label)

            # Request body
            req_body = operation.get("requestBody")
            if req_body is None:
                logger.debug("  No requestBody for %s", op_label)
            elif _has_ref(req_body):
                _skip("$ref requestBody", op_label)
            else:
                if rules.description and _missing(req_body.get("description")):
                    gaps.append(_gap(path, method, "requestBody.description", "description"))
                elif rules.description:
                    logger.debug("  OK  requestBody description")
                for ct, content in req_body.get("content", {}).items():
                    if not isinstance(content, dict):
                        continue
                    schema = content.get("schema") or {}
                    if _has_ref(schema):
                        _skip(f"$ref schema in requestBody {ct!r}", op_label)
                        continue
                    loc = f"requestBody.content.{ct}.schema"
                    if rules.example and "example" not in schema:
                        gaps.append(_gap(path, method, f"{loc}.example", "example"))
                    elif rules.example:
                        logger.debug("  OK  requestBody %s example", ct)
                    _walk_schema_properties(path, method, schema, f"{loc}.properties", rules, gaps)

            # Responses
            for status_code, response in operation.get("responses", {}).items():
                r_label = f"{op_label} response[{status_code}]"
                if not isinstance(response, dict):
                    _skip("not a dict", r_label)
                    continue
                if _has_ref(response):
                    _skip("$ref response", r_label)
                    continue
                if rules.description and _missing(response.get("description")):
                    gaps.append(_gap(path, method, f"responses.{status_code}.description", "description"))
                elif rules.description:
                    logger.debug("  OK  %s description", r_label)
                for ct, content in response.get("content", {}).items():
                    if not isinstance(content, dict):
                        continue
                    schema = content.get("schema") or {}
                    if _has_ref(schema):
                        _skip(f"$ref schema in response {status_code} {ct!r}", op_label)
                        continue
                    loc = f"responses.{status_code}.content.{ct}.schema"
                    if rules.example and "example" not in schema:
                        gaps.append(_gap(path, method, f"{loc}.example", "example"))
                    elif rules.example:
                        logger.debug("  OK  response %s %s example", status_code, ct)
                    _walk_schema_properties(path, method, schema, f"{loc}.properties", rules, gaps)

    # ── Components / schemas ─────────────────────────────────────────────────
    for schema_name, schema in components.items():
        c_label = f"component/schemas/{schema_name}"
        if not isinstance(schema, dict):
            _skip("not a dict", c_label)
            continue
        if _has_ref(schema):
            _skip("$ref entire schema", c_label)
            continue
        if rules.description and _missing(schema.get("description")):
            gaps.append(_gap("", "component", f"schemas.{schema_name}.description", "description"))
        elif rules.description:
            logger.debug("  OK  %s description", c_label)
        _walk_schema_properties("", "component", schema, f"schemas.{schema_name}.properties", rules, gaps)

    logger.info("Walker done — %d gap(s) (fields absent)", len(gaps))
    return gaps
