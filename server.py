from flask import Flask, request, jsonify, abort, send_file
from pathlib import Path
from git import Repo, InvalidGitRepositoryError
from datetime import datetime, timezone
from openai import OpenAI
from dotenv import load_dotenv
import json
import shutil 
import base64
import io
import os


# pip install flask GitPython OpenAI python-dotenv
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = Flask(__name__)
BASE_DIR = Path("projects").resolve()
BASE_DIR.mkdir(exist_ok=True)

def get_project_repo(project_name: str):
    project_path = BASE_DIR / project_name
    project_path.mkdir(parents=True, exist_ok=True)

    try:
        return Repo(project_path)
    except InvalidGitRepositoryError:
        return Repo.init(project_path)


def rotate_versions(scene_path: Path, role: str):
    oldest = scene_path / f"{role}_5.json"
    if oldest.exists():
        oldest.unlink()

    for i in range(4, 0, -1):
        src = scene_path / f"{role}_{i}.json"
        dst = scene_path / f"{role}_{i+1}.json"
        if src.exists():
            src.rename(dst)

    current = scene_path / f"{role}.json"
    if current.exists():
        current.rename(scene_path / f"{role}_1.json")


# GET json
# /projects/Project1/Scene1/Shot1/Shot1.json
@app.route("/projects/<project>/<scene>/<shot>/<file>", methods=["GET"])
def get_json(project, scene, shot, file):
    file_path = BASE_DIR / project / scene / shot / file

    if not file_path.exists():
        abort(404, "File not found")

    with file_path.open("r", encoding="utf-8") as f:
        return jsonify(json.load(f))

# PUT json
# /projects/Project1/Scene1/Shot1/Director.json
@app.route("/projects/<project>/<scene>/<shot>/<file>", methods=["PUT"])
def update_role_file(project, scene, shot, file):
    repo = get_project_repo(project)
    role = file.replace(".json", "")
    shot_path = BASE_DIR / project / scene / shot
    role_path = shot_path / f"{role}.json"
    
    shot_path.mkdir(parents=True, exist_ok=True)
    rotate_versions(shot_path, role)
    data = request.get_json()

    if "metadata" in data and "data" in data:
        wrapped = data
    else:
        wrapped = {
            "metadata": {
                "pipline_State": data.get("Stage"),
                "role": role,
                "timestamp": datetime.now(timezone.utc).isoformat()
            },
            "data": data
        }

    # Converts to json file
    with role_path.open("w") as f:
        json.dump(wrapped, f, indent=2)

    # Commits
    rel_path = role_path.relative_to(BASE_DIR / project)
    repo.index.add([str(rel_path)])
    repo.index.commit(f"{role} commited in {shot}")

    return jsonify({
        "status": "committed"
    })

# POST /rollback?version=3
@app.route("/projects/<project>/<scene>/<shot>/<role>/rollback", methods=["POST"])
def rollback_role(project, scene, shot, role):

    version = request.args.get("version")

    if not version:
        abort(400, "version required")

    shot_path = BASE_DIR / project / scene / shot
    role = role.replace(".json", "")
    version_file = shot_path / f"{role}_{version}.json"
    current_file = shot_path / f"{role}.json"

    if not version_file.exists():
        abort(404, "Version not found")

    # Copy version to current
    shutil.copy(version_file, current_file)

    # Commits
    repo = get_project_repo(project)
    rel_path = current_file.relative_to(BASE_DIR / project)
    repo.index.add([str(rel_path)])
    repo.index.commit(f"{role} rolled back to version {version}")

    return jsonify({"status": f"rolled back to {role}_{version}"})


# POST merge files
@app.route("/projects/<project>/<scene>/<shot>/<role>/merge", methods=["POST"])
def merge_role(project, scene, shot, file):

    repo = get_project_repo(project)
    shot_path = BASE_DIR / project/ scene / shot
    role_path = shot_path / file
    master_path = shot_path / "Shot.json"

    if not master_path.exists():
        abort(404, "Shot.json not found")

    with role_path.open("r") as f:
        role_data = json.load(f)

    with master_path.open("w") as f:
        json.dump(role_data, f, indent=2)

    #Commit
    rel_path = master_path.relative_to(BASE_DIR / project)
    repo.index.add([str(rel_path)])
    repo.index.commit(f"Merged {file} current file into Shot")

    return jsonify({
        "status": f"merged {file} into shot"
    })

# GET history
# /history/scenes/SC_012/
@app.route("/projects/<project>/<scene>/<shot>/<role>/history", methods=["GET"])
def history(project, scene, shot, role):
    repo = get_project_repo(project)
    file_path = BASE_DIR / project/ scene/ shot/ role

    if not file_path.exists():
        abort(404, "File or folder not found")

    rel_path = file_path.relative_to(BASE_DIR / project)

    commits = list(repo.iter_commits(paths=str(rel_path)))

    return jsonify([
        {
            "commit": c.hexsha,
            "message": c.message.strip(),
            "date": c.committed_datetime.isoformat()
        }
        for c in commits
    ])


# GET Diff
@app.route("/projects/<project>/<scene>/<shot>/diff", methods=["GET"])
def diff_files(project, scene, shot):

    file1 = request.args.get("file1")
    file2 = request.args.get("file2")

    if not file1 or not file2:
        abort(400, "file1 and file2 required")

    shot_path = BASE_DIR / project / scene / shot

    path1 = shot_path / file1
    path2 = shot_path / file2

    if not path1.exists() or not path2.exists():
        abort(404, "One of the files does not exist")

    with path1.open() as f:
        data1 = json.load(f)

    with path2.open() as f:
        data2 = json.load(f)

    diff = compute_diff(data1, data2)

    return jsonify({
        "file1": file1,
        "file2": file2,
        "diff": diff
    })



def compute_diff(cur_data, prev_data):

    old_actors = {}
    new_actors = {}

    old_list = prev_data.get("data", {}).get("Actors", {})
    new_list = cur_data.get("data", {}).get("Actors", {})
    
    for actor in old_list:
        actor_type = actor["ActorType"] + "_" + actor["Instance"]
        old_actors[actor_type] = actor

    for actor in new_list:
        actor_type = actor["ActorType"] + "_" + actor["Instance"]
        new_actors[actor_type] = actor

    added = []
    removed = []
    modified = []

    # Added or modified
    for actor_type, new_actor in new_actors.items():

        # They were added
        if actor_type not in old_actors:
            added.append(new_actor)

        else:
            old_actor = old_actors[actor_type]

            # Modified
            changes = {}

            for field in new_actor:
                if field not in old_actor:
                    changes[field] = {
                        "previous": None,
                        "current": new_actor[field]
                    }
                elif old_actor[field] != new_actor[field]:
                    changes[field] = {
                        "previous": old_actor[field],
                        "current": new_actor[field]
                    }
            if changes:
                modified.append({
                    "actor": actor_type,
                    "changes": changes
                })

    # Removed
    for actor_type, old_actor in old_actors.items():
        if actor_type not in new_actors:
            removed.append(old_actor)

    return {
        "added": added,
        "removed": removed,
        "modified": modified
    }


# File viewer (AI GEN)
@app.route("/", defaults={"req_path": ""})
@app.route("/browse/<path:req_path>")
def browse(req_path):

    abs_path = BASE_DIR / req_path

    if not abs_path.exists():
        abort(404)

    # If file → return file
    if abs_path.is_file():
        return send_file(abs_path)

    # If directory → list contents
    files = []
    for item in abs_path.iterdir():
        files.append({
            "name": item.name,
            "path": f"{req_path}/{item.name}",
            "type": "dir" if item.is_dir() else "file"
        })

    html = f"<h2>Project Directory</h2><ul>"

    if req_path != "":
        parent = "/".join(req_path.split("/")[:-1])
        html += f'<li><a href="/browse/{parent}">⬅ Back</a></li>'

    for f in files:
        if f["type"] == "dir":
            html += f'<li>📁 <a href="/browse/{f["path"]}">{f["name"]}</a></li>'
        else:
            html += f'<li>📄 <a href="/browse/{f["path"]}">{f["name"]}</a></li>'

    html += "</ul>"

    return html

# # GET all branches
# @app.route("/branches", methods=["GET"])
# def list_branches():
#     branches = [b.name for b in repo.branches]

#     return jsonify({
#         "current":  repo.active_branch.name, 
#         "branches": branches
#     })

# # POST /branches/<branch_name>?from_commit=<value>
# @app.route("/branches/<branch_name>", methods=["POST"])
# def create_branches(branch_name):
    
#     if (branch_name in [b.name for b in repo.branches]):
#         abort(404, "Branch name already exist")

#     from_commit = request.args.get("from_commit")
#     print(from_commit)
#     if from_commit:
#         sel_commit = repo.commit(from_commit)
#         repo.create_head(branch_name, sel_commit)
#     else:
#         repo.create_head(branch_name)

    

#     return jsonify({
#         "status": "Created new branch"
#     })

# # PUT Change Branch
# @app.route("/branches/<branch_name>", methods=["PUT"])
# def switch_branch(branch_name):
#     if branch_name not in [b.name for b in repo.branches]:
#         abort(404, "Branch not found")

#     repo.git.checkout(branch_name)

#     # Maybe stash idk

#     return jsonify({
#         "status": f"Changed Branches to {branch_name}"
#     })

# # DELETE 
# @app.route("/branches/<branch_name>", methods=["DELETE"])
# def delete_branch(branch_name):
#     if branch_name == repo.active_branch.name:
#         abort(404, "Cannot delete active branch")
    
#     if branch_name not in [b.name for b in repo.branches]:
#         abort(404, "Branch doesn't exist")

#     repo.delete_head(branch_name, force=True)

#     return jsonify({
#         "status": f"deleted {branch_name}"
#     })

# STT S --------------------------------------------------
@app.route("/stt", methods=["POST"])
def stt():
    # VaRest-friendly: JSON body with base64 audio
    if not request.is_json:
        abort(400, "Request body must be JSON")

    body = request.get_json()
    audio_b64 = body.get("audio_b64")
    filename = body.get("filename", "audio.wav")

    if not audio_b64:
        abort(400, "Missing audio_b64")

    audio_bytes = base64.b64decode(audio_b64)

    f = io.BytesIO(audio_bytes)
    f.name = filename  # helps model infer format

    result = client.audio.transcriptions.create(
        model="gpt-4o-mini-transcribe",
        file=f
    )

    return jsonify({"text": result.text})
# STT E --------------------------------------------------

# OLD S --------------------------------------------------
# Get json function
# @app.route("/json/<path:path>", methods=["GET"])
# def get_json(path):
#     path = Path(path)
#     if not path.exists():
#         abort(404, "File not found")
#     with path.open("r", encoding='utf-8') as f:
#         return jsonify(json.load(f))


# @app.route("/json/<path:path>", methods=["PUT"])
# def put_json(path):
#     path = Path(path)
#     if not request.is_json:
#         abort(400, "Request body must be JSON")

#     incoming = request.get_json()                 #  changed

#     if path.exists():                             #  added
#         with path.open("r", encoding="utf-8") as f:
#             data = json.load(f)
#     else:
#         data = {}

#     data.update(incoming)                         #  added

#     path.parent.mkdir(parents=True, exist_ok=True)
#     with path.open("w", encoding="utf-8") as f:
#         json.dump(data, f, indent=2)

#     return jsonify({
#         "status": "ok",
#         "written": str(path),
#         "data": data
#     })
# OLD E --------------------------------------------------



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
