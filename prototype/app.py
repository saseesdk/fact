"""Phase 1 UI: paste text, see it partitioned into factual claims vs. not.

Minimal Flask backend over claim_filter.segregate(). No database, no auth,
no build step for the frontend — a single static page in ui/.
"""

from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from claim_filter import segregate

UI_DIR = Path(__file__).parent / "ui"

app = Flask(__name__, static_folder=None)


@app.get("/")
def index():
    return send_from_directory(UI_DIR, "index.html")


@app.post("/api/segregate")
def api_segregate():
    text = (request.get_json(silent=True) or {}).get("text", "")
    if not text.strip():
        return jsonify({"claims": [], "non_claims": []})
    return jsonify(segregate(text))


if __name__ == "__main__":
    # use_reloader off: the reloader's monitor+worker process pair was
    # racing on Windows (multiple stale workers ending up bound around the
    # same port across restarts). Restart manually after editing instead.
    app.run(debug=True, port=5000, use_reloader=False)
