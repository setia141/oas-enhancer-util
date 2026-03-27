"""
OpenAI function tool schemas.
"""

SUGGESTER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "submit_suggestions",
            "description": "Submit a list of suggested improvements for the OAS specification.",
            "parameters": {
                "type": "object",
                "properties": {
                    "suggestions": {
                        "type": "array",
                        "description": "List of suggested field additions. Each item targets one specific field.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "The API path, e.g. /users/{id}",
                                },
                                "method": {
                                    "type": "string",
                                    "description": "HTTP method lowercase, e.g. get, post. Use 'component' for component schema suggestions.",
                                },
                                "location": {
                                    "type": "string",
                                    "description": (
                                        "Dot-notation location of the field within the operation or component. Examples: "
                                        "'description' for the operation description, "
                                        "'parameters.0.description' for first parameter, "
                                        "'parameters.0.schema.example' for first parameter example, "
                                        "'requestBody.description' for request body description, "
                                        "'requestBody.content.application/json.schema.example' for request body example, "
                                        "'responses.200.description' for response description, "
                                        "'responses.200.content.application/json.schema.example' for response example, "
                                        "'x-ai' for the x-ai extension field. "
                                        "For components: 'schemas.MySchema.description' or 'schemas.MySchema.properties.fieldName.description'."
                                    ),
                                },
                                "field": {
                                    "type": "string",
                                    "enum": ["description", "example", "x-ai"],
                                    "description": "The type of field being suggested.",
                                },
                                "value": {
                                    "description": "The suggested value. String for description, any valid JSON value for example, true for x-ai.",
                                },
                                "reason": {
                                    "type": "string",
                                    "description": "One short sentence explaining why this addition is useful.",
                                },
                            },
                            "required": ["path", "method", "location", "field", "value"],
                        },
                    },
                },
                "required": ["suggestions"],
            },
        },
    }
]
