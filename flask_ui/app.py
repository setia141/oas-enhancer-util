"""
Flask frontend — mounts the OAS Enhancer blueprint.
"""
import os

from dotenv import load_dotenv
from flask import Flask, render_template

load_dotenv()

from .blueprint import oas_blueprint  # noqa: E402

REDUNDANCY_UTIL_URL = os.environ.get("REDUNDANCY_UTIL_URL", "#")

app = Flask(__name__)
app.register_blueprint(oas_blueprint)


@app.route("/")
def home():
    return render_template("home.html", redundancy_util_url=REDUNDANCY_UTIL_URL)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000, debug=True)
