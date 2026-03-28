"""
Phase 1 — Deterministic OAS spec walker.

Walks the spec tree and returns a list of Gaps: locations that need
description, example, or x-ai values. No LLM involved.

Customise what counts as "poor quality" in WalkRules.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Configuration — import and override in loop_runner / prompts
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class WalkRules:
    # Which field types to look for
    description: bool = True
    example:     bool = True
    x_ai:        bool = True

    # A description is considered "poor" (needs improvement) if:
    poor_description_min_length: int = 10
    poor_description_placeholders: set = field(default_factory=lambda: {
        "string", "integer", "number", "boolean", "object", "array",
        "todo", "tbd", "n/a", "na", "none", "example", "description",
        "placeholder", "fill me in", "...",
    })


# ─────────────────────────────────────────────────────────────────────────────
# Gap — one location that needs a value
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Gap:
    path:     str   # API path, e.g. /users/{id}  (empty for components)
    method:   str   # HTTP method lowercase, or "component"
    location: str   # dot-notation within the operation/component
    field:    str   # "description" | "example" | "x-ai"
    is_update: bool = False  # True when field exists but is poor quality


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _poor_description(value, rules: WalkRules) -> bool:
    """True if value is missing or considered poor quality."""
    if value is None:
        return True
    v = str(value).strip()
    if not v:
        return True
    if len(v) < rules.poor_description_min_length:
        return True
    if v.lower() in rules.poor_description_placeholders:
        return True
    return False


def _has_ref(obj) -> bool:
    return isinstance(obj, dict) and "$ref" in obj


def _walk_schema_properties(
    path: str, method: str,
    schema: dict, props_location: str,
    rules: WalkRules, gaps: list[Gap],
) -> None:
    """Recurse into schema properties, skip $ref entries."""
    for prop_name, prop_schema in schema.get("properties", {}).items():
        if not isinstance(prop_schema, dict) or _has_ref(prop_schema):
            continue
        base = f"{props_location}.{prop_name}"
        if rules.description:
            exists = "description" in prop_schema
            if _poor_description(prop_schema.get("description"), rules):
                gaps.append(Gap(path, method, f"{base}.description", "description", is_update=exists))
        if rules.example and "example" not in prop_schema:
            gaps.append(Gap(path, method, f"{base}.example", "example"))


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def walk(spec: dict, rules: WalkRules) -> list[Gap]:
    """
    Walk the OAS spec and return every Gap that needs a value.
    Gaps are returned in spec order (paths, then components).
    """
    gaps: list[Gap] = []

    # ── Paths ────────────────────────────────────────────────────────────────
    for path, path_item in spec.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue

        for method in ("get", "post", "put", "patch", "delete", "head", "options"):
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue

            # Operation-level description
            if rules.description:
                exists = "description" in operation
                if _poor_description(operation.get("description"), rules):
                    gaps.append(Gap(path, method, "description", "description", is_update=exists))

            # x-ai extension
            if rules.x_ai and "x-ai" not in operation:
                gaps.append(Gap(path, method, "x-ai", "x-ai"))

            # Parameters
            for i, param in enumerate(operation.get("parameters", [])):
                if not isinstance(param, dict) or _has_ref(param):
                    continue
                schema = param.get("schema") or {}
                if _has_ref(schema):
                    continue
                if rules.description:
                    exists = "description" in param
                    if _poor_description(param.get("description"), rules):
                        gaps.append(Gap(path, method, f"parameters.{i}.description", "description", is_update=exists))
                if rules.example and "example" not in schema:
                    gaps.append(Gap(path, method, f"parameters.{i}.schema.example", "example"))

            # Request body
            req_body = operation.get("requestBody")
            if isinstance(req_body, dict) and not _has_ref(req_body):
                if rules.description:
                    exists = "description" in req_body
                    if _poor_description(req_body.get("description"), rules):
                        gaps.append(Gap(path, method, "requestBody.description", "description", is_update=exists))
                for ct, content in req_body.get("content", {}).items():
                    if not isinstance(content, dict):
                        continue
                    schema = content.get("schema") or {}
                    if _has_ref(schema):
                        continue
                    loc = f"requestBody.content.{ct}.schema"
                    if rules.example and "example" not in schema:
                        gaps.append(Gap(path, method, f"{loc}.example", "example"))
                    _walk_schema_properties(path, method, schema, f"{loc}.properties", rules, gaps)

            # Responses
            for status_code, response in operation.get("responses", {}).items():
                if not isinstance(response, dict) or _has_ref(response):
                    continue
                if rules.description:
                    exists = "description" in response
                    if _poor_description(response.get("description"), rules):
                        gaps.append(Gap(path, method, f"responses.{status_code}.description", "description", is_update=exists))
                for ct, content in response.get("content", {}).items():
                    if not isinstance(content, dict):
                        continue
                    schema = content.get("schema") or {}
                    if _has_ref(schema):
                        continue
                    loc = f"responses.{status_code}.content.{ct}.schema"
                    if rules.example and "example" not in schema:
                        gaps.append(Gap(path, method, f"{loc}.example", "example"))
                    _walk_schema_properties(path, method, schema, f"{loc}.properties", rules, gaps)

    # ── Components / schemas ─────────────────────────────────────────────────
    for schema_name, schema in spec.get("components", {}).get("schemas", {}).items():
        if not isinstance(schema, dict) or _has_ref(schema):
            continue
        if rules.description:
            exists = "description" in schema
            if _poor_description(schema.get("description"), rules):
                gaps.append(Gap("", "component", f"schemas.{schema_name}.description", "description", is_update=exists))
        _walk_schema_properties("", "component", schema, f"schemas.{schema_name}.properties", rules, gaps)

    logger.info(
        "Walker: %d gaps found (%d updates, %d new)",
        len(gaps),
        sum(1 for g in gaps if g.is_update),
        sum(1 for g in gaps if not g.is_update),
    )
    return gaps
