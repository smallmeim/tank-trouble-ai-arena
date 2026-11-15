"""Mobile ricochet hunter that prioritizes safe shots and survival."""

from __future__ import annotations

import math


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def _segment_distance2(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 <= 1e-9:
        return (px - ax) ** 2 + (py - ay) ** 2
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2


class CodexHarrier:
    """Dodges threats, collects useful powerups, and takes safe bank shots."""

    name = "6.1 Sol"
    author = "6.1 Sol (Harrier / Mobile Ricochet Hunter)"

    def __init__(self) -> None:
        self._last_xy: tuple[float, float] | None = None
        self._stuck = 0

    def act(self, state: dict) -> tuple[int, int, int, int]:
        try:
            return self._act(state)
        except Exception:
            # A malformed optional field should never disable the bot for a frame.
            return 0, 0, 0, 0

    def _act(self, state: dict) -> tuple[int, int, int, int]:
        me = state["me"]
        arena = state["arena"]
        x, y, angle = me["x"], me["y"], me["angle"]
        enemies = state.get("enemies", [])
        lidar = me.get("lidar", [0.0] * 12)
        tank_r = arena.get("tank_radius", 16.0)
        shell_r = arena.get("shell_radius", 3.0)
        helpers = state.get("helpers", {})
        raycast = helpers.get("raycast")
        trace = helpers.get("trace_bounces")

        if self._last_xy is not None and math.hypot(x - self._last_xy[0], y - self._last_xy[1]) < 0.8:
            self._stuck += 1
        else:
            self._stuck = max(0, self._stuck - 2)
        self._last_xy = (x, y)

        # Predict short-range body collisions before aiming, collecting, or dodging shells.
        # Shields do not protect against tank-to-tank impacts.
        close_enemies = [e for e in enemies if e.get("dist", 1e9) < 86.0]
        if close_enemies:
            dt = 0.05
            horizon_steps = 6
            turn_speed = arena.get("turn_speed", 3.0)
            tank_speed = arena.get("tank_speed", 120.0)
            best_action = (0, 0)
            best_score = -1e9
            for move_candidate in (-1, 0, 1):
                for turn_candidate in (-1, 0, 1):
                    px, py, pa = x, y, angle
                    min_separation = float("inf")
                    for step in range(1, horizon_steps + 1):
                        pa += turn_candidate * turn_speed * dt
                        px += move_candidate * tank_speed * math.cos(pa) * dt
                        py += move_candidate * tank_speed * math.sin(pa) * dt
                        elapsed = step * dt
                        for enemy in close_enemies:
                            ex, ey = enemy["x"], enemy["y"]
                            toward_x, toward_y = x - ex, y - ey
                            toward_len = max(1.0, math.hypot(toward_x, toward_y))
                            enemy_facing_us = ((math.cos(enemy["angle"]) * toward_x
                                                + math.sin(enemy["angle"]) * toward_y) / toward_len)
                            enemy_speed = tank_speed if enemy_facing_us > 0.15 else 0.0
                            ex += enemy_speed * math.cos(enemy["angle"]) * elapsed
                            ey += enemy_speed * math.sin(enemy["angle"]) * elapsed
                            separation = math.hypot(px - ex, py - ey)
                            min_separation = min(min_separation, separation)

                    # Avoid choosing a mathematically safe path that immediately drives into a wall.
                    relative_heading = _wrap(pa - angle + (math.pi if move_candidate < 0 else 0.0))
                    lidar_index = int(round(relative_heading / (math.pi / 6.0))) % 12
                    clearance = lidar[lidar_index] if move_candidate else float("inf")
                    wall_penalty = max(0.0, tank_r + 22.0 - clearance) * 2.0
                    end_separation = min(math.hypot(px - e["x"], py - e["y"]) for e in close_enemies)
                    score = min_separation + 0.25 * end_separation - wall_penalty
                    if score > best_score:
                        best_score = score
                        best_action = (move_candidate, turn_candidate)

            self.mode = "AvoidTank"
            return best_action[0], best_action[1], 0, 0

        # Back out of corners before resuming navigation.
        if self._stuck > 12:
            turn = 1 if lidar[3] >= lidar[9] else -1
            if self._stuck > 26:
                self._stuck = 0
            self.mode = "Escape"
            return -1, turn, 0, 0

        # Avoid armed mines and shells whose projected path crosses the tank.
        if not me.get("shield", False):
            for mine in state.get("mines", []):
                if mine.get("armed") and mine.get("dist", 1e9) < tank_r + 58.0:
                    away = math.atan2(y - mine["y"], x - mine["x"])
                    err = _wrap(away - angle)
                    self.mode = "DodgeMine"
                    return (-1 if lidar[6] > tank_r + 10 else 1), (1 if err >= 0 else -1), 0, 0

            for shell in state.get("shells", []):
                if shell.get("is_mine") and shell.get("age_sec", 0.0) < 0.35:
                    continue
                if shell.get("dist", 1e9) > 260.0:
                    continue
                speed = math.hypot(shell.get("vx", 0.0), shell.get("vy", 0.0))
                if speed < 1.0 or trace is None:
                    continue
                try:
                    points = trace(shell["x"], shell["y"], math.atan2(shell["vy"], shell["vx"]), min(300.0, speed * 1.35), 2)
                except Exception:
                    continue
                danger2 = (tank_r + shell_r + 17.0) ** 2
                for i in range(len(points) - 1):
                    ax, ay = points[i]
                    bx, by = points[i + 1]
                    if _segment_distance2(x, y, ax, ay, bx, by) <= danger2:
                        dx, dy = bx - ax, by - ay
                        options = (math.atan2(-dx, dy), math.atan2(dx, -dy))
                        chosen = max(options, key=lambda a: raycast(x, y, a, 100.0) if raycast else 100.0)
                        err = _wrap(chosen - angle)
                        self.mode = "DodgeShell"
                        return (1 if lidar[0] > tank_r + 14 else -1), (1 if err > 0.08 else (-1 if err < -0.08 else 0)), 0, 0

        # Choose a useful firing angle by tracing straight and bank-shot paths.
        fire = 0
        aim_error = None
        if me.get("can_fire") and trace is not None and enemies:
            laser = me.get("laser_shots", 0) > 0
            shot_range = 720.0 if laser else 460.0
            max_bounces = 4 if laser else 2
            hit_r2 = (tank_r + shell_r + 9.0) ** 2
            self_r2 = (tank_r + shell_r + 10.0) ** 2
            best = None
            for offset in (0.0, -0.10, 0.10, -0.23, 0.23, -0.43, 0.43, -0.68, 0.68, -0.95, 0.95):
                shot_angle = angle + offset
                if raycast and raycast(x, y, shot_angle, tank_r + shell_r + 18.0) <= tank_r + shell_r + 8.0:
                    continue
                try:
                    points = trace(x, y, shot_angle, shot_range, max_bounces)
                except Exception:
                    continue
                self_hit = False
                hit_target = None
                for i in range(len(points) - 1):
                    ax, ay = points[i]
                    bx, by = points[i + 1]
                    if i > 0 and _segment_distance2(x, y, ax, ay, bx, by) <= self_r2:
                        self_hit = True
                        break
                    for enemy in enemies:
                        if _segment_distance2(enemy["x"], enemy["y"], ax, ay, bx, by) <= hit_r2:
                            hit_target = enemy
                            break
                    if hit_target is not None:
                        break
                if hit_target is not None and not self_hit:
                    score = abs(offset) + hit_target.get("dist", 9999.0) * 0.0001
                    if best is None or score < best[0]:
                        best = score, offset
            if best is not None:
                aim_error = best[1]
                if abs(aim_error) <= 0.055:
                    fire = 1
                    aim_error = None
                    self.mode = "LaserShot" if laser else "BankShot"
                else:
                    self.mode = "AimShot"

        # Drop a mine when a nearby enemy can plausibly run into it.
        special = int(me.get("mine_charges", 0) > 0 and bool(enemies) and enemies[0].get("dist", 1e9) < 145.0)
        if aim_error is not None:
            turn = 1 if aim_error > 0 else -1
            return (1 if lidar[0] > tank_r + 25 else 0), turn, fire, special

        # Head for the nearest enemy, or a high-value nearby pickup while searching.
        target_x = target_y = None
        if enemies:
            enemy = enemies[0]
            if enemy.get("has_los"):
                target_x, target_y = enemy["x"], enemy["y"]
            else:
                waypoint = enemy.get("next_waypoint")
                if waypoint:
                    target_x, target_y = waypoint

        powerups = state.get("powerups", [])
        wants_shield = not me.get("shield", False)
        wants_laser = me.get("laser_shots", 0) <= 0
        if powerups and (not enemies or enemies[0].get("dist", 1e9) > 250.0):
            weights = {"shield": 1.7 if wants_shield else 0.35, "laser": 1.6 if wants_laser else 0.45,
                       "scatter": 0.9 if me.get("scatter_shots", 0) <= 0 else 0.45, "mine": 0.55}
            pickup = min(powerups, key=lambda p: p.get("dist", 1e9) / weights.get(p.get("type"), 0.5))
            target_x, target_y = pickup["x"], pickup["y"]

        if target_x is None:
            self.mode = "Search"
            turn = 1 if lidar[2] >= lidar[10] else -1
            return (1 if lidar[0] > tank_r + 18 else -1), turn, fire, special

        desired = math.atan2(target_y - y, target_x - x)
        err = _wrap(desired - angle)
        turn = 1 if err > 0.13 else (-1 if err < -0.13 else 0)
        if lidar[0] < tank_r + 17:
            turn = 1 if lidar[3] >= lidar[9] else -1
            move = -1 if abs(err) > 0.8 and lidar[6] > tank_r + 12 else 0
        elif enemies and enemies[0].get("has_los") and enemies[0].get("dist", 1e9) < 115.0:
            move = 0
        else:
            move = 1
        self.mode = "Hunt"
        return move, turn, fire, special
