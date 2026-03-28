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
                                        "For components: 'schemas.MySchema.description' or 'schemas.MySchema.properties.fieldName.description'. "
                                        "For adding a missing property from Postman: location must point to the property name inside properties, "
                                        "e.g. 'requestBody.content.application/json.schema.properties.role' or "
                                        "'responses.201.content.application/json.schema.properties.createdAt'."
                                    ),
                                },
                                "field": {
                                    "type": "string",
                                    "enum": ["description", "example", "x-ai", "schema_property"],
                                    "description": (
                                        "The type of field being suggested. Use 'schema_property' ONLY when Postman shows "
                                        "a request body or response field that is completely missing from the spec's properties object. "
                                        "For schema_property, location must end at the property name (not .description or .example), "
                                        "and value must be the complete property schema object e.g. {\"type\": \"string\", \"description\": \"...\"}."
                                    ),
                                },
                                "value": {
                                    "description": (
                                        "The suggested value. String for description, any valid JSON value for example or x-ai, "
                                        "a complete schema object e.g. {\"type\": \"string\", \"description\": \"...\"} for schema_property."
                                    ),
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
