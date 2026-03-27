"""
OpenAI function tool schemas and state helper functions.
"""

REVIEWER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "submit_review",
            "description": "Submit the review result after analysing the OAS specification.",
            "parameters": {
                "type": "object",
                "properties": {
                    "satisfied": {
                        "type": "boolean",
                        "description": "True if the spec needs no further improvements.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Brief description of the overall state of the spec.",
                    },
                    "suggestions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of specific, actionable improvement instructions.",
                    },
                },
                "required": ["satisfied", "summary", "suggestions"],
            },
        },
    }
]

ENHANCER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "save_enhanced_spec",
            "description": "Save the fully enhanced OAS specification after applying all suggestions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "changes_made": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Human-readable list of every change applied in this iteration.",
                    },
                    "enhanced_spec": {
                        "type": "object",
                        "description": "The COMPLETE enhanced OAS 3.x object — not a diff or partial update.",
                    },
                },
                "required": ["changes_made", "enhanced_spec"],
            },
        },
    }
]


def get_breaking_changes_policy(state: dict) -> str:
    if state.get("has_postman", False):
        return (
            "A Postman collection IS available. Breaking changes ARE allowed — "
            "align the spec with the Postman collection if responses or schemas differ."
        )
    return (
        "NO Postman collection is available. Breaking changes are NOT allowed. "
        "Only additive improvements: add examples, descriptions, new error responses, etc."
    )
