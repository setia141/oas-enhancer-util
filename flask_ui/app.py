"""
Flask frontend for OAS Enhancer.
Proxies /enhance (SSE) and /convert to the FastAPI backend.
"""
import os
import requests
from flask import Flask, render_template, request, Response, stream_with_context

app = Flask(__name__)

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/enhance", methods=["POST"])
def enhance():
    files = {}
    if "oas_file" in request.files:
        f = request.files["oas_file"]
        files["oas_file"] = (f.filename, f.read(), f.content_type or "application/octet-stream")
    if "postman_file" in request.files:
        f = request.files["postman_file"]
        if f.filename:
            files["postman_file"] = (f.filename, f.read(), f.content_type or "application/octet-stream")

    data = {}
    if request.form.get("instructions"):
        data["instructions"] = request.form["instructions"]

    def generate():
        with requests.post(
            f"{BACKEND_URL}/enhance",
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


@app.route("/convert", methods=["POST"])
def convert():
    files = {}
    if "oas_file" in request.files:
        f = request.files["oas_file"]
        files["oas_file"] = (f.filename, f.read(), f.content_type or "application/octet-stream")
    r = requests.post(f"{BACKEND_URL}/convert", files=files, timeout=60)
    return Response(r.content, status=r.status_code, content_type="application/json")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000, debug=True)
