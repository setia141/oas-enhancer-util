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
# Configuration — import and override in prompts.py
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class WalkRules:
    # Which field types to look for
    description:      bool = True
    example:          bool = True
    x_ai:             bool = True
    info_description: bool = True   # spec-level info.description

    # Required sub-tags inside every x-ai object
    x_ai_required_tags: list = field(default_factory=lambda: [
        "when-to-use-me",
        "how-to-use-me",
        "trigger-me-command",
    ])

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
    path:      str   # API path, e.g. /users/{id}  (empty for info/components)
    method:    str   # HTTP method lowercase, "component", or "info"
    location:  str   # dot-notation within the root object
    field:     str   # "description" | "example" | "x-ai"
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


def _gap(path, method, location, field, is_update=False) -> Gap:
    action = "UPDATE" if is_update else "NEW"
    label  = f"{method.upper()} {path}" if path else method.upper()
    logger.debug("  GAP [%s] %s → %s (%s)", action, label, location, field)
    return Gap(path, method, location, field, is_update=is_update)


def _skip(reason: str, context: str) -> None:
    logger.debug("  SKIP %s — %s", context, reason)


def _walk_schema_properties(
    path: str, method: str,
    schema: dict, props_location: str,
    rules: WalkRules, gaps: list[Gap],
) -> None:
    """Recurse into schema properties, skip $ref entries."""
    properties = schema.get("properties", {})
    if not properties:
        return

    logger.debug("    Checking %d properties at %s", len(properties), props_location)
    for prop_name, prop_schema in properties.items():
        base = f"{props_location}.{prop_name}"
        if not isinstance(prop_schema, dict):
            _skip("not a dict", base)
            continue
        if _has_ref(prop_schema):
            _skip("$ref — cannot add siblings in OAS 3.0", base)
            continue
        if rules.description:
            existing = prop_schema.get("description")
            if _poor_description(existing, rules):
                gaps.append(_gap(path, method, f"{base}.description", "description",
                                 is_update=existing is not None))
            else:
                logger.debug("    OK  description at %s = %r", base, existing)
        if rules.example:
            if "example" not in prop_schema:
                gaps.append(_gap(path, method, f"{base}.example", "example"))
            else:
                logger.debug("    OK  example at %s", base)


def _check_x_ai(path: str, method: str, operation: dict, rules: WalkRules, gaps: list[Gap]) -> None:
    """Check x-ai presence and all required sub-tags."""
    xai = operation.get("x-ai")

    if xai is None:
        # Entire x-ai object missing — one gap for the whole thing
        logger.debug("  GAP [NEW] %s %s → x-ai (x-ai — entire object missing)", method.upper(), path)
        gaps.append(Gap(path, method, "x-ai", "x-ai"))
        return

    if not isinstance(xai, dict):
        logger.debug("  SKIP x-ai at %s %s — not a dict, cannot inspect sub-tags", method.upper(), path)
        return

    # x-ai exists — check each required sub-tag
    for tag in rules.x_ai_required_tags:
        existing = xai.get(tag)
        if existing is None:
            gaps.append(_gap(path, method, f"x-ai.{tag}", "x-ai"))
        elif tag == "trigger-me-command" and _poor_description(existing, rules):
            # trigger-me-command must be meaningful, not a placeholder
            gaps.append(_gap(path, method, f"x-ai.{tag}", "x-ai", is_update=True))
        else:
            logger.debug("  OK  x-ai.%s = %r", tag, existing)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def walk(spec: dict, rules: WalkRules) -> list[Gap]:
    """
    Walk the OAS spec and return every Gap that needs a value.
    Gaps are returned in spec order (info, then paths, then components).
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
        existing = spec.get("info", {}).get("description")
        if _poor_description(existing, rules):
            logger.debug("Checking info.description")
            gaps.append(_gap("", "info", "description", "description", is_update=existing is not None))
        else:
            logger.debug("OK  info.description = %r", existing)

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
            logger.debug("Checking operation %s", op_label)

            # Operation-level description
            if rules.description:
                existing = operation.get("description")
                if _poor_description(existing, rules):
                    gaps.append(_gap(path, method, "description", "description",
                                     is_update=existing is not None))
                else:
                    logger.debug("  OK  operation description = %r", existing)

            # x-ai (full object + required sub-tags)
            if rules.x_ai:
                _check_x_ai(path, method, operation, rules, gaps)

            # Parameters
            params = operation.get("parameters", [])
            logger.debug("  Checking %d parameter(s)", len(params))
            for i, param in enumerate(params):
                p_label = f"{op_label} param[{i}] name={param.get('name', '?')!r}"
                if not isinstance(param, dict):
                    _skip("not a dict", p_label)
                    continue
                if _has_ref(param):
                    _skip("$ref parameter — resolve before suggesting", p_label)
                    continue
                schema = param.get("schema") or {}
                if _has_ref(schema):
                    _skip("$ref schema — cannot add siblings", p_label)
                    continue
                if rules.description:
                    existing = param.get("description")
                    if _poor_description(existing, rules):
                        gaps.append(_gap(path, method, f"parameters.{i}.description", "description",
                                         is_update=existing is not None))
                    else:
                        logger.debug("  OK  %s description = %r", p_label, existing)
                if rules.example:
                    if "example" not in schema:
                        gaps.append(_gap(path, method, f"parameters.{i}.schema.example", "example"))
                    else:
                        logger.debug("  OK  %s example present", p_label)

            # Request body
            req_body = operation.get("requestBody")
            if req_body is None:
                logger.debug("  No requestBody for %s", op_label)
            elif _has_ref(req_body):
                _skip("$ref requestBody — resolve before suggesting", op_label)
            else:
                logger.debug("  Checking requestBody for %s", op_label)
                if rules.description:
                    existing = req_body.get("description")
                    if _poor_description(existing, rules):
                        gaps.append(_gap(path, method, "requestBody.description", "description",
                                         is_update=existing is not None))
                    else:
                        logger.debug("  OK  requestBody description = %r", existing)
                for ct, content in req_body.get("content", {}).items():
                    if not isinstance(content, dict):
                        continue
                    schema = content.get("schema") or {}
                    if _has_ref(schema):
                        _skip(f"$ref schema in requestBody content {ct!r}", op_label)
                        continue
                    loc = f"requestBody.content.{ct}.schema"
                    if rules.example:
                        if "example" not in schema:
                            gaps.append(_gap(path, method, f"{loc}.example", "example"))
                        else:
                            logger.debug("  OK  requestBody %s example present", ct)
                    _walk_schema_properties(path, method, schema, f"{loc}.properties", rules, gaps)

            # Responses
            responses = operation.get("responses", {})
            logger.debug("  Checking %d response(s) for %s", len(responses), op_label)
            for status_code, response in responses.items():
                r_label = f"{op_label} response[{status_code}]"
                if not isinstance(response, dict):
                    _skip("not a dict", r_label)
                    continue
                if _has_ref(response):
                    _skip("$ref response — resolve before suggesting", r_label)
                    continue
                if rules.description:
                    existing = response.get("description")
                    if _poor_description(existing, rules):
                        gaps.append(_gap(path, method, f"responses.{status_code}.description", "description",
                                         is_update=existing is not None))
                    else:
                        logger.debug("  OK  %s description = %r", r_label, existing)
                for ct, content in response.get("content", {}).items():
                    if not isinstance(content, dict):
                        continue
                    schema = content.get("schema") or {}
                    if _has_ref(schema):
                        _skip(f"$ref schema in response {status_code} content {ct!r}", op_label)
                        continue
                    loc = f"responses.{status_code}.content.{ct}.schema"
                    if rules.example:
                        if "example" not in schema:
                            gaps.append(_gap(path, method, f"{loc}.example", "example"))
                        else:
                            logger.debug("  OK  response %s %s example present", status_code, ct)
                    _walk_schema_properties(path, method, schema, f"{loc}.properties", rules, gaps)

    # ── Components / schemas ─────────────────────────────────────────────────
    if components:
        logger.debug("Checking %d component schema(s)", len(components))
    for schema_name, schema in components.items():
        c_label = f"component/schemas/{schema_name}"
        if not isinstance(schema, dict):
            _skip("not a dict", c_label)
            continue
        if _has_ref(schema):
            _skip("$ref — entire schema is a reference", c_label)
            continue
        logger.debug("  Checking %s", c_label)
        if rules.description:
            existing = schema.get("description")
            if _poor_description(existing, rules):
                gaps.append(_gap("", "component", f"schemas.{schema_name}.description", "description",
                                 is_update=existing is not None))
            else:
                logger.debug("  OK  %s description = %r", c_label, existing)
        _walk_schema_properties("", "component", schema, f"schemas.{schema_name}.properties", rules, gaps)

    new_count    = sum(1 for g in gaps if not g.is_update)
    update_count = sum(1 for g in gaps if g.is_update)
    logger.info(
        "Walker done — %d gap(s) total: %d new (field missing), %d update (field poor quality)",
        len(gaps), new_count, update_count,
    )
    return gaps
