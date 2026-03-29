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
    if not raw_url:
        return '/'
    # Strip scheme + host (http://host/...)
    path = re.sub(r'^https?://[^/]+', '', raw_url)
    # Strip leading {{baseUrl}} or similar env-variable host (may repeat, e.g. {{host}}{{basePath}})
    path = re.sub(r'^(\{\{[^}]+\}\})+', '', path)
    # Drop query string and fragment
    path = path.split('?')[0].split('#')[0]
    # Normalise {{variable}} → {variable}
    path = re.sub(r'\{\{([^}]+)\}\}', r'{\1}', path)
    # Normalise :param style → {param}  (only after /)
    path = re.sub(r'/:([a-zA-Z_][a-zA-Z0-9_]*)', r'/{\1}', path)
    return path or '/'


def _url_raw(url) -> str:
    """Extract the raw URL string whether url is a string or a Postman URL object."""
    if isinstance(url, str):
        return url
    if isinstance(url, dict):
        # Prefer raw; fall back to reconstructing from path array
        if url.get('raw'):
            return url['raw']
        parts = url.get('path', [])
        if parts:
            return '/' + '/'.join(str(p) for p in parts)
    return ''


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
    acc: dict keyed on (method, normalised_path) → {request_fields, response_codes, response_fields}
    Multiple scenarios for the same (method, path) are merged (union).
    """
    for item in items:
        # Folder — recurse
        if 'item' in item:
            _walk(item['item'], acc)
            continue

        request = item.get('request', {}) or {}
        method  = request.get('method', 'GET').upper()
        path    = _normalise_path(_url_raw(request.get('url', '')))

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
            for fd in (body.get('formdata') or []):
                if fd.get('key'):
                    ep['request_fields'].add(fd['key'])
        elif mode == 'urlencoded':
            for fd in (body.get('urlencoded') or []):
                if fd.get('key'):
                    ep['request_fields'].add(fd['key'])

        # ── Saved responses ───────────────────────────────────────────────────
        for resp in (item.get('response') or []):
            code = resp.get('code')
            if not code:
                continue
            code = int(code)
            ep['response_codes'].add(code)
            fields = _json_top_keys(resp.get('body', ''))
            if fields:
                ep['response_fields'].setdefault(code, set()).update(fields)


# ── Spec path matching ────────────────────────────────────────────────────────

def _path_matches(spec_path: str, postman_path: str) -> bool:
    """
    Return True if postman_path matches the spec_path template.
    e.g. spec='/users/{id}'  postman='/users/usr_abc123'  → True
    """
    spec_parts    = spec_path.strip('/').split('/')
    postman_parts = postman_path.strip('/').split('/')
    if len(spec_parts) != len(postman_parts):
        return False
    for s, p in zip(spec_parts, postman_parts):
        if s.startswith('{') and s.endswith('}'):
            continue   # path parameter — matches anything
        if s != p:
            return False
    return True


def _match_to_spec_paths(endpoints: list[ParsedEndpoint], spec_paths: list[str]) -> list[ParsedEndpoint]:
    """
    Replace concrete Postman paths with their matching spec path template.

    Fix 1 — prefer exact matches over templates:
      Spec has /users/active and /users/{id}.
      Postman /users/active → /users/active  (not /users/{id})

    Fix 2 — re-merge after matching:
      Postman has GET /users/usr_123 and GET /users/usr_456, both map to GET /users/{id}.
      Their fields are unioned into a single ParsedEndpoint.
    """
    # Sort spec paths: exact paths (no {) first, templates second
    sorted_spec = sorted(spec_paths, key=lambda p: (1 if '{' in p else 0, p))

    # Step 1 — map each endpoint to its best-matching spec path
    matched: list[ParsedEndpoint] = []
    for ep in endpoints:
        matched_path = ep.path
        for sp in sorted_spec:
            if _path_matches(sp, ep.path):
                matched_path = sp
                break
        matched.append(ParsedEndpoint(
            method=ep.method,
            path=matched_path,
            request_fields=ep.request_fields,
            response_codes=ep.response_codes,
            response_fields={k: set(v) for k, v in ep.response_fields.items()},
        ))

    # Step 2 — re-merge endpoints that now share the same (method, path)
    merged: dict[tuple, ParsedEndpoint] = {}
    for ep in matched:
        key = (ep.method, ep.path)
        if key not in merged:
            merged[key] = ep
        else:
            existing = merged[key]
            existing.request_fields.update(ep.request_fields)
            existing.response_codes.update(ep.response_codes)
            for code, fields in ep.response_fields.items():
                existing.response_fields.setdefault(code, set()).update(fields)

    return list(merged.values())


# ── GraphQL detection ─────────────────────────────────────────────────────────

def _is_graphql(acc: dict) -> bool:
    """
    Return True if the collection looks like a GraphQL collection —
    all requests go to a single path containing 'graphql'.
    Sending this to the LLM as schema diffs would produce noise.
    """
    paths = {path for (_, path) in acc}
    return len(paths) == 1 and 'graphql' in next(iter(paths)).lower()


# ── Public API ────────────────────────────────────────────────────────────────

def parse(collection_text: str, spec_paths: list[str] | None = None) -> list[ParsedEndpoint]:
    """
    Parse a Postman Collection v2.1 JSON string.
    Returns one ParsedEndpoint per unique (method, path).
    If spec_paths is provided, concrete path values are matched against spec
    path templates (e.g. /users/usr_abc123 → /users/{id}).
    Returns empty list if the input is not valid or is a GraphQL collection.
    """
    try:
        collection = json.loads(collection_text)
    except (json.JSONDecodeError, ValueError):
        return []

    acc: dict = {}
    _walk(collection.get('item', []), acc)

    if not acc or _is_graphql(acc):
        return []

    endpoints = [
        ParsedEndpoint(
            method=method,
            path=path,
            request_fields=data['request_fields'],
            response_codes=data['response_codes'],
            response_fields=data['response_fields'],
        )
        for (method, path), data in acc.items()
    ]

    if spec_paths:
        endpoints = _match_to_spec_paths(endpoints, spec_paths)

    return endpoints


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
