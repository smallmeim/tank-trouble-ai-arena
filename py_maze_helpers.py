"""Geometry, raycast, bounce tracing, and BFS pathfinding synced to AbyssWhalen/tank-trouble."""

from __future__ import annotations

import math
from collections import deque
from typing import Any


def wrap_angle(a: float) -> float:
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def _seg_intersect_param(
    ax: float, ay: float, bx: float, by: float,
    cx: float, cy: float, dx: float, dy: float,
) -> float | None:
    """Return t in [0, 1] along segment A->B where it intersects C->D, else None."""
    rx, ry = bx - ax, by - ay
    sx, sy = dx - cx, dy - cy
    denom = rx * sy - ry * sx
    if abs(denom) < 1e-9:
        return None
    qpx, qpy = cx - ax, cy - ay
    t = (qpx * sy - qpy * sx) / denom
    u = (qpx * ry - qpy * rx) / denom
    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        return t
    return None


class MazeHelper:
    """Mirrors the JS maze (cells + destructible walls) for Python AI helpers."""

    def __init__(self, maze_data: dict[str, Any]) -> None:
        self.cols: int = int(maze_data.get("cols", 9))
        self.rows: int = int(maze_data.get("rows", 7))
        self.cell_size: float = float(maze_data.get("cellSize", 96.0))
        self.width: float = self.cols * self.cell_size
        self.height: float = self.rows * self.cell_size
        self.cells: list[list[dict[str, bool]]] = maze_data.get("cells", [])
        self.walls: list[tuple[float, float, float, float]] = []
        self.wall_dicts: list[dict[str, float]] = []
        self.wall_version: int = int(maze_data.get("wallVersion", 0))
        self._bfs_cache: dict[tuple[int, int, int, int], list[tuple[int, int]]] = {}
        self.update_walls(maze_data.get("walls", []), wall_version=self.wall_version, cells=self.cells)

    def update_walls(
        self,
        raw_walls: list[dict[str, Any]],
        wall_version: int | None = None,
        cells: list[list[dict[str, bool]]] | None = None,
    ) -> None:
        self.walls = [
            (float(w["x1"]), float(w["y1"]), float(w["x2"]), float(w["y2"]))
            for w in raw_walls
        ]
        self.wall_dicts = [
            {"x1": w[0], "y1": w[1], "x2": w[2], "y2": w[3]}
            for w in self.walls
        ]
        if cells is not None:
            self.cells = cells
        if wall_version is not None:
            self.wall_version = int(wall_version)
        self._bfs_cache.clear()

    def cell_of(self, x: float, y: float) -> tuple[int, int]:
        c = max(0, min(self.cols - 1, int(x // self.cell_size)))
        r = max(0, min(self.rows - 1, int(y // self.cell_size)))
        return c, r

    def cell_center(self, c: int, r: int) -> tuple[float, float]:
        return (c + 0.5) * self.cell_size, (r + 0.5) * self.cell_size

    def has_los(self, x0: float, y0: float, x1: float, y1: float) -> bool:
        for wx1, wy1, wx2, wy2 in self.walls:
            if _seg_intersect_param(x0, y0, x1, y1, wx1, wy1, wx2, wy2) is not None:
                return False
        return True

    def raycast(self, ox: float, oy: float, angle: float, max_dist: float = 900.0) -> float:
        ex = ox + math.cos(angle) * max_dist
        ey = oy + math.sin(angle) * max_dist
        best_t: float | None = None
        for wx1, wy1, wx2, wy2 in self.walls:
            t = _seg_intersect_param(ox, oy, ex, ey, wx1, wy1, wx2, wy2)
            if t is not None and (best_t is None or t < best_t):
                best_t = t
        return float(max_dist if best_t is None else max_dist * best_t)

    def trace_bounces(
        self,
        ox: float,
        oy: float,
        angle: float,
        max_dist: float = 600.0,
        max_bounces: int = 2,
    ) -> list[tuple[float, float]]:
        pts: list[tuple[float, float]] = [(float(ox), float(oy))]
        px, py = float(ox), float(oy)
        dx, dy = math.cos(angle), math.sin(angle)
        rem = float(max_dist)

        for seg in range(int(max_bounces) + 1):
            if rem <= 0.5:
                break
            ex = px + dx * rem
            ey = py + dy * rem
            best_t: float | None = None
            best_w: tuple[float, float, float, float] | None = None
            for w in self.walls:
                t = _seg_intersect_param(px, py, ex, ey, w[0], w[1], w[2], w[3])
                if t is not None and (best_t is None or t < best_t):
                    best_t = t
                    best_w = w
            if best_t is None or best_w is None:
                pts.append((ex, ey))
                break
            hx = px + dx * rem * best_t
            hy = py + dy * rem * best_t
            pts.append((hx, hy))
            rem -= rem * best_t
            if seg == max_bounces:
                break
            wx = best_w[2] - best_w[0]
            wy = best_w[3] - best_w[1]
            wlen = math.hypot(wx, wy) or 1.0
            nx, ny = -wy / wlen, wx / wlen
            dot = dx * nx + dy * ny
            dx -= 2.0 * dot * nx
            dy -= 2.0 * dot * ny
            px = hx + dx * 0.5
            py = hy + dy * 0.5
        return pts

    def shortest_path_cells(self, x0: float, y0: float, x1: float, y1: float) -> list[tuple[int, int]]:
        start = self.cell_of(x0, y0)
        goal = self.cell_of(x1, y1)
        if start == goal or not self.cells:
            return [start]
        key = (start[0], start[1], goal[0], goal[1])
        cached = self._bfs_cache.get(key)
        if cached is not None:
            return cached

        q = deque([start])
        parent: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
        dirs = ((0, -1, "top"), (1, 0, "right"), (0, 1, "bottom"), (-1, 0, "left"))
        while q:
            c, r = q.popleft()
            if (c, r) == goal:
                break
            cell_walls = self.cells[r][c]
            for dc, dr, wname in dirs:
                if cell_walls.get(wname, True):
                    continue
                nc, nr = c + dc, r + dr
                if 0 <= nc < self.cols and 0 <= nr < self.rows and (nc, nr) not in parent:
                    parent[(nc, nr)] = (c, r)
                    q.append((nc, nr))

        path: list[tuple[int, int]] = []
        cur: tuple[int, int] | None = goal if goal in parent else start
        while cur is not None:
            path.append(cur)
            cur = parent[cur]
        path.reverse()
        self._bfs_cache[key] = path
        return path

    def shortest_path(self, x0: float, y0: float, x1: float, y1: float) -> list[tuple[float, float]]:
        return [self.cell_center(c, r) for c, r in self.shortest_path_cells(x0, y0, x1, y1)]

    def compute_lidar(self, x: float, y: float, angle: float, max_dist: float = 360.0) -> list[float]:
        return [
            self.raycast(x, y, angle + (2.0 * math.pi * i) / 12.0, max_dist)
            for i in range(12)
        ]


def build_bot_state(
    maze: MazeHelper,
    snapshot: dict[str, Any],
    tank_index: int,
) -> dict[str, Any]:
    """Build unified Python AI state dict from AbyssWhalen live world snapshot."""
    tanks = snapshot.get("tanks", [])
    me_raw = tanks[tank_index]
    mx, my, mang = float(me_raw["x"]), float(me_raw["y"]), float(me_raw["angle"])
    bullets = snapshot.get("bullets", [])
    active_mine = sum(1 for b in bullets if int(b.get("owner", -1)) == tank_index)
    max_bullets = int(me_raw.get("maxAlive", 5))
    cd = float(me_raw.get("cooldown", 0.0))

    enemies: list[dict[str, Any]] = []
    for ek in tanks:
        eid = int(ek["id"])
        if eid == tank_index or not ek.get("alive", False):
            continue
        ex, ey = float(ek["x"]), float(ek["y"])
        dist = math.hypot(ex - mx, ey - my)
        rel = wrap_angle(math.atan2(ey - my, ex - mx) - mang)
        cells = maze.shortest_path_cells(mx, my, ex, ey)
        wp = maze.cell_center(*cells[1]) if len(cells) >= 2 else (ex, ey)
        enemies.append(
            {
                "id": eid,
                "name": str(ek.get("name", f"P{eid+1}")),
                "x": ex,
                "y": ey,
                "angle": float(ek["angle"]),
                "dist": float(dist),
                "rel_angle": float(rel),
                "maze_steps": max(0, len(cells) - 1),
                "next_waypoint": (float(wp[0]), float(wp[1])),
                "has_los": maze.has_los(mx, my, ex, ey),
                "shield": bool(ek.get("shield", False)),
                "scatter_shots": int(ek.get("scatterShots", 0)),
                "laser_shots": int(ek.get("laserShots", 0)),
                "mine_charges": int(ek.get("mineCharges", 0)),
            }
        )
    enemies.sort(key=lambda item: item["dist"])

    shells: list[dict[str, Any]] = []
    for b in bullets:
        bx, by = float(b["x"]), float(b["y"])
        owner = int(b.get("owner", -1))
        age_sec = float(b.get("age", 0.0))
        shells.append(
            {
                "owner": owner,
                "is_mine": owner == tank_index,
                "x": bx,
                "y": by,
                "vx": float(b["vx"]),
                "vy": float(b["vy"]),
                "bounces": int(b.get("bounces", 0)),
                "age": int(round(age_sec * 60.0)),
                "age_sec": age_sec,
                "dist": float(math.hypot(bx - mx, by - my)),
            }
        )
    shells.sort(key=lambda item: item["dist"])

    powerups: list[dict[str, Any]] = []
    for pw in snapshot.get("powerups", []):
        px, py = float(pw["x"]), float(pw["y"])
        powerups.append(
            {
                "type": str(pw["type"]),
                "x": px,
                "y": py,
                "dist": float(math.hypot(px - mx, py - my)),
                "rel_angle": float(wrap_angle(math.atan2(py - my, px - mx) - mang)),
            }
        )
    powerups.sort(key=lambda item: item["dist"])

    mines: list[dict[str, Any]] = []
    for mn in snapshot.get("mines", []):
        nx, ny = float(mn["x"]), float(mn["y"])
        mines.append(
            {
                "owner": int(mn.get("owner", -1)),
                "is_mine": int(mn.get("owner", -1)) == tank_index,
                "x": nx,
                "y": ny,
                "armed": bool(mn.get("armed", True)),
                "dist": float(math.hypot(nx - mx, ny - my)),
            }
        )
    mines.sort(key=lambda item: item["dist"])

    return {
        "tick": int(snapshot.get("tick", 0)),
        "max_ticks": 10000,
        "arena": {
            "width": maze.width,
            "height": maze.height,
            "cell_size": maze.cell_size,
            "cols": maze.cols,
            "rows": maze.rows,
            "tank_radius": 16.0,
            "shell_radius": 3.0,
            "shell_speed": 180.0,
            "tank_speed": 120.0,
            "turn_speed": 3.0,
            "max_bounces": 8,
            "fps": 60,
        },
        "me": {
            "id": tank_index,
            "x": mx,
            "y": my,
            "angle": mang,
            "alive": bool(me_raw.get("alive", True)),
            "fire_cd": int(round(max(0.0, cd) * 60.0)),
            "active_shells": active_mine,
            "max_active_shells": max_bullets,
            "can_fire": bool(
                me_raw.get("alive", True)
                and cd <= 0.0
                and (me_raw.get("scatterShots", 0) > 0 or me_raw.get("laserShots", 0) > 0 or active_mine < max_bullets)
            ),
            "kills": int(me_raw.get("kills", 0)),
            "shield": bool(me_raw.get("shield", False)),
            "shield_timer": float(me_raw.get("shieldTimer", 0.0)),
            "scatter_shots": int(me_raw.get("scatterShots", 0)),
            "laser_shots": int(me_raw.get("laserShots", 0)),
            "mine_charges": int(me_raw.get("mineCharges", 0)),
            "lidar": maze.compute_lidar(mx, my, mang),
        },
        "enemies": enemies,
        "shells": shells,
        "powerups": powerups,
        "mines": mines,
        "walls": maze.wall_dicts,
        "helpers": {
            "raycast": maze.raycast,
            "trace_bounces": maze.trace_bounces,
            "shortest_path": maze.shortest_path,
            "has_los": maze.has_los,
        },
    }
