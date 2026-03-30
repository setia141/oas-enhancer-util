"""
OAS Enhancer — Flask Blueprint.

Drop this into any Flask app:

    from flask_ui.blueprint import oas_blueprint

    app.register_blueprint(oas_blueprint)

Routes registered:
    GET  /oas-enhancer/        — UI page
    POST /oas-enhancer/suggest — proxies SSE stream to backend
    POST /oas-enhancer/apply   — proxies apply call to backend
"""
import os

import requests
from flask import Blueprint, Response, jsonify, render_template, request, stream_with_context

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")

oas_blueprint = Blueprint(
    "oas_enhancer",
    __name__,
    template_folder="templates",
    url_prefix="/oas-enhancer",
)


@oas_blueprint.route("/")
def index():
    return render_template("index.html")


@oas_blueprint.route("/suggest", methods=["POST"])
def suggest():
    files = {}
    if "oas_file" in request.files:
        f = request.files["oas_file"]
        files["oas_file"] = (f.filename, f.read(), f.content_type or "application/octet-stream")
    if "postman_file" in request.files:
        f = request.files["postman_file"]
        if f.filename:
            files["postman_file"] = (f.filename, f.read(), f.content_type or "application/octet-stream")

    data = {}
    if request.form.get("force_refresh") == "true":
        data["force_refresh"] = "true"

    def generate():
        with requests.post(
            f"{BACKEND_URL}/oas-enhancer/suggest",
            files=files,
            data=data,
            stream=True,
            timeout=600,
        ) as r:
            for chunk in r.iter_content(chunk_size=None):
                if chunk:
                    yield chunk

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@oas_blueprint.route("/apply", methods=["POST"])
def apply():
    data = request.get_json()
    resp = requests.post(f"{BACKEND_URL}/oas-enhancer/apply", json=data, timeout=60)
    return jsonify(resp.json()), resp.status_code
