"""
OAS Enhancer prompts.

How to customise:
  - WALK_RULES   — what the code scanner looks for (deterministic, no LLM).
  - VALUE_RULES  — how the LLM generates values for gaps found by the walker.
  - POSTMAN_RULES — what the LLM cross-checks when a Postman collection is provided.
  - Do NOT change SUGGESTER_INSTRUCTION — it assembles the final prompt.
"""
from backend.spec_walker import WalkRules  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# CUSTOMISE THIS — what the spec walker looks for
# Enforced by code, not the LLM. 100% reliable.
# ─────────────────────────────────────────────────────────────────────────────

WALK_RULES = WalkRules(
    info_description   = True,   # spec-level info.description
    description        = True,   # all operation / parameter / schema descriptions
    example            = True,   # all missing examples
    x_ai               = True,   # x-ai tag + required sub-tags on every operation

    # Sub-tags that must be present inside every x-ai object
    x_ai_required_tags = ["when-to-use-me", "how-to-use-me", "trigger-me-command"],
)

# ─────────────────────────────────────────────────────────────────────────────
# CUSTOMISE THIS — how the LLM should generate values
# ─────────────────────────────────────────────────────────────────────────────

VALUE_RULES = """
### description
- One concise sentence starting with a verb ("Returns...", "Creates...", "Deletes...").
- For info.description: outline the overall business purpose of the API in 1-2 sentences.
- For request/response schemas: explain the business purpose — why this field exists, not just what it is.
  Bad: "Represents the user status." Good: "Controls whether the user can authenticate and access protected resources."
- For enum fields: list what each value means, e.g. "Status of the order: 'pending' (awaiting payment), 'processing' (payment confirmed), 'shipped' (dispatched)."
- For format fields (date-time, email, uuid, uri): mention the expected format in the description.
- For fields with constraints (minLength, maximum, pattern): describe the constraint, e.g. "Must be between 1 and 100."
- No filler words. No generic sentences like "This is the description of..." or "Represents the...".

### example
- Must be a realistic, production-like value. Never use "string", "123", "example", or placeholders.
- Dates: use ISO 8601 format (e.g. "2024-01-15T10:30:00Z").
- IDs: use realistic prefixed formats (e.g. "usr_abc123", "ord_xyz789") unless spec implies integer.
- Emails: use realistic domains (e.g. "john.doe@company.com").
- Enums: pick the most commonly used value, not just the first one listed.

### x-ai (when location is `x-ai` — full object missing)
Generate the complete x-ai object with all three sub-tags:
{
  "when-to-use-me": "<one sentence describing the business scenario that triggers this endpoint>",
  "how-to-use-me": "<one sentence on required inputs, auth, and expected output>",
  "trigger-me-command": "<a realistic slash command or CLI trigger, e.g. /create-user email=john@company.com role=admin>"
}

### x-ai (when location is `x-ai.when-to-use-me`, `x-ai.how-to-use-me`, or `x-ai.trigger-me-command`)
Generate only the string value for that specific sub-tag.
- `when-to-use-me`: one sentence, business scenario (e.g. "Use when onboarding a new team member who needs system access.")
- `how-to-use-me`: one sentence, inputs and output (e.g. "Send email and role in the request body; returns the created user with an ID.")
- `trigger-me-command`: a meaningful slash command with realistic parameter names, not a placeholder
  (e.g. "/create-user email=<email> role=<role>")
"""

# ─────────────────────────────────────────────────────────────────────────────
# CUSTOMISE THIS — Postman cross-check rules
# Only applied when a Postman collection is uploaded.
# ─────────────────────────────────────────────────────────────────────────────

POSTMAN_RULES = """
You are given a structured Postman summary. For EVERY endpoint listed, apply ALL of the following rules.
Do not skip any endpoint. Do not output any text — only call submit_suggestions.
IMPORTANT: For every suggestion, `path` MUST be the exact spec path of the endpoint (e.g. '/orders', '/orders/{orderId}'). NEVER set path to empty string '' — that is only for component schema suggestions which do NOT apply here.

1. MISSING ERROR CODES — If Postman shows a response code (400, 401, 404, 409, 422, 500, etc.) that is
   absent from the OAS responses object for that operation, add it using field: "schema_property" at
   location `responses.{code}`, value must be a complete response object:
   {"description": "<meaningful description>", "content": {"application/json": {"schema": {"type": "object",
   "properties": {"error": {"type": "string", "description": "Error message.", "example": "Not found."}}}}}}

2. MISSING REQUEST FIELDS — For any field in Postman request body absent from OAS requestBody properties,
   add it using field: "schema_property" at location
   `requestBody.content.application/json.schema.properties.{fieldName}`.
   Value MUST include type, description, AND example.

3. MISSING RESPONSE FIELDS — For any field in a Postman response body absent from OAS response properties,
   add it using field: "schema_property" at location
   `responses.{code}.content.application/json.schema.properties.{fieldName}`.
   Value MUST include type, description, AND example.

4. NAMING INCONSISTENCIES — If Postman uses camelCase (e.g. shippingAddress) but OAS uses snake_case
   (e.g. shipping_address) for the same concept, add the camelCase version as a schema_property.

5. TYPE CORRECTIONS — If OAS declares a field as one type but Postman shows a different type,
   suggest the corrected schema with the correct type, description, AND example.

Process every endpoint in the summary before calling submit_suggestions.
"""

# ─────────────────────────────────────────────────────────────────────────────
# DO NOT CHANGE — tool-call format rules
# ─────────────────────────────────────────────────────────────────────────────

_FORMAT_RULES = """
- `example` on a parameter must go at `parameters.N.schema.example` — NOT at `parameters.N.example`
- `example` on a schema property goes at the property level inside the schema
- NEVER suggest adding any field directly alongside a `$ref` — in OAS 3.0 all sibling properties of `$ref` are ignored
- For `x-ai` sub-tags: only navigate into `x-ai.<tag>` if `x-ai` already exists as a dict.
  If `x-ai` is missing entirely, the gap location will be `x-ai` — submit the complete object as value.
- For `info.description`: method is "info", location is "description".
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
