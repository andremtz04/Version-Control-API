# JSON structure
```JSON
{
  "metadata": {
    "pipline_State": "PreViz",
    "role": "Director",
    "timestamp": "2026-03-01T18:05:40.295563+00:00"
  },
  "data": {
    "ShotVersion": "V1",
    "Role": "Director",
    "Stage": "PreViz",
    "Actors": []
  }
}
```

# GET json
```bash
GET /projects/<project>/<scene>/<shot>/<file>
```
Returns: full JSON file

## PUT commit
```bash 
PUT /projects/<project>/<scene>/<shot>/<file>
```
Returns: Commits changes to the selected file

Also creates a cache of the preivous 5 versions in rotation with 5 being the oldest and 1 being the newest. 
- Director.json -> Director_1.json
- Director_1.json -> Director_2.json
- ...

## POST rollback
```bash
POST /projects/<project>/<scene>/<shot>/<file>/rollback?version=<1-5>
```

Changes the current version to the selected previous version

## GET history
```bash
GET /projects/<project>/<scene>/<shot>/<role>/history
```
Reutrns: Git history of the selected file