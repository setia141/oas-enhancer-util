"""
OpenAI function tool schemas and state helper functions.
"""

ENHANCER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "save_enhanced_spec",
            "description": "Save the changes made to the OAS specification.",
            "parameters": {
                "type": "object",
                "properties": {
                    "changes_made": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Human-readable list of every change applied.",
                    },
                    "changed_paths": {
                        "type": "object",
                        "description": (
                            "Only the paths that were modified — same structure as OAS 'paths'. "
                            "Omit paths you did not change."
                        ),
                    },
                    "changed_components": {
                        "type": "object",
                        "description": (
                            "Only the component sections that were modified (e.g. schemas, responses). "
                            "Omit sections you did not change."
                        ),
                    },
                },
                "required": ["changes_made", "changed_paths"],
            },
        },
    }
]


def get_breaking_changes_policy(has_postman: bool) -> str:
    if has_postman:
        return (
            "A Postman collection IS available. Breaking changes ARE allowed — "
            "align the spec with the Postman collection if responses or schemas differ."
        )
    return (
        "NO Postman collection is available. Breaking changes are NOT allowed. "
        "Only additive improvements: add examples, descriptions, new error responses, etc."
    )
