"""
Flask frontend — common homepage + OAS Enhancer util.
Proxies /enhance (SSE) and /convert to the FastAPI backend.
"""
import os
import requests
from dotenv import load_dotenv
from flask import Flask, render_template, request, Response, stream_with_context

load_dotenv()

app = Flask(__name__)

BACKEND_URL         = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
REDUNDANCY_UTIL_URL = os.environ.get("REDUNDANCY_UTIL_URL", "#")
MAX_ITERATIONS      = int(os.environ.get("MAX_ITERATIONS", 5))


@app.route("/")
def home():
    return render_template("home.html", redundancy_util_url=REDUNDANCY_UTIL_URL)


@app.route("/oas-enhancer")
def oas_enhancer():
    return render_template("index.html", max_iterations=MAX_ITERATIONS)


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
    if request.form.get("max_iterations"):
        data["max_iterations"] = request.form["max_iterations"]

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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000, debug=True)
