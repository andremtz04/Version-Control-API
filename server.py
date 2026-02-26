from flask import Flask, request, jsonify, abort
from pathlib import Path
from git import Repo, InvalidGitRepositoryError
import json

# pip install flask GitPython

app = Flask(__name__)

BASE_DIR = Path("scenes").resolve()
BASE_DIR.mkdir(exist_ok=True)
try:
    repo = Repo(BASE_DIR)
except InvalidGitRepositoryError:
    repo = Repo.init(BASE_DIR)


def safe_path(relative_path: str) -> Path:
    path = (BASE_DIR / relative_path).resolve()
    if not str(path).startswith(str(BASE_DIR)):
        abort(403, "Invalid path")
    return path


def git_commit(file_path: Path, message: str):
    rel_path = file_path.relative_to(BASE_DIR)
    repo.index.add([str(rel_path)])

    if repo.is_dirty(untracked_files=True):
        repo.index.commit(message)

# GET json
# /json/SC_012/test1.json
@app.route("/json/<path:path>", methods=["GET"])
def get_json(path):
    file_path = safe_path(path)

    if not file_path.exists():
        abort(404, "File not found")

    with file_path.open("r", encoding="utf-8") as f:
        return jsonify(json.load(f))

# PUT json
# /json/SC_012/test1.json   Optional Header: Commit-Message
@app.route("/json/<path:path>", methods=["PUT"])
def put_json(path):
    if not request.is_json:
        abort(400, "Request body must be JSON")

    file_path = safe_path(path)
    incoming = request.get_json()

    commit_message = request.headers.get("Commit-Message")

    if file_path.exists():
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}

    data.update(incoming)

    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    if not commit_message:
        commit_message = f"Update {file_path.relative_to(BASE_DIR)}"

    git_commit(file_path, commit_message)

    return jsonify({
        "status": "ok",
        "written": str(file_path),
        "data": data,
        "commit_message": commit_message
    })


# GET history
# /history/scenes/SC_012/
@app.route("/history/<path:path>", methods=["GET"])
def history(path):
    target_path = safe_path(path)

    if not target_path.exists():
        abort(404, "File or folder not found")

    rel_path = str(target_path.relative_to(BASE_DIR))

    commits = list(repo.iter_commits(paths=rel_path))

    return jsonify([
        {
            "commit": c.hexsha,
            "message": c.message.strip(),
            "date": c.committed_datetime.isoformat()
        }
        for c in commits
    ])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)