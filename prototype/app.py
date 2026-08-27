"""Phase 1 UI: paste text, see it partitioned into factual claims vs. not.

Minimal Flask backend over claim_filter.segregate(). No database, no auth,
no build step for the frontend — a single static page in ui/.
"""

from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from claim_filter import segregate
from verify import verify

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


@app.post("/api/verify")
def api_verify():
    claim = (request.get_json(silent=True) or {}).get("claim", "")
    if not claim.strip():
        return jsonify({"error": "No claim provided."}), 400
    return jsonify(verify(claim))


@app.errorhandler(Exception)
def handle_unexpected_error(e):
    # medical_retrieval.py already degrades network/parsing failures to []
    # rather than raising, so this is a backstop for genuinely unexpected
    # bugs — the UI's fetch() expects JSON, and an HTML error page would
    # otherwise just show up as an opaque "Failed: Unexpected token '<'".
    app.logger.exception("Unhandled error in %s", request.path)
    return jsonify({"error": "Internal error — check server logs."}), 500


if __name__ == "__main__":
    # use_reloader off: the reloader's monitor+worker process pair was
    # racing on Windows (multiple stale workers ending up bound around the
    # same port across restarts). Restart manually after editing instead.
    app.run(debug=True, port=5000, use_reloader=False)
