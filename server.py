from flask import Flask, request, jsonify, abort
from pathlib import Path
import json

app = Flask(__name__)


# Get json function
@app.route("/json/<path:path>", methods=["GET"])
def get_json(path):
    path = Path(path)
    if not path.exists():
        abort(404, "File not found")
    with path.open("r", encoding='utf-8') as f:
        return jsonify(json.load(f))


# Overwrite json function
@app.route("/json/<path:path>", methods=["PUT"])
def put_json(path):
    path = Path(path)
    if not request.is_json:
        abort(400, "Request body must be JSON")

    data = request.get_json()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding='utf-8') as f:
        json.dump(data, f, indent=2)

    return jsonify({
        "status": "ok",
        "written": str(path)
    })


if __name__ == "__main__":
    # app.run(debug=True)
    app.run(host="0.0.0.0", port=5000, debug=True)
