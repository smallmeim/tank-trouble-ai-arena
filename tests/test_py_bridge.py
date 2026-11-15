"""Unit tests for bots/loader.py, py_maze_helpers.py, and Flask server.py."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from bots.loader import discover_bots, safe_run_bot  # noqa: E402
from py_maze_helpers import MazeHelper  # noqa: E402
import server  # noqa: E402


def _make_sample_maze(break_middle_wall: bool = False) -> dict:
    """Build a 3x2 cell maze (96px cells) with a single vertical divider at x=96, y=0..96."""
    cols, rows, cs = 3, 2, 96.0
    cells = [
        [{"top": r == 0, "bottom": r == rows - 1, "left": c == 0, "right": c == cols - 1} for c in range(cols)]
        for r in range(rows)
    ]
    walls = [
        {"x1": 0, "y1": 0, "x2": cols * cs, "y2": 0},
        {"x1": 0, "y1": rows * cs, "x2": cols * cs, "y2": rows * cs},
        {"x1": 0, "y1": 0, "x2": 0, "y2": rows * cs},
        {"x1": cols * cs, "y1": 0, "x2": cols * cs, "y2": rows * cs},
    ]
    if not break_middle_wall:
        cells[0][0]["right"] = True
        cells[0][1]["left"] = True
        walls.append({"x1": 96, "y1": 0, "x2": 96, "y2": 96})
    return {
        "cols": cols,
        "rows": rows,
        "cellSize": cs,
        "wallVersion": 2 if break_middle_wall else 1,
        "cells": cells,
        "walls": walls,
    }


class TestBotLoader(unittest.TestCase):
    def test_discover_real_contestant_bots(self) -> None:
        entries, errors = discover_bots()
        self.assertEqual(errors, [])
        by_id = {e.bot_id: e.name for e in entries}
        self.assertEqual(
            by_id,
            {
                "py:6astra": "6Astra",
                "py:6_1_sol": "6.1 Sol",
                "py:argon": "Argon",
                "py:deepseek": "DeepSeek",
                "py:doubao": "豆包",
                "py:opus_5_5": "Opus 5.5",
            },
        )

    def test_discover_mixed_and_broken_bots_in_temp_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdir = Path(tmp)
            (tdir / "good_cls.py").write_text(
                "class GoodBot:\n"
                "    name = 'ClassTank'\n"
                "    def act(self, state):\n"
                "        return (1, -1, 1, 0)\n",
                encoding="utf-8",
            )
            (tdir / "good_fn.py").write_text(
                "BOT_NAME = 'FuncTank'\n"
                "def act(state):\n"
                "    return {'move': -0.8, 'turn': 0.1, 'fire': False, 'special': True}\n",
                encoding="utf-8",
            )
            (tdir / "broken_bot.py").write_text("def oops(:\n", encoding="utf-8")
            (tdir / "_ignored.py").write_text("raise RuntimeError('should skip')\n", encoding="utf-8")

            entries, errors = discover_bots(tdir)
            self.assertEqual({e.bot_id for e in entries}, {"py:good_cls", "py:good_fn"})
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0][0], "broken_bot.py")

            by_id = {e.bot_id: e for e in entries}
            cls_res = safe_run_bot(by_id["py:good_cls"].builder(), {})
            self.assertEqual((cls_res["move"], cls_res["turn"], cls_res["fire"], cls_res["special"]), (1, -1, True, False))
            self.assertEqual(cls_res["error"], "")

            fn_res = safe_run_bot(by_id["py:good_fn"].builder(), {})
            self.assertEqual((fn_res["move"], fn_res["turn"], fn_res["fire"], fn_res["special"]), (-1, 0, False, True))
            self.assertEqual(fn_res["error"], "")

    def test_safe_run_bot_catches_runtime_exception(self) -> None:
        class CrashBot:
            def act(self, state):
                return 1 / 0

        res = safe_run_bot(CrashBot(), {})
        self.assertEqual(res["move"], 0)
        self.assertEqual(res["turn"], 0)
        self.assertFalse(res["fire"])
        self.assertFalse(res["special"])
        self.assertIn("ZeroDivisionError", res["error"])


class TestMazeHelper(unittest.TestCase):
    def test_los_raycast_bounce_and_wall_destruction(self) -> None:
        maze = MazeHelper(_make_sample_maze(break_middle_wall=False))
        self.assertFalse(maze.has_los(48, 48, 144, 48))
        self.assertTrue(maze.has_los(48, 144, 144, 144))

        dist = maze.raycast(48, 48, 0.0, 400.0)
        self.assertAlmostEqual(dist, 48.0, places=3)
        self.assertAlmostEqual(maze.raycast(48, 144, 0.0, 900.0), 240.0, places=3)

        # Shoot diagonal at vertical wall x=96 -> should reflect back leftwards
        import math

        pts = maze.trace_bounces(48, 24, math.pi / 4, max_dist=300.0, max_bounces=1)
        self.assertEqual(len(pts), 3)
        self.assertAlmostEqual(pts[1][0], 96.0, places=2)
        self.assertLess(pts[2][0], pts[1][0])

        # Shortest path must detour via bottom row when (0,0)->(1,0) wall is intact
        detour = maze.shortest_path_cells(48, 48, 144, 48)
        self.assertEqual(detour, [(0, 0), (0, 1), (1, 1), (1, 0)])

        # Break middle wall and verify cache invalidates + direct path & LOS open up
        broken = _make_sample_maze(break_middle_wall=True)
        maze.update_walls(broken["walls"], wall_version=2, cells=broken["cells"])
        self.assertTrue(maze.has_los(48, 48, 144, 48))
        direct = maze.shortest_path_cells(48, 48, 144, 48)
        self.assertEqual(direct, [(0, 0), (1, 0)])


class TestFlaskServer(unittest.TestCase):
    def setUp(self) -> None:
        self.client = server.app.test_client()

    def test_static_and_discovery_routes(self) -> None:
        r_idx = self.client.get("/")
        self.assertEqual(r_idx.status_code, 200)
        html = r_idx.get_data(as_text=True)
        self.assertIn('id="py-arena-ui"', html)
        self.assertIn('id="py-cricket-btn"', html)
        self.assertIn('id="py-speed-btn"', html)
        self.assertIn('id="py-respawn-input"', html)
        self.assertIn('id="py-respawn-dec"', html)
        self.assertIn('id="py-respawn-inc"', html)
        self.assertIn('id="game-canvas"', html)

        r_js = self.client.get("/src/py_bot_bridge.js")
        self.assertEqual(r_js.status_code, 200)
        self.assertIn("javascript", r_js.content_type)
        js_txt = r_js.get_data(as_text=True)
        self.assertIn("onStartCricket", js_txt)
        self.assertIn("onChangeRespawn", js_txt)
        self.assertIn("normalizeRespawnDelay", js_txt)
        self.assertIn("buildAllBotsPayload", js_txt)
        self.assertIn("invulnTimer", js_txt)

        r_cricket = self.client.get("/src/cricket.js")
        self.assertEqual(r_cricket.status_code, 200)
        self.assertIn("javascript", r_cricket.content_type)

        r_bots = self.client.get("/api/bots")
        self.assertEqual(r_bots.status_code, 200)
        data = r_bots.get_json()
        self.assertTrue(data["ok"])
        self.assertGreaterEqual(len(data["py_bots"]), 6)
        self.assertGreaterEqual(len(data["builtin"]), 5)

        r_prompt = self.client.get("/api/prompt_guide")
        self.assertEqual(r_prompt.status_code, 200)
        pdata = r_prompt.get_json()
        self.assertTrue(pdata["ok"])
        self.assertIn("def act(self, state", pdata["markdown"])
        self.assertIn(r"C:\Users\24718\.gemini\antigravity\scratch\tank-trouble-github\bots", pdata["markdown"])

    def test_ai_reset_and_step_all_contestant_bots_and_wall_update(self) -> None:
        # Step with uninitialized round should request maze sync
        r_need = self.client.post("/api/ai_step", json={"round_id": 999, "wall_version": 1, "tanks": [], "requests": []})
        self.assertEqual(r_need.status_code, 200)
        self.assertTrue(r_need.get_json()["need_maze"])

        maze0 = _make_sample_maze(break_middle_wall=False)
        r_reset = self.client.post("/api/ai_reset", json={"round_id": 7, "maze": maze0})
        self.assertEqual(r_reset.status_code, 200)
        self.assertTrue(r_reset.get_json()["ok"])

        bots = [
            "py:6astra",
            "py:opus_5_5",
            "py:deepseek",
            "py:6_1_sol",
            "py:doubao",
            "py:argon",
        ]
        tanks = [
            {"id": 0, "name": "6Astra", "x": 48, "y": 48, "angle": 0.0, "alive": True, "cooldown": 0.0, "maxAlive": 5, "shield": False, "scatterShots": 0, "laserShots": 1, "mineCharges": 0},
            {"id": 1, "name": "Opus 5.5", "x": 144, "y": 48, "angle": 3.1, "alive": True, "cooldown": 0.2, "maxAlive": 5, "shield": False, "scatterShots": 0, "laserShots": 0, "mineCharges": 0},
            {"id": 2, "name": "DeepSeek", "x": 240, "y": 144, "angle": -2.5, "alive": True, "cooldown": 0.0, "maxAlive": 5, "shield": True, "scatterShots": 2, "laserShots": 0, "mineCharges": 0},
            {"id": 3, "name": "6.1 Sol", "x": 48, "y": 144, "angle": -0.3, "alive": True, "cooldown": 0.0, "maxAlive": 5, "shield": False, "scatterShots": 0, "laserShots": 0, "mineCharges": 2},
            {"id": 4, "name": "豆包", "x": 144, "y": 144, "angle": 1.2, "alive": True, "cooldown": 0.0, "maxAlive": 5, "shield": False, "scatterShots": 1, "laserShots": 0, "mineCharges": 0},
            {"id": 5, "name": "Argon", "x": 240, "y": 48, "angle": -1.5, "alive": True, "cooldown": 0.0, "maxAlive": 5, "shield": False, "scatterShots": 0, "laserShots": 0, "mineCharges": 1},
        ]
        requests = [{"slot": i, "bot_id": bots[i]} for i in range(len(bots))]

        for tick in (1, 2):
            payload = {
                "round_id": 7,
                "wall_version": 1,
                "tick": tick,
                "tanks": tanks,
                "bullets": [{"owner": 1, "x": 110, "y": 48, "vx": -180, "vy": 0, "bounces": 0, "age": 0.3}],
                "powerups": [{"type": "laser", "x": 144, "y": 144}],
                "mines": [{"owner": 3, "x": 60, "y": 130, "armed": True}],
                "requests": requests,
            }
            resp = self.client.post("/api/ai_step", json=payload)
            self.assertEqual(resp.status_code, 200)
            body = resp.get_json()
            self.assertFalse(body["need_maze"])
            for idx in range(len(bots)):
                ctrl = body["controls"][str(idx)]
                self.assertIn(ctrl["move"], (-1, 0, 1))
                self.assertIn(ctrl["turn"], (-1, 0, 1))
                self.assertIsInstance(ctrl["fire"], bool)
                self.assertIsInstance(ctrl["special"], bool)
                self.assertEqual(ctrl["error"], "")

        # Now send broken-wall update on tick 3
        broken_maze = _make_sample_maze(break_middle_wall=True)
        resp3 = self.client.post(
            "/api/ai_step",
            json={
                "round_id": 7,
                "wall_version": 2,
                "walls": broken_maze["walls"],
                "cells": broken_maze["cells"],
                "tick": 3,
                "tanks": tanks,
                "bullets": [],
                "powerups": [],
                "mines": [],
                "requests": requests,
            },
        )
        self.assertEqual(resp3.status_code, 200)
        body3 = resp3.get_json()
        self.assertFalse(body3["need_maze"])
        for idx in range(len(bots)):
            self.assertEqual(body3["controls"][str(idx)]["error"], "")


if __name__ == "__main__":
    unittest.main()
