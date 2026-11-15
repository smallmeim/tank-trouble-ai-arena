"""Local Flask bridge serving GitHub `AbyssWhalen/tank-trouble` + multi-AI Python bots (`bots/*.py`)."""

from __future__ import annotations

import argparse
import mimetypes
import os
import socket
import subprocess
import threading
import urllib.request
import webbrowser
from typing import Any

from flask import Flask, jsonify, request, send_from_directory

from bots import discover_bots, safe_run_bot
from py_maze_helpers import MazeHelper, build_bot_state

# Prevent Windows registry quirks from breaking ES Module imports (<script type="module">)
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(BASE_DIR, "src")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
BOTS_DIR = os.path.join(BASE_DIR, "bots")
PROMPT_MD = os.path.join(BASE_DIR, "PROMPT_FOR_OTHER_AI.md")

app = Flask(__name__)

_lock = threading.Lock()
_bridge_state: dict[str, Any] = {
    "round_id": -1,
    "maze": None,
    "bot_instances": {},  # (round_id, slot_idx, bot_id) -> instance
}


def _roster_payload() -> dict[str, Any]:
    entries, errors = discover_bots(BOTS_DIR)
    py_bots = [
        {
            "id": e.bot_id,
            "name": e.name,
            "file_name": e.file_name,
            "author": e.author,
            "description": e.description,
            "kind": "python",
        }
        for e in entries
    ]
    builtin = [
        {"id": "github:hard", "name": "原版AI·困难", "author": "GitHub ai.js", "kind": "builtin"},
        {"id": "github:normal", "name": "原版AI·普通", "author": "GitHub ai.js", "kind": "builtin"},
        {"id": "github:easy", "name": "原版AI·简单", "author": "GitHub ai.js", "kind": "builtin"},
        {"id": "human1", "name": "玩家1 (WASD+空格+E)", "author": "键盘操控", "kind": "human"},
        {"id": "human2", "name": "玩家2 (方向键+Enter+RShift)", "author": "键盘操控", "kind": "human"},
    ]
    return {
        "ok": True,
        "bots_dir": BOTS_DIR,
        "py_bots": py_bots,
        "builtin": builtin,
        "errors": [{"file": fn, "error": err} for fn, err in errors],
    }


def _get_or_create_bot(round_id: int, slot_idx: int, bot_id: str) -> Any | None:
    key = (round_id, slot_idx, bot_id)
    inst = _bridge_state["bot_instances"].get(key)
    if inst is not None:
        return inst
    entries, _ = discover_bots(BOTS_DIR)
    for e in entries:
        if e.bot_id == bot_id:
            inst = e.builder()
            _bridge_state["bot_instances"][key] = inst
            return inst
    return None


@app.route("/")
def root() -> Any:
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/index.html")
def index_html() -> Any:
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/src/<path:filename>")
def src_files(filename: str) -> Any:
    return send_from_directory(SRC_DIR, filename)


@app.route("/assets/<path:filename>")
def asset_files(filename: str) -> Any:
    return send_from_directory(ASSETS_DIR, filename)


@app.route("/api/bots", methods=["GET"])
@app.route("/api/reload_bots", methods=["GET", "POST"])
def api_bots() -> Any:
    return jsonify(_roster_payload())


@app.route("/api/open_bots_dir", methods=["POST"])
def api_open_bots_dir() -> Any:
    os.makedirs(BOTS_DIR, exist_ok=True)
    if os.name == "nt":
        subprocess.Popen(["explorer", BOTS_DIR])
    return jsonify({"ok": True, "path": BOTS_DIR})


@app.route("/api/prompt_guide", methods=["GET"])
def api_prompt_guide() -> Any:
    if os.path.exists(PROMPT_MD):
        with open(PROMPT_MD, "r", encoding="utf-8") as f:
            return jsonify({"ok": True, "markdown": f.read()})
    return jsonify({"ok": False, "markdown": ""})


@app.route("/api/ai_reset", methods=["POST"])
def api_ai_reset() -> Any:
    data = request.get_json(silent=True) or {}
    round_id = int(data.get("round_id", 0))
    maze_data = data.get("maze")
    with _lock:
        _bridge_state["round_id"] = round_id
        _bridge_state["bot_instances"] = {}
        if isinstance(maze_data, dict):
            _bridge_state["maze"] = MazeHelper(maze_data)
    return jsonify({"ok": True, "round_id": round_id})


@app.route("/api/ai_step", methods=["POST"])
def api_ai_step() -> Any:
    data = request.get_json(silent=True) or {}
    round_id = int(data.get("round_id", 0))
    wall_version = int(data.get("wall_version", 0))

    with _lock:
        maze: MazeHelper | None = _bridge_state.get("maze")
        if _bridge_state["round_id"] != round_id or maze is None:
            if isinstance(data.get("maze"), dict):
                _bridge_state["round_id"] = round_id
                _bridge_state["bot_instances"] = {}
                maze = MazeHelper(data["maze"])
                _bridge_state["maze"] = maze
            else:
                return jsonify({"need_maze": True, "controls": {}})

        if wall_version != maze.wall_version and isinstance(data.get("walls"), list):
            maze.update_walls(data["walls"], wall_version=wall_version, cells=data.get("cells"))

        controls: dict[str, Any] = {}
        tanks = data.get("tanks", [])
        for req in data.get("requests", []):
            slot_idx = int(req.get("slot", 0))
            bot_id = str(req.get("bot_id", ""))
            if slot_idx < 0 or slot_idx >= len(tanks) or not tanks[slot_idx].get("alive", False):
                controls[str(slot_idx)] = {"move": 0, "turn": 0, "fire": False, "special": False, "mode": "Dead"}
                continue
            bot = _get_or_create_bot(round_id, slot_idx, bot_id)
            if bot is None:
                controls[str(slot_idx)] = {"move": 0, "turn": 0, "fire": False, "special": False, "mode": "MissingBot"}
                continue
            state = build_bot_state(maze, data, slot_idx)
            controls[str(slot_idx)] = safe_run_bot(bot, state)

    return jsonify({"need_maze": False, "controls": controls})


def _is_existing_arena(port: int) -> bool:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/api/bots", timeout=0.8) as resp:
            return resp.status == 200 and b'"py_bots"' in resp.read()
    except Exception:
        return False


def _open_when_ready(port: int, url: str) -> None:
    import time

    for _ in range(50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.15)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                break
        time.sleep(0.1)
    webbrowser.open(url)


def _pick_free_port(preferred: int) -> int:
    for p in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return preferred


def main() -> None:
    parser = argparse.ArgumentParser(description="Tank Trouble GitHub Edition + Python AI Melee Bridge")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "5180")))
    parser.add_argument("--open", action="store_true", help="Automatically open browser tab.")
    args = parser.parse_args()

    if _is_existing_arena(args.port):
        url = f"http://127.0.0.1:{args.port}/"
        print(f"Tank Trouble is already running at {url}")
        if args.open:
            webbrowser.open(url)
        return

    port = _pick_free_port(args.port)
    url = f"http://127.0.0.1:{port}/"
    print(f"===================================================")
    print(f"  坦克回廊 (GitHub 版 + Python AI 小车混战) 已启动")
    print(f"  网址: {url}")
    print(f"  AI 代码目录: {BOTS_DIR}")
    print(f"===================================================")

    if args.open and not os.environ.get("TANK_NO_OPEN"):
        threading.Thread(target=_open_when_ready, args=(port, url), daemon=True).start()

    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
