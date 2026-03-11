"""
Native OAS 3.x → Postman Collection v2.1 converter.
No external npm/vulnerable dependencies — pure Python.
"""
import json
import re
import uuid
from typing import Any


def _parse_arg(value):
    """Accept either a JSON string or an already-parsed object (OpenAI/LiteLLM passes dicts directly)."""
    if isinstance(value, str):
        return json.loads(value)
    return value


def _make_id() -> str:
    return str(uuid.uuid4())


def _resolve_ref(oas: dict, ref: str) -> dict:
    """Resolve a $ref like '#/components/schemas/Foo'."""
    parts = ref.lstrip("#/").split("/")
    node = oas
    for part in parts:
        node = node.get(part, {})
    return node


def _schema_to_example(schema: dict, oas: dict, depth: int = 0) -> Any:
    """Generate a plausible example value from a JSON Schema node."""
    if depth > 5:
        return None
    if "$ref" in schema:
        schema = _resolve_ref(oas, schema["$ref"])

    # Use provided example/default first
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    if schema.get("examples"):
        ex = schema["examples"]
        return ex[0] if isinstance(ex, list) else next(iter(ex.values()), None)

    stype = schema.get("type")

    if stype == "object" or "properties" in schema:
        props = schema.get("properties", {})
        return {k: _schema_to_example(v, oas, depth + 1) for k, v in props.items()}

    if stype == "array" or "items" in schema:
        items = schema.get("items", {})
        return [_schema_to_example(items, oas, depth + 1)]

    if stype == "string":
        fmt = schema.get("format", "")
        if fmt == "date-time":
            return "2024-01-01T00:00:00Z"
        if fmt == "date":
            return "2024-01-01"
        if fmt == "email":
            return "user@example.com"
        if fmt == "uuid":
            return _make_id()
        if fmt == "uri":
            return "https://example.com"
        enum = schema.get("enum", [])
        if enum:
            return enum[0]
        return schema.get("title", "string").lower().replace(" ", "_")

    if stype == "integer":
        return schema.get("minimum", 1)
    if stype == "number":
        return schema.get("minimum", 1.0)
    if stype == "boolean":
        return True

    return None


def _build_url(base_url: str, path: str, parameters: list, oas: dict) -> dict:
    """Build a Postman URL object."""
    full = (base_url.rstrip("/") + path)
    # Split into host and path parts
    match = re.match(r"(https?://[^/]+)(.*)", full)
    host_str = match.group(1) if match else base_url
    path_str = match.group(2) if match else path

    # Query params
    query = []
    path_vars = []
    for param in parameters:
        if "$ref" in param:
            param = _resolve_ref(oas, param["$ref"])
        pin = param.get("in", "")
        example = param.get("example") or _schema_to_example(param.get("schema", {}), oas)
        if pin == "query":
            query.append({
                "key": param["name"],
                "value": str(example) if example is not None else "",
                "description": param.get("description", ""),
                "disabled": not param.get("required", False),
            })
        elif pin == "path":
            path_vars.append({
                "key": param["name"],
                "value": str(example) if example is not None else param["name"],
                "description": param.get("description", ""),
            })

    # Replace {param} in path with :param for Postman style
    path_str_postman = re.sub(r"\{(\w+)\}", r":\1", path_str)

    return {
        "raw": full,
        "protocol": "https" if full.startswith("https") else "http",
        "host": [host_str],
        "path": [p for p in path_str_postman.split("/") if p],
        "query": query,
        "variable": path_vars,
    }


def _build_headers(operation: dict, content_type: str | None) -> list:
    headers = []
    for param in operation.get("parameters", []):
        if param.get("in") == "header":
            headers.append({
                "key": param["name"],
                "value": str(param.get("example", "")),
                "description": param.get("description", ""),
            })
    if content_type:
        headers.append({"key": "Content-Type", "value": content_type})
    return headers


def _build_body(operation: dict, oas: dict) -> dict | None:
    rb = operation.get("requestBody", {})
    if not rb:
        return None

    content = rb.get("content", {})
    # Prefer JSON
    for media_type in ["application/json", "application/xml", "text/plain"]:
        if media_type not in content:
            continue
        media = content[media_type]
        schema = media.get("schema", {})
        if "$ref" in schema:
            schema = _resolve_ref(oas, schema["$ref"])

        # Check for inline examples first
        examples = media.get("examples", {})
        if examples:
            first = next(iter(examples.values()))
            raw_val = first.get("value", {})
        elif "example" in media:
            raw_val = media["example"]
        else:
            raw_val = _schema_to_example(schema, oas)

        return {
            "mode": "raw",
            "raw": json.dumps(raw_val, indent=2) if raw_val is not None else "{}",
            "options": {"raw": {"language": "json"}},
        }

    return None


def _build_responses(operation: dict, oas: dict) -> list:
    saved = []
    for status, resp_obj in operation.get("responses", {}).items():
        if "$ref" in resp_obj:
            resp_obj = _resolve_ref(oas, resp_obj["$ref"])
        content = resp_obj.get("content", {})
        body = "{}"
        content_type = "application/json"
        for mt, media in content.items():
            content_type = mt
            schema = media.get("schema", {})
            examples = media.get("examples", {})
            if examples:
                first = next(iter(examples.values()))
                val = first.get("value", {})
            elif "example" in media:
                val = media["example"]
            else:
                val = _schema_to_example(schema, oas)
            body = json.dumps(val, indent=2) if val is not None else "{}"
            break

        saved.append({
            "id": _make_id(),
            "name": f"{status} - {resp_obj.get('description', 'Response')}",
            "originalRequest": {},
            "status": resp_obj.get("description", "OK"),
            "code": int(status) if status.isdigit() else 200,
            "header": [{"key": "Content-Type", "value": content_type}],
            "body": body,
        })
    return saved


def _build_item(
    method: str,
    path: str,
    operation: dict,
    base_url: str,
    oas: dict,
    path_level_params: list,
) -> dict:
    all_params = path_level_params + operation.get("parameters", [])
    content = operation.get("requestBody", {}).get("content", {})
    content_type = next(iter(content), None) if content else None
    body = _build_body(operation, oas)

    return {
        "id": _make_id(),
        "name": operation.get("summary") or f"{method.upper()} {path}",
        "request": {
            "method": method.upper(),
            "header": _build_headers(operation, content_type),
            "url": _build_url(base_url, path, all_params, oas),
            "body": body,
            "description": operation.get("description", ""),
        },
        "response": _build_responses(operation, oas),
    }


def oas_to_postman(oas_json: str) -> str:
    """
    ADK Tool: Converts an OAS 3.x specification to a Postman Collection v2.1.

    Args:
        oas_json: The OAS specification as a JSON string.

    Returns:
        A Postman Collection v2.1 JSON string.
    """
    try:
        oas = _parse_arg(oas_json)
    except (json.JSONDecodeError, TypeError) as e:
        return json.dumps({"error": f"Invalid OAS JSON: {e}"})

    info = oas.get("info", {})
    servers = oas.get("servers", [{}])
    base_url = servers[0].get("url", "https://api.example.com") if servers else "https://api.example.com"

    HTTP_METHODS = ["get", "post", "put", "patch", "delete", "options", "head", "trace"]
    folders: dict[str, list] = {}  # tag → items

    for path, path_item in oas.get("paths", {}).items():
        path_params = [p for p in path_item.get("parameters", []) if isinstance(p, dict)]
        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            tags = operation.get("tags", ["Default"])
            folder = tags[0] if tags else "Default"
            item = _build_item(method, path, operation, base_url, oas, path_params)
            folders.setdefault(folder, []).append(item)

    collection_items = [
        {"id": _make_id(), "name": tag, "item": items}
        for tag, items in folders.items()
    ]

    collection = {
        "info": {
            "_postman_id": _make_id(),
            "name": info.get("title", "API Collection"),
            "description": info.get("description", ""),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            "version": info.get("version", "1.0.0"),
        },
        "item": collection_items,
        "variable": [
            {"key": "baseUrl", "value": base_url, "type": "string"}
        ],
    }

    return json.dumps(collection, indent=2)
