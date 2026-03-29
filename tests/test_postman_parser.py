"""
Comprehensive tests for postman_parser.py covering real-world messy collection scenarios.
Run from project root:  python -m pytest tests/test_postman_parser.py -v
"""
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backend.postman_parser import parse, format_for_llm, _normalise_path

# ── Helpers ───────────────────────────────────────────────────────────────────

def _col(items):
    return json.dumps({"info": {"name": "Test", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"}, "item": items})

def _req(method, url, body=None):
    r = {"method": method, "url": {"raw": url}}
    if body:
        r["body"] = body
    return r

def _saved_resp(code, body_dict=None, body_str=None):
    return {"code": code, "status": str(code), "body": json.dumps(body_dict) if body_dict else (body_str or "")}

def _item(name, method, url, body=None, responses=None):
    return {"name": name, "request": _req(method, url, body), "response": responses or []}

def endpoints_by_path(result):
    return {(ep.method, ep.path): ep for ep in result}

# ── URL normalisation tests ───────────────────────────────────────────────────

def test_normalise_env_variable_host():
    assert _normalise_path("{{baseUrl}}/users") == "/users"

def test_normalise_http_host():
    assert _normalise_path("http://localhost:8000/users/123") == "/users/123"

def test_normalise_https_host():
    assert _normalise_path("https://api.example.com/v1/users") == "/v1/users"

def test_normalise_double_env_variable():
    assert _normalise_path("{{host}}{{basePath}}/users") == "/users"

def test_normalise_inline_variable():
    assert _normalise_path("{{baseUrl}}/users/{{userId}}") == "/users/{userId}"

def test_normalise_colon_param():
    assert _normalise_path("{{baseUrl}}/users/:id") == "/users/{id}"

def test_normalise_mixed_styles():
    assert _normalise_path("{{baseUrl}}/orgs/{{orgId}}/users/:userId") == "/orgs/{orgId}/users/{userId}"

def test_normalise_query_string_stripped():
    assert _normalise_path("{{baseUrl}}/users?page=1&limit=10") == "/users"

def test_normalise_fragment_stripped():
    assert _normalise_path("{{baseUrl}}/users#section") == "/users"

def test_normalise_empty():
    assert _normalise_path("") == "/"

def test_normalise_url_as_string():
    """URL field is a plain string, not object."""
    col = _col([_item("Get", "GET", "{{baseUrl}}/products")])
    result = parse(col)
    assert len(result) == 1
    assert result[0].path == "/products"

def test_normalise_url_object_no_raw():
    """URL object has path array but no raw field."""
    col = json.dumps({"info": {"name": "T"}, "item": [{
        "name": "Get User",
        "request": {
            "method": "GET",
            "url": {"path": ["users", "{{userId}}"]}
        },
        "response": []
    }]})
    result = parse(col)
    assert len(result) == 1
    assert result[0].path == "/users/{userId}"

# ── Basic parsing ─────────────────────────────────────────────────────────────

def test_basic_post_with_body():
    col = _col([_item("Create User", "POST", "{{baseUrl}}/users",
        body={"mode": "raw", "raw": json.dumps({"email": "a@b.com", "role": "admin"})},
        responses=[_saved_resp(201, {"id": "usr_1", "email": "a@b.com"})]
    )])
    result = parse(col)
    assert len(result) == 1
    ep = result[0]
    assert ep.method == "POST"
    assert ep.path == "/users"
    assert ep.request_fields == {"email", "role"}
    assert ep.response_codes == {201}
    assert ep.response_fields[201] == {"id", "email"}

def test_basic_get_no_body():
    col = _col([_item("List Users", "GET", "{{baseUrl}}/users",
        responses=[_saved_resp(200, {"items": [], "total": 0})]
    )])
    result = parse(col)
    ep = result[0]
    assert ep.request_fields == set()
    assert ep.response_fields[200] == {"items", "total"}

def test_no_saved_responses():
    """Requests without saved responses — request fields still extracted."""
    col = _col([_item("Create", "POST", "{{baseUrl}}/orders",
        body={"mode": "raw", "raw": json.dumps({"product_id": "p1", "qty": 2})}
    )])
    result = parse(col)
    assert result[0].request_fields == {"product_id", "qty"}
    assert result[0].response_codes == set()

# ── Body modes ────────────────────────────────────────────────────────────────

def test_formdata_body():
    col = _col([_item("Upload", "POST", "{{baseUrl}}/upload",
        body={"mode": "formdata", "formdata": [
            {"key": "file", "type": "file"},
            {"key": "description", "type": "text"},
        ]}
    )])
    result = parse(col)
    assert result[0].request_fields == {"file", "description"}

def test_urlencoded_body():
    col = _col([_item("Login", "POST", "{{baseUrl}}/auth/token",
        body={"mode": "urlencoded", "urlencoded": [
            {"key": "username", "value": "admin"},
            {"key": "password", "value": "secret"},
        ]}
    )])
    result = parse(col)
    assert result[0].request_fields == {"username", "password"}

def test_non_json_response_body():
    """XML/HTML response bodies — silently ignored, no crash."""
    col = _col([_item("Get HTML", "GET", "{{baseUrl}}/page",
        responses=[{"code": 200, "status": "OK", "body": "<html><body>Hello</body></html>"}]
    )])
    result = parse(col)
    assert result[0].response_codes == {200}
    assert result[0].response_fields == {}  # no fields extracted, no crash

def test_empty_response_body():
    col = _col([_item("Delete", "DELETE", "{{baseUrl}}/users/1",
        responses=[{"code": 204, "status": "No Content", "body": ""}]
    )])
    result = parse(col)
    assert result[0].response_codes == {204}

# ── Multiple scenarios for same endpoint ─────────────────────────────────────

def test_multiple_scenarios_merged():
    """Two saved responses for the same endpoint — fields should be unioned."""
    col = _col([
        _item("Create User - Success", "POST", "{{baseUrl}}/users",
            body={"mode": "raw", "raw": json.dumps({"email": "a@b.com", "role": "admin"})},
            responses=[_saved_resp(201, {"id": "u1", "email": "a@b.com", "createdAt": "2024-01-01"})]
        ),
        _item("Create User - Validation Error", "POST", "{{baseUrl}}/users",
            body={"mode": "raw", "raw": json.dumps({"email": "bad"})},
            responses=[_saved_resp(400, {"error": "Invalid email", "field": "email"})]
        ),
    ])
    result = parse(col)
    assert len(result) == 1  # merged into one endpoint
    ep = result[0]
    assert ep.request_fields == {"email", "role"}  # union
    assert ep.response_codes == {201, 400}
    assert ep.response_fields[201] == {"id", "email", "createdAt"}
    assert ep.response_fields[400] == {"error", "field"}

def test_multiple_scenarios_different_request_fields():
    """Different scenarios send different fields — all should appear."""
    col = _col([
        _item("Create with all fields", "POST", "{{baseUrl}}/products",
            body={"mode": "raw", "raw": json.dumps({"name": "x", "price": 10, "sku": "ABC"})}
        ),
        _item("Create minimal", "POST", "{{baseUrl}}/products",
            body={"mode": "raw", "raw": json.dumps({"name": "y", "price": 5})}
        ),
    ])
    result = parse(col)
    assert len(result) == 1
    assert result[0].request_fields == {"name", "price", "sku"}

# ── Spec path matching ────────────────────────────────────────────────────────

def test_concrete_path_matched_to_spec_template():
    """Postman uses concrete values — should be matched to spec template."""
    col = _col([_item("Get User", "GET", "{{baseUrl}}/users/usr_abc123",
        responses=[_saved_resp(200, {"id": "usr_abc123", "email": "a@b.com"})]
    )])
    spec_paths = ["/users", "/users/{id}"]
    result = parse(col, spec_paths)
    assert len(result) == 1
    assert result[0].path == "/users/{id}"

def test_exact_path_preferred_over_template():
    """
    Spec has both /users/active and /users/{id}.
    Postman /users/active should match /users/active, NOT /users/{id}.
    """
    col = _col([_item("List Active", "GET", "{{baseUrl}}/users/active")])
    spec_paths = ["/users/{id}", "/users/active"]  # template listed first
    result = parse(col, spec_paths)
    assert result[0].path == "/users/active"

def test_no_spec_match_kept_as_is():
    """Path not in spec — kept as original normalised path."""
    col = _col([_item("Webhook", "POST", "{{baseUrl}}/webhooks/stripe")])
    spec_paths = ["/users", "/orders"]
    result = parse(col, spec_paths)
    assert result[0].path == "/webhooks/stripe"

def test_multiple_concrete_values_merged_after_matching():
    """
    Two requests with different concrete IDs both map to same spec template.
    Must be merged into one endpoint, not two.
    """
    col = _col([
        _item("Get User 1", "GET", "{{baseUrl}}/users/usr_111",
            responses=[_saved_resp(200, {"id": "usr_111", "email": "a@b.com", "role": "admin"})]
        ),
        _item("Get User 2", "GET", "{{baseUrl}}/users/usr_222",
            responses=[_saved_resp(200, {"id": "usr_222", "email": "b@c.com", "status": "active"})]
        ),
    ])
    spec_paths = ["/users/{id}"]
    result = parse(col, spec_paths)
    assert len(result) == 1  # must be merged, not 2
    ep = result[0]
    assert ep.path == "/users/{id}"
    assert ep.response_fields[200] == {"id", "email", "role", "status"}  # union of both

def test_deep_nested_path_matched():
    col = _col([_item("Get Role", "GET", "{{baseUrl}}/orgs/org_123/users/usr_456/roles",
        responses=[_saved_resp(200, {"roles": ["admin"]})]
    )])
    spec_paths = ["/orgs/{orgId}/users/{userId}/roles"]
    result = parse(col, spec_paths)
    assert result[0].path == "/orgs/{orgId}/users/{userId}/roles"

def test_already_normalised_path_still_matches():
    """Path already has {variable} style — should still match spec template."""
    col = _col([_item("Get", "GET", "{{baseUrl}}/users/{{userId}}")])
    spec_paths = ["/users/{id}"]
    result = parse(col, spec_paths)
    # {userId} matches {id} — both are path params
    assert result[0].path == "/users/{id}"

# ── Nested folders ────────────────────────────────────────────────────────────

def test_nested_folders_3_levels():
    col = json.dumps({"info": {"name": "T"}, "item": [
        {"name": "Users", "item": [
            {"name": "CRUD", "item": [
                {"name": "Auth", "item": [
                    _item("Create", "POST", "{{baseUrl}}/users",
                        body={"mode": "raw", "raw": json.dumps({"email": "x"})})
                ]}
            ]}
        ]}
    ]})
    result = parse(col)
    assert len(result) == 1
    assert result[0].path == "/users"
    assert result[0].request_fields == {"email"}

def test_mixed_folders_and_items():
    col = json.dumps({"info": {"name": "T"}, "item": [
        _item("List", "GET", "{{baseUrl}}/products"),
        {"name": "Auth folder", "item": [
            _item("Login", "POST", "{{baseUrl}}/auth/login",
                body={"mode": "raw", "raw": json.dumps({"username": "u", "password": "p"})})
        ]},
        _item("Health", "GET", "{{baseUrl}}/health"),
    ]})
    result = parse(col)
    paths = {ep.path for ep in result}
    assert paths == {"/products", "/auth/login", "/health"}

# ── GraphQL detection ─────────────────────────────────────────────────────────

def test_graphql_collection_returns_empty():
    col = _col([
        _item("GetUser", "POST", "{{baseUrl}}/graphql",
            body={"mode": "raw", "raw": json.dumps({"query": "{ user { id } }"})}),
        _item("CreateUser", "POST", "{{baseUrl}}/graphql",
            body={"mode": "raw", "raw": json.dumps({"query": "mutation { createUser }"})}),
    ])
    result = parse(col)
    assert result == []

def test_graphql_with_spec_paths_still_empty():
    col = _col([_item("Q", "POST", "https://api.example.com/graphql")])
    result = parse(col, spec_paths=["/users"])
    assert result == []

# ── Edge cases ────────────────────────────────────────────────────────────────

def test_empty_collection():
    col = json.dumps({"info": {"name": "Empty"}, "item": []})
    assert parse(col) == []

def test_invalid_json():
    assert parse("not json at all") == []

def test_invalid_json_response_body_no_crash():
    col = _col([_item("Get", "GET", "{{baseUrl}}/users",
        responses=[{"code": 200, "status": "OK", "body": "just a plain string response"}]
    )])
    result = parse(col)
    assert result[0].response_codes == {200}
    assert result[0].response_fields == {}

def test_null_body_no_crash():
    col = json.dumps({"info": {"name": "T"}, "item": [{
        "name": "Get",
        "request": {"method": "GET", "url": {"raw": "{{baseUrl}}/users"}, "body": None},
        "response": []
    }]})
    result = parse(col)
    assert result[0].request_fields == set()

def test_missing_response_code_skipped():
    col = _col([_item("Get", "GET", "{{baseUrl}}/users",
        responses=[{"status": "OK", "body": json.dumps({"id": "1"})}]  # no code field
    )])
    result = parse(col)
    assert result[0].response_codes == set()

def test_multiple_response_codes_for_one_endpoint():
    col = _col([_item("Get", "GET", "{{baseUrl}}/users/1",
        responses=[
            _saved_resp(200, {"id": "1", "email": "a@b.com"}),
            _saved_resp(404, {"error": "Not found"}),
            _saved_resp(401, {"error": "Unauthorized"}),
        ]
    )])
    result = parse(col, ["/users/{id}"])
    ep = result[0]
    assert ep.response_codes == {200, 404, 401}
    assert ep.response_fields[404] == {"error"}

def test_format_for_llm_output():
    col = _col([
        _item("Create User", "POST", "{{baseUrl}}/users",
            body={"mode": "raw", "raw": json.dumps({"email": "a@b.com", "role": "admin"})},
            responses=[_saved_resp(201, {"id": "u1", "email": "a@b.com"}), _saved_resp(400, {"error": "bad"})]
        ),
    ])
    result = parse(col)
    output = format_for_llm(result)
    assert "### POST /users" in output
    assert "email, role" in output
    assert "Response codes seen" in output
    assert "201" in output
    assert "400" in output

def test_format_for_llm_empty():
    assert "(no endpoints" in format_for_llm([])


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import traceback
    tests = {k: v for k, v in globals().items() if k.startswith("test_")}
    passed, failed = 0, 0
    for name, fn in tests.items():
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {name}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed out of {passed + failed} tests")
    sys.exit(1 if failed else 0)
