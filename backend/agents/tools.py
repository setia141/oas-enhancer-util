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
                            "A JSON object where each key is a path string (e.g. '/users/{id}') "
                            "and each value is the COMPLETE enhanced path item object including all "
                            "operations, parameters, requestBody, and responses fully written out. "
                            "Only include paths you actually modified. Do NOT just list path names."
                        ),
                    },
                    "changed_components": {
                        "type": "object",
                        "description": (
                            "A JSON object where each key is a component section name (e.g. 'schemas') "
                            "and each value is a JSON object of the modified entries fully written out. "
                            "Only include sections you actually modified. Do NOT just list section names."
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
