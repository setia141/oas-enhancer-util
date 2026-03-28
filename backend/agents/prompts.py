"""
OAS Enhancer prompts.

How to customise:
  - Change WALK_RULES to control what the code scanner looks for and what
    counts as "poor quality". No LLM involved here.
  - Change VALUE_RULES to tell the LLM how to generate good values.
  - Change POSTMAN_RULES to control what Postman cross-checking does.
  - Do NOT change SUGGESTER_INSTRUCTION — it assembles the final prompt.
"""
from backend.spec_walker import WalkRules  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# CUSTOMISE THIS — what the spec walker looks for
# These rules are enforced by code, not the LLM. 100% reliable.
# ─────────────────────────────────────────────────────────────────────────────

WALK_RULES = WalkRules(
    description = True,   # Find missing or poor-quality descriptions
    example     = True,   # Find missing examples
    x_ai        = True,   # Find operations missing x-ai extension

    # A description shorter than this is treated as poor quality
    poor_description_min_length = 10,

    # Descriptions matching any of these (case-insensitive) are treated as poor quality
    poor_description_placeholders = {
        "string", "integer", "number", "boolean", "object", "array",
        "todo", "tbd", "n/a", "na", "none", "example", "description",
        "placeholder", "fill me in", "...",
    },
)

# ─────────────────────────────────────────────────────────────────────────────
# CUSTOMISE THIS — how the LLM should generate values
# The LLM only generates values for gaps already found by the walker.
# It does NOT search the spec — the walker already did that.
# ─────────────────────────────────────────────────────────────────────────────

VALUE_RULES = """
- `description`: one concise sentence starting with a verb (e.g. "Returns...", "Creates...", "Deletes..."). No filler.
- `example`: a realistic, production-like value. Never use "string", "123", "example", or other placeholders.
- `x-ai`: replace this line entirely with your company's actual x-ai structure and value. Example: {"enabled": true, "model": "gpt-4"}
"""

# ─────────────────────────────────────────────────────────────────────────────
# CUSTOMISE THIS — Postman cross-check rules
# Only applied when a Postman collection is uploaded.
# The LLM compares Postman request/response bodies against the spec's properties.
# ─────────────────────────────────────────────────────────────────────────────

POSTMAN_RULES = """
- For any request body or response field that Postman shows but is completely absent from the spec's `properties` object: suggest adding it using `field: "schema_property"`. Set `location` to end at the property name inside `properties` (e.g. `requestBody.content.application/json.schema.properties.role`), and set `value` to the complete property schema inferred from the Postman data (e.g. `{"type": "string", "description": "User role"}`).
- If a field exists in the spec but its type contradicts what Postman shows (e.g. spec says integer but Postman shows a string value), suggest the corrected full property schema using `field: "schema_property"`.
"""

# ─────────────────────────────────────────────────────────────────────────────
# DO NOT CHANGE — tool-call format rules
# ─────────────────────────────────────────────────────────────────────────────

_FORMAT_RULES = """
- `example` on a parameter must go at `parameters.N.schema.example` — NOT at `parameters.N.example`
- `example` on a schema property goes at the property level inside the schema
- Keep description values to one concise sentence
- Keep example values short and realistic
- NEVER suggest adding any field directly alongside a `$ref` — in OAS 3.0 all sibling properties of `$ref` are ignored
"""

# ─────────────────────────────────────────────────────────────────────────────
# Assembled instruction — do not edit
# ─────────────────────────────────────────────────────────────────────────────

SUGGESTER_INSTRUCTION = f"""
You are a senior API documentation engineer.

You will be given:
1. An OpenAPI Specification (YAML) for context.
2. A list of GAPS — specific locations in the spec that are missing or have poor-quality values.
   These gaps were found by a deterministic code scanner, not by you.

Your ONLY job is to generate a good value for each gap.
Do NOT search the spec for additional gaps — the list is complete.
You MUST call `submit_suggestions` with one entry per gap. Do not skip any gap.

## Value quality rules
{VALUE_RULES.strip()}

## Format rules
{_FORMAT_RULES.strip()}

## Postman rules (only applied when a Postman collection is provided)
{POSTMAN_RULES.strip()}

You MUST call `submit_suggestions`. Do NOT write any text outside of tool calls.
"""
