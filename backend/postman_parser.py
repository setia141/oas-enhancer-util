"""
Postman Collection v2.1 parser.

Extracts a clean per-endpoint summary from a raw collection:
  - method + normalised path  ({{vars}} → {param}, :param → {param})
  - request body fields       (union across all scenarios for that endpoint)
  - response codes seen       (union)
  - response body fields      (union per code across all scenarios)

Nested folders are walked recursively.
Scripts, auth, pre-request hooks, test scripts, and env variables are ignored.
"""
import json
import re
from dataclasses import dataclass, field


@dataclass
class ParsedEndpoint:
    method: str
    path: str
    request_fields: set[str]
    response_codes: set[int]
    response_fields: dict[int, set[str]]   # code → top-level field names


# ── URL normalisation ─────────────────────────────────────────────────────────

def _normalise_path(raw_url: str) -> str:
    """
    Extract the path component from a raw URL and normalise variable styles:
      {{baseUrl}}/users/{{userId}}  →  /users/{userId}
      http://host/users/:id         →  /users/{id}
    """
    # Strip scheme + host (http://host/...)
    path = re.sub(r'^https?://[^/]+', '', raw_url)
    # Strip leading {{baseUrl}} or similar env-variable host
    path = re.sub(r'^\{\{[^}]+\}\}', '', path)
    # Drop query string and fragment
    path = path.split('?')[0].split('#')[0]
    # Normalise {{variable}} → {variable}
    path = re.sub(r'\{\{([^}]+)\}\}', r'{\1}', path)
    # Normalise :param style → {param}
    path = re.sub(r'/:([a-zA-Z_][a-zA-Z0-9_]*)', r'/{\1}', path)
    return path or '/'


# ── Field extraction ──────────────────────────────────────────────────────────

def _json_top_keys(text: str) -> set[str]:
    """Parse a JSON string and return its top-level keys. Returns empty set on failure."""
    if not text or not text.strip():
        return set()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return set(parsed.keys())
    except (json.JSONDecodeError, ValueError):
        pass
    return set()


# ── Recursive collection walker ───────────────────────────────────────────────

def _walk(items: list, acc: dict) -> None:
    """
    Recursively walk collection items.
    acc: dict keyed on (method, path) → {request_fields, response_codes, response_fields}
    Multiple scenarios for the same endpoint are merged (union).
    """
    for item in items:
        # Folder — recurse
        if 'item' in item:
            _walk(item['item'], acc)
            continue

        request = item.get('request', {})
        method  = request.get('method', 'GET').upper()

        url = request.get('url', '')
        raw = url.get('raw', '') if isinstance(url, dict) else url
        path = _normalise_path(raw)

        key = (method, path)
        if key not in acc:
            acc[key] = {'request_fields': set(), 'response_codes': set(), 'response_fields': {}}
        ep = acc[key]

        # ── Request body ──────────────────────────────────────────────────────
        body = request.get('body', {}) or {}
        mode = body.get('mode', '')
        if mode == 'raw':
            ep['request_fields'].update(_json_top_keys(body.get('raw', '')))
        elif mode == 'formdata':
            for fd in body.get('formdata', []):
                if fd.get('key'):
                    ep['request_fields'].add(fd['key'])
        elif mode == 'urlencoded':
            for fd in body.get('urlencoded', []):
                if fd.get('key'):
                    ep['request_fields'].add(fd['key'])

        # ── Saved responses ───────────────────────────────────────────────────
        for resp in item.get('response', []):
            code = resp.get('code')
            if not code:
                continue
            code = int(code)
            ep['response_codes'].add(code)
            fields = _json_top_keys(resp.get('body', ''))
            if fields:
                ep['response_fields'].setdefault(code, set()).update(fields)


# ── Public API ────────────────────────────────────────────────────────────────

def parse(collection_text: str) -> list[ParsedEndpoint]:
    """
    Parse a Postman Collection v2.1 JSON string.
    Returns one ParsedEndpoint per unique (method, path).
    Returns empty list if the input is not a valid collection.
    """
    try:
        collection = json.loads(collection_text)
    except (json.JSONDecodeError, ValueError):
        return []

    acc: dict = {}
    _walk(collection.get('item', []), acc)

    return [
        ParsedEndpoint(
            method=method,
            path=path,
            request_fields=data['request_fields'],
            response_codes=data['response_codes'],
            response_fields=data['response_fields'],
        )
        for (method, path), data in acc.items()
    ]


def format_for_llm(endpoints: list[ParsedEndpoint]) -> str:
    """
    Render parsed endpoints as a clean structured summary for the LLM.
    Replaces the raw Postman JSON — the LLM sees only what was observed,
    with no noise from scripts, auth config, or environment variables.
    """
    if not endpoints:
        return "(no endpoints extracted from Postman collection)"

    lines = ["## Postman collection — observed endpoints\n"]
    for ep in sorted(endpoints, key=lambda e: (e.path, e.method)):
        lines.append(f"### {ep.method} {ep.path}")
        if ep.request_fields:
            lines.append(f"  Request body fields : {', '.join(sorted(ep.request_fields))}")
        if ep.response_codes:
            lines.append(f"  Response codes seen : {', '.join(str(c) for c in sorted(ep.response_codes))}")
        for code, fields in sorted(ep.response_fields.items()):
            if fields:
                lines.append(f"  Response {code} fields  : {', '.join(sorted(fields))}")
        lines.append("")
    return "\n".join(lines)
