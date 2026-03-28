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
                        "description": "List of suggested field additions or updates. Each item targets one specific field.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "The API path, e.g. /users/{id}. MUST be empty string '' for info-level or component suggestions.",
                                },
                                "method": {
                                    "type": "string",
                                    "description": (
                                        "HTTP method lowercase (get, post, put, patch, delete). "
                                        "Use 'component' for component schema suggestions. "
                                        "Use 'info' for spec-level info.description."
                                    ),
                                },
                                "location": {
                                    "type": "string",
                                    "description": (
                                        "CRITICAL: Copy the location EXACTLY as given in the gap list. Never set to null. "
                                        "The location already includes the field name at the end — do not shorten it. "
                                        "Examples: "
                                        "'description' — operation or info-level description; "
                                        "'parameters.0.description' — first parameter description; "
                                        "'parameters.0.schema.example' — first parameter example (ends in .example); "
                                        "'requestBody.description' — request body description; "
                                        "'requestBody.content.application/json.schema.example' — request body example; "
                                        "'requestBody.content.application/json.schema.required' — required fields array; "
                                        "'responses.200.description' — response description; "
                                        "'responses.400' — full error response object (Postman rule 2); "
                                        "'responses.200.content.application/json.schema.example' — response example; "
                                        "'x-ai' — full x-ai object; "
                                        "'x-ai.when-to-use-me' — single x-ai sub-tag; "
                                        "'x-ai.how-to-use-me' — single x-ai sub-tag; "
                                        "'x-ai.trigger-me-command' — single x-ai sub-tag; "
                                        "'schemas.MySchema.description' — component schema description (method=component, path=''); "
                                        "'schemas.MySchema.example' — component schema example (method=component, path='', ends in .example); "
                                        "'schemas.MySchema.properties.fieldName.description' — component property description (method=component, path=''); "
                                        "'schemas.MySchema.properties.fieldName.example' — component property example (method=component, path='', ends in .example). "
                                        "NEVER put 'components/schemas/...' in path — path must be empty string for components. "
                                        "For Postman missing property: location ends at the property name, "
                                        "e.g. 'requestBody.content.application/json.schema.properties.role'."
                                    ),
                                },
                                "field": {
                                    "type": "string",
                                    "enum": ["description", "example", "x-ai", "schema_property"],
                                    "description": (
                                        "'description' — text description field. "
                                        "'example' — example value field. "
                                        "'x-ai' — x-ai extension field or sub-tag (when-to-use-me / how-to-use-me / trigger-me-command). "
                                        "'schema_property' — used for Postman findings: missing properties, "
                                        "type corrections, error response schemas, required arrays. "
                                        "For schema_property the value must be a complete object."
                                    ),
                                },
                                "value": {
                                    "description": (
                                        "The suggested value. "
                                        "String for description or x-ai sub-tags. "
                                        "Any valid JSON value for example. "
                                        "Complete x-ai object {when-to-use-me, how-to-use-me, trigger-me-command} when location is 'x-ai'. "
                                        "Complete schema object {type, description, example} for schema_property. "
                                        "Complete response object {description, content} for error response schema_property. "
                                        "Full array [field1, field2] for required array schema_property."
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
