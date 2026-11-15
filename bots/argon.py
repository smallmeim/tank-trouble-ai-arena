"""ArgonVanguard: Geometry-driven ricochet sniper and potential-field tactician."""

from __future__ import annotations

import math
import random
from collections import deque
from typing import Any


def _wrap_angle(angle: float) -> float:
    """Normalize angle into [-pi, pi]."""
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def _point_to_segment_dist(
    px: float, py: float, x1: float, y1: float, x2: float, y2: float
) -> tuple[float, float]:
    """Return (min_distance, distance_along_segment) from point P to segment AB."""
    dx = x2 - x1
    dy = y2 - y1
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq <= 1e-9:
        return math.hypot(px - x1, py - y1), 0.0
    t = ((px - x1) * dx + (py - y1) * dy) / seg_len_sq
    t_clamped = max(0.0, min(1.0, t))
    proj_x = x1 + t_clamped * dx
    proj_y = y1 + t_clamped * dy
    seg_len = math.sqrt(seg_len_sq)
    return math.hypot(px - proj_x, py - proj_y), t_clamped * seg_len


class ArgonVanguardBot:
    """Ricochet sniper + CPA shell evasion + BFS powerup & combat navigator."""

    name = "Argon"
    author = "Argon (几何弹道&势场决策)"

    def __init__(self) -> None:
        self.mode: str = "Init"
        self.pos_history: deque[tuple[float, float]] = deque(maxlen=24)
        self.enemy_prev_pos: dict[int, tuple[float, float, int]] = {}
        self.enemy_vel: dict[int, tuple[float, float]] = {}
        self.unstuck_timer: int = 0
        self.unstuck_turn: int = 1
        self.mine_cooldown: int = 0
        self.strafe_dir: int = 1
        self.last_tick: int = -1

    def act(self, state: dict[str, Any]) -> tuple[int, int, int, int]:
        me = state.get("me")
        if not me or not me.get("alive", False):
            self.mode = "Offline"
            return 0, 0, 0, 0

        tick = int(state.get("tick", 0))
        arena = state.get("arena", {})
        enemies = state.get("enemies", [])
        shells = state.get("shells", [])
        powerups = state.get("powerups", [])
        mines = state.get("mines", [])
        helpers = state.get("helpers", {})

        if tick < self.last_tick:
            # New round reset
            self.pos_history.clear()
            self.enemy_prev_pos.clear()
            self.enemy_vel.clear()
            self.unstuck_timer = 0
            self.mine_cooldown = 0
        self.last_tick = tick

        if self.mine_cooldown > 0:
            self.mine_cooldown -= 1

        mx = float(me["x"])
        my = float(me["y"])
        m_angle = float(me["angle"])
        tank_r = float(arena.get("tank_radius", 16.0))
        shell_r = float(arena.get("shell_radius", 3.0))
        shell_speed = float(arena.get("shell_speed", 180.0))
        tank_speed = float(arena.get("tank_speed", 120.0))
        turn_speed = float(arena.get("turn_speed", 3.0))
        has_shield = bool(me.get("shield", False))
        laser_shots = int(me.get("laser_shots", 0))
        scatter_shots = int(me.get("scatter_shots", 0))
        mine_charges = int(me.get("mine_charges", 0))
        can_fire = bool(me.get("can_fire", True))
        lidar: list[float] = list(me.get("lidar", [200.0] * 12))

        self._update_enemy_velocities(enemies, tick, tank_speed)

        raycast = helpers.get("raycast")
        trace_bounces = helpers.get("trace_bounces")
        shortest_path = helpers.get("shortest_path")

        # ------------------------------------------------------------------
        # 1. Anti-stuck detection & recovery
        # ------------------------------------------------------------------
        self.pos_history.append((mx, my))
        if self.unstuck_timer > 0:
            self.unstuck_timer -= 1
            self.mode = "Unstuck"
            fire_now = self._check_instant_fire(
                mx, my, m_angle, tank_r, shell_r, shell_speed,
                has_shield, laser_shots, scatter_shots, can_fire,
                enemies, trace_bounces
            )
            u_move, u_turn = self._apply_collision_safety_gate(
                mx, my, m_angle, -1, self.unstuck_turn,
                tank_speed, turn_speed, lidar, enemies
            )
            return u_move, u_turn, fire_now, 0

        if len(self.pos_history) == self.pos_history.maxlen and tick % 6 == 0:
            old_x, old_y = self.pos_history[0]
            if math.hypot(mx - old_x, my - old_y) < 5.5:
                self.unstuck_timer = 10
                # Turn toward the side with greater lidar clearance
                left_space = sum(lidar[8:12])
                right_space = sum(lidar[1:5])
                self.unstuck_turn = -1 if left_space > right_space else 1
                self.pos_history.clear()
                self.mode = "Unstuck"
                u_move, u_turn = self._apply_collision_safety_gate(
                    mx, my, m_angle, -1, self.unstuck_turn,
                    tank_speed, turn_speed, lidar, enemies
                )
                return u_move, u_turn, 0, 0

        # ------------------------------------------------------------------
        # 2. Tactical mine deployment
        # ------------------------------------------------------------------
        special = 0
        if mine_charges > 0 and self.mine_cooldown == 0:
            if self._should_drop_mine(mx, my, lidar, enemies, mines):
                special = 1
                self.mine_cooldown = 45

        # ------------------------------------------------------------------
        # 3. Ballistic, mine & close-body collision threat evaluation
        # ------------------------------------------------------------------
        evade_angle, threat_urgency = self._evaluate_threats(
            mx, my, m_angle, tank_r, shell_r, has_shield,
            shells, mines, enemies, raycast
        )
        if threat_urgency > 0.0 and evade_angle is not None:
            self.mode = "Evade"
            move, turn = self._drive_toward_angle(
                m_angle, evade_angle, lidar, allow_reverse=True, urgent=True
            )
            move, turn = self._apply_collision_safety_gate(
                mx, my, m_angle, move, turn,
                tank_speed, turn_speed, lidar, enemies
            )
            fire = self._check_instant_fire(
                mx, my, m_angle, tank_r, shell_r, shell_speed,
                has_shield, laser_shots, scatter_shots, can_fire,
                enemies, trace_bounces
            )
            return move, turn, fire, special

        # ------------------------------------------------------------------
        # 4. Ricochet & direct sniping solution
        # ------------------------------------------------------------------
        fire = 0
        aim_override_angle: float | None = None
        if can_fire and enemies and callable(trace_bounces):
            fire, aim_override_angle = self._find_firing_solution(
                mx, my, m_angle, tank_r, shell_r, shell_speed,
                has_shield, laser_shots, scatter_shots, enemies, trace_bounces
            )

        # ------------------------------------------------------------------
        # 5. Navigation: Powerup collection vs Combat positioning
        # ------------------------------------------------------------------
        target_angle = self._choose_navigation_angle(
            mx, my, m_angle, has_shield, laser_shots, scatter_shots,
            lidar, enemies, powerups, mines, shortest_path, raycast
        )

        # If we found an imminent bank-shot / direct-shot angle close to current heading,
        # prioritize snapping our turret to finish the shot (unless a collision risk overrides).
        if aim_override_angle is not None:
            self.mode = "SnipeAim"
            ang_err = _wrap_angle(aim_override_angle - m_angle)
            turn = 1 if ang_err > 0.015 else (-1 if ang_err < -0.015 else 0)
            # Still translate forward/backward along navigation desire if safe
            nav_diff = abs(_wrap_angle(target_angle - m_angle))
            if nav_diff < 1.0 and lidar[0] > 42.0:
                move = 1
            elif nav_diff > 2.1 and lidar[6] > 42.0:
                move = -1
            else:
                move = 0
            move, turn = self._apply_collision_safety_gate(
                mx, my, m_angle, move, turn,
                tank_speed, turn_speed, lidar, enemies
            )
            return move, turn, fire, special

        move, turn = self._drive_toward_angle(
            m_angle, target_angle, lidar, allow_reverse=True, urgent=False
        )
        move, turn = self._apply_collision_safety_gate(
            mx, my, m_angle, move, turn,
            tank_speed, turn_speed, lidar, enemies
        )
        return move, turn, fire, special

    # ======================================================================
    # Helper methods
    # ======================================================================

    def _update_enemy_velocities(
        self, enemies: list[dict[str, Any]], tick: int, tank_speed: float
    ) -> None:
        """Track enemy positions across ticks to estimate velocity vectors."""
        active_ids: set[int] = set()
        for e in enemies:
            eid = int(e.get("id", -1))
            active_ids.add(eid)
            ex = float(e["x"])
            ey = float(e["y"])
            prev = self.enemy_prev_pos.get(eid)
            if prev is not None:
                px, py, ptick = prev
                dt = max(1, tick - ptick) / 30.0
                vx = max(-tank_speed, min(tank_speed, (ex - px) / dt))
                vy = max(-tank_speed, min(tank_speed, (ey - py) / dt))
                old_vx, old_vy = self.enemy_vel.get(eid, (vx, vy))
                self.enemy_vel[eid] = (0.6 * vx + 0.4 * old_vx, 0.6 * vy + 0.4 * old_vy)
            else:
                self.enemy_vel[eid] = (0.0, 0.0)
            self.enemy_prev_pos[eid] = (ex, ey, tick)

        for eid in list(self.enemy_prev_pos.keys()):
            if eid not in active_ids:
                self.enemy_prev_pos.pop(eid, None)
                self.enemy_vel.pop(eid, None)

    def _apply_collision_safety_gate(
        self,
        mx: float,
        my: float,
        m_angle: float,
        move: int,
        turn: int,
        tank_speed: float,
        turn_speed: float,
        lidar: list[float],
        enemies: list[dict[str, Any]],
    ) -> tuple[int, int]:
        """
        High-priority anti-collision safety gate:
        Tank-to-tank contact (dist <= 32px) kills BOTH tanks instantly regardless of shield.
        If any enemy is within 74px (or closing fast within 92px), verify that our next step
        does not bring us into collision range; otherwise override (move, turn) to separate.
        """
        if not enemies:
            return move, turn

        close_threats: list[tuple[float, float, float, float, float]] = []
        for e in enemies:
            dist = float(e.get("dist", 999.0))
            if dist > 92.0:
                continue
            eid = int(e.get("id", -1))
            ex = float(e["x"])
            ey = float(e["y"])
            e_ang = float(e.get("angle", 0.0))
            evx, evy = self.enemy_vel.get(eid, (0.0, 0.0))
            # Blend observed velocity with worst-case lunge toward us along enemy heading
            to_me_x = (mx - ex) / (dist or 1.0)
            to_me_y = (my - ey) / (dist or 1.0)
            heading_x = math.cos(e_ang)
            heading_y = math.sin(e_ang)
            align = abs(heading_x * to_me_x + heading_y * to_me_y)
            worst_vx = evx * 0.55 + to_me_x * tank_speed * (0.45 if align > 0.5 else 0.25)
            worst_vy = evy * 0.55 + to_me_y * tank_speed * (0.45 if align > 0.5 else 0.25)
            close_threats.append((ex, ey, worst_vx, worst_vy, dist))

        if not close_threats:
            return move, turn

        dt = 0.085  # ~2.5 frames lookahead

        def _min_sep_for_action(mv: int, trn: int) -> float:
            next_ang = m_angle + trn * turn_speed * dt
            step = mv * tank_speed * dt
            # Respect wall clearance so we don't assume we can phase through a wall
            if len(lidar) >= 12:
                if mv > 0 and min(lidar[0], lidar[11] * 1.1, lidar[1] * 1.1) < 22.0:
                    step = 0.0
                elif mv < 0 and min(lidar[6], lidar[5] * 1.1, lidar[7] * 1.1) < 22.0:
                    step = 0.0
            nx = mx + math.cos(next_ang) * step
            ny = my + math.sin(next_ang) * step

            worst_sep = 999.0
            for ex, ey, wvx, wvy, cur_d in close_threats:
                nex = ex + wvx * dt
                ney = ey + wvy * dt
                sep = math.hypot(nx - nex, ny - ney)
                worst_sep = min(worst_sep, sep)
            return worst_sep

        min_cur_dist = min(t[4] for t in close_threats)
        planned_sep = _min_sep_for_action(move, turn)

        # Safe if planned separation stays comfortably above 62px and isn't shrinking inside 58px
        if planned_sep >= 62.0 and (min_cur_dist > 58.0 or planned_sep >= min_cur_dist + 1.5):
            return move, turn

        # Search all (mv, trn) combinations for the action that maximizes separation
        best_mv, best_trn = move, turn
        best_score = -999.0
        for cand_mv in (-1, 1, 0):
            for cand_trn in (-1, 0, 1):
                sep = _min_sep_for_action(cand_mv, cand_trn)
                # Slight preference for keeping current turn if separation is tied
                score = sep - (0.3 if cand_trn != turn else 0.0) - (0.2 if cand_mv == 0 else 0.0)
                if score > best_score:
                    best_score = score
                    best_mv, best_trn = cand_mv, cand_trn

        self.mode = "AntiCollide"
        return best_mv, best_trn

    def _should_drop_mine(
        self,
        mx: float,
        my: float,
        lidar: list[float],
        enemies: list[dict[str, Any]],
        mines: list[dict[str, Any]],
    ) -> bool:
        """Drop mines on choke points or when an enemy is pursuing close by."""
        for m in mines:
            if float(m.get("dist", 999.0)) < 68.0:
                return False

        nearest_dist = float(enemies[0]["dist"]) if enemies else 999.0
        if nearest_dist < 40.0:
            return False

        # Case A: Enemy is chasing or pressuring in close-to-medium range
        if 42.0 <= nearest_dist <= 240.0:
            return True

        # Case B: Narrow corridor / doorway choke point
        if len(lidar) >= 12:
            left_right = lidar[3] + lidar[9]
            front_back = lidar[0] + lidar[6]
            if min(left_right, front_back) < 105.0 and nearest_dist < 420.0:
                return True

        return False

    def _evaluate_threats(
        self,
        mx: float,
        my: float,
        m_angle: float,
        tank_r: float,
        shell_r: float,
        has_shield: bool,
        shells: list[dict[str, Any]],
        mines: list[dict[str, Any]],
        enemies: list[dict[str, Any]],
        raycast: Any,
    ) -> tuple[float | None, float]:
        """Compute emergency evasion angle and urgency score (shells, mines, and ramming enemies)."""
        danger_x = 0.0
        danger_y = 0.0
        max_urgency = 0.0
        safe_radius = tank_r + shell_r + (10.0 if has_shield else 22.0)

        # 1. Incoming shells via CPA (Closest Point of Approach)
        for s in shells:
            age = float(s.get("age_sec", 1.0))
            if s.get("is_mine", False) and age < 0.22:
                continue

            sx = float(s["x"])
            sy = float(s["y"])
            vx = float(s["vx"])
            vy = float(s["vy"])
            speed_sq = vx * vx + vy * vy
            if speed_sq < 1e-6:
                continue

            rx = mx - sx
            ry = my - sy
            # Time until closest approach
            t_cpa = (rx * vx + ry * vy) / speed_sq
            if t_cpa < -0.04 or t_cpa > 1.35:
                continue

            t_clamp = max(0.0, t_cpa)
            cpa_x = sx + vx * t_clamp
            cpa_y = sy + vy * t_clamp
            miss_dist = math.hypot(mx - cpa_x, my - cpa_y)

            if miss_dist < safe_radius:
                urgency = (1.4 - t_clamp) * ((safe_radius - miss_dist) / safe_radius + 0.5)
                if has_shield:
                    urgency *= 0.25  # Shield can tank 1 shell hit, only dodge very close shots
                if urgency > 0.15:
                    # Sidestep perpendicular to shell velocity
                    speed = math.sqrt(speed_sq)
                    nx1, ny1 = -vy / speed, vx / speed
                    nx2, ny2 = vy / speed, -vx / speed

                    # Pick perpendicular direction that moves away from trajectory line
                    side_dot = rx * nx1 + ry * ny1
                    if side_dot < 0:
                        nx1, ny1, nx2, ny2 = nx2, ny2, nx1, ny1

                    # Verify wall clearance with raycast if available
                    if callable(raycast):
                        ang1 = math.atan2(ny1, nx1)
                        ang2 = math.atan2(ny2, nx2)
                        c1 = float(raycast(mx, my, ang1, 70.0))
                        c2 = float(raycast(mx, my, ang2, 70.0))
                        if c1 < 28.0 and c2 > c1 + 12.0:
                            nx1, ny1 = nx2, ny2

                    danger_x += nx1 * urgency * 2.5
                    danger_y += ny1 * urgency * 2.5
                    max_urgency = max(max_urgency, urgency)

        # 2. Nearby mines
        for m in mines:
            dist = float(m.get("dist", 999.0))
            armed = bool(m.get("armed", True))
            mine_safe_r = 64.0 if armed else 44.0
            if dist < mine_safe_r:
                urgency = (mine_safe_r - dist) / mine_safe_r * 1.8
                dx = mx - float(m["x"])
                dy = my - float(m["y"])
                d = math.hypot(dx, dy) or 1.0
                danger_x += (dx / d) * urgency * 2.0
                danger_y += (dy / d) * urgency * 2.0
                max_urgency = max(max_urgency, urgency)

        # 3. Close enemy body collision threat (Shield does NOT protect against collision!)
        collision_warn_r = 74.0
        for e in enemies:
            dist = float(e.get("dist", 999.0))
            if dist < collision_warn_r:
                eid = int(e.get("id", -1))
                ex = float(e["x"])
                ey = float(e["y"])
                evx, evy = self.enemy_vel.get(eid, (0.0, 0.0))
                # Predict slightly ahead
                dx = mx - (ex + evx * 0.08)
                dy = my - (ey + evy * 0.08)
                d = math.hypot(dx, dy) or 1.0
                ux, uy = dx / d, dy / d

                # Add slight tangential sidestep toward the side with better wall clearance
                tx1, ty1 = -uy, ux
                tx2, ty2 = uy, -ux
                if callable(raycast):
                    c1 = float(raycast(mx, my, math.atan2(ty1, tx1), 65.0))
                    c2 = float(raycast(mx, my, math.atan2(ty2, tx2), 65.0))
                    if c2 > c1:
                        tx1, ty1 = tx2, ty2

                urgency = ((collision_warn_r - dist) / (collision_warn_r - 32.0)) ** 1.35 * 2.4
                danger_x += (ux * 0.82 + tx1 * 0.35) * urgency * 2.4
                danger_y += (uy * 0.82 + ty1 * 0.35) * urgency * 2.4
                max_urgency = max(max_urgency, urgency)

        if max_urgency > 0.0 and (abs(danger_x) > 1e-4 or abs(danger_y) > 1e-4):
            return math.atan2(danger_y, danger_x), max_urgency
        return None, 0.0

    def _evaluate_shot_angle(
        self,
        mx: float,
        my: float,
        test_angle: float,
        tank_r: float,
        shell_r: float,
        shell_speed: float,
        has_shield: bool,
         is_laser: bool,
        enemies: list[dict[str, Any]],
        trace_bounces: Any,
    ) -> float:
        """
        Simulate trajectory along `test_angle` and return a score:
        < 0: unsafe (self-kill risk) or no hit
        > 0: hits an enemy (higher is faster/higher-value hit)
        """
        muzzle_dist = tank_r + shell_r + 2.0
        bx = mx + math.cos(test_angle) * muzzle_dist
        by = my + math.sin(test_angle) * muzzle_dist

        max_dist = 1100.0 if is_laser else 680.0
        max_bounces = 4 if is_laser else 2
        pts = trace_bounces(bx, by, test_angle, max_dist, max_bounces)
        if not pts or len(pts) < 2:
            return -1.0

        # Immediate wall proximity check for normal bouncy shells
        first_seg_len = math.hypot(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
        if not is_laser and not has_shield and first_seg_len < 42.0:
            return -10.0

        hit_radius = tank_r + shell_r + (3.5 if is_laser else 1.5)
        self_safe_radius = tank_r + shell_r + 8.0

        total_path_len = 0.0
        best_hit_score = -1.0

        for i in range(len(pts) - 1):
            x1, y1 = float(pts[i][0]), float(pts[i][1])
            x2, y2 = float(pts[i + 1][0]), float(pts[i + 1][1])
            seg_len = math.hypot(x2 - x1, y2 - y1)
            if seg_len <= 1e-6:
                continue

            # Check self-hit risk after first bounce
            if i >= 1 and not is_laser and not has_shield:
                self_dist, along = _point_to_segment_dist(mx, my, x1, y1, x2, y2)
                if self_dist < self_safe_radius:
                    return -10.0

            # Check intersection against enemies
            for e in enemies:
                ex = float(e["x"])
                ey = float(e["y"])
                if i == 0 and not is_laser:
                    eid = int(e.get("id", -1))
                    evx, evy = self.enemy_vel.get(eid, (0.0, 0.0))
                    approx_t = min(0.28, float(e.get("dist", 100.0)) / max(1.0, shell_speed) * 0.5)
                    ex += evx * approx_t
                    ey += evy * approx_t

                dist_to_seg, along = _point_to_segment_dist(ex, ey, x1, y1, x2, y2)
                travel_dist = total_path_len + along

                # Tighter tolerance for multi-bounce shots as enemy may move
                eff_radius = hit_radius if i == 0 else max(10.0, hit_radius - i * 2.5)
                if dist_to_seg <= eff_radius:
                    score = 120.0 - travel_dist * 0.08 - i * 12.0
                    if e.get("shield", False):
                        score *= 0.45  # Still worthwhile to strip enemy shield
                    best_hit_score = max(best_hit_score, score)

            total_path_len += seg_len
            if best_hit_score > 0.0:
                break

        return best_hit_score

    def _check_instant_fire(
        self,
        mx: float,
        my: float,
        m_angle: float,
        tank_r: float,
        shell_r: float,
        shell_speed: float,
        has_shield: bool,
        laser_shots: int,
        scatter_shots: int,
        can_fire: bool,
        enemies: list[dict[str, Any]],
        trace_bounces: Any,
    ) -> int:
        """Check if current turret angle already lines up a clean shot."""
        if not can_fire or not enemies or not callable(trace_bounces):
            return 0
        is_laser = laser_shots > 0
        score = self._evaluate_shot_angle(
            mx, my, m_angle, tank_r, shell_r, shell_speed,
            has_shield, is_laser, enemies, trace_bounces
        )
        return 1 if score > 0.0 else 0

    def _find_firing_solution(
        self,
        mx: float,
        my: float,
        m_angle: float,
        tank_r: float,
        shell_r: float,
        shell_speed: float,
        has_shield: bool,
        laser_shots: int,
        scatter_shots: int,
        enemies: list[dict[str, Any]],
        trace_bounces: Any,
    ) -> tuple[int, float | None]:
        """
        Scan current heading and nearby angles for direct or ricochet kills.
        Returns (fire_now, aim_override_angle).
        """
        is_laser = laser_shots > 0

        # 1. Check current angle right now
        cur_score = self._evaluate_shot_angle(
            mx, my, m_angle, tank_r, shell_r, shell_speed,
            has_shield, is_laser, enemies, trace_bounces
        )
        if cur_score > 0.0:
            return 1, m_angle

        # If holding scatter, also check +/- 0.16 rad spread cones
        if scatter_shots > 0:
            for spread in (-0.16, 0.16):
                sp_score = self._evaluate_shot_angle(
                    mx, my, m_angle + spread, tank_r, shell_r, shell_speed,
                    has_shield, False, enemies, trace_bounces
                )
                if sp_score > 15.0 and cur_score > -5.0:
                    return 1, m_angle

        # 2. Candidate angles: fine sweep around current heading + direct angles to enemies
        candidates: list[float] = []
        # Sweep within +/- 0.55 rad (~31 deg) for quick turret snap
        for step in range(1, 12):
            delta = step * 0.048
            candidates.append(_wrap_angle(m_angle + delta))
            candidates.append(_wrap_angle(m_angle - delta))

        # Add direct angles to closest 2 enemies and wall-reflection guesses
        for e in enemies[:2]:
            dir_ang = math.atan2(float(e["y"]) - my, float(e["x"]) - mx)
            if abs(_wrap_angle(dir_ang - m_angle)) <= 0.85:
                candidates.append(dir_ang)

        best_angle: float | None = None
        best_score = 0.0

        for ang in candidates:
            ang_diff = abs(_wrap_angle(ang - m_angle))
            score = self._evaluate_shot_angle(
                mx, my, ang, tank_r, shell_r, shell_speed,
                has_shield, is_laser, enemies, trace_bounces
            )
            if score > 0.0:
                # Penalize large turret rotation time
                adjusted = score - ang_diff * 28.0
                if adjusted > best_score:
                    best_score = adjusted
                    best_angle = ang

        if best_angle is not None:
            if abs(_wrap_angle(best_angle - m_angle)) < 0.038:
                return 1, best_angle
            return 0, best_angle

        return 0, None

    def _choose_navigation_angle(
        self,
        mx: float,
        my: float,
        m_angle: float,
        has_shield: bool,
        laser_shots: int,
        scatter_shots: int,
        lidar: list[float],
        enemies: list[dict[str, Any]],
        powerups: list[dict[str, Any]],
        mines: list[dict[str, Any]],
        shortest_path: Any,
        raycast: Any,
    ) -> float:
        """Select desired movement heading based on powerups, enemy distance, and maze BFS."""
        nearest_enemy = enemies[0] if enemies else None
        nearest_enemy_dist = float(nearest_enemy["dist"]) if nearest_enemy else 9999.0

        # 0. Emergency anti-ram spacing: never rush toward a close enemy (even around a corner)
        if nearest_enemy is not None and nearest_enemy_dist < 88.0:
            ex = float(nearest_enemy["x"])
            ey = float(nearest_enemy["y"])
            ang_to_enemy = math.atan2(ey - my, ex - mx)
            self.mode = "AntiRamKite"
            if random.random() < 0.04:
                self.strafe_dir *= -1
            return _wrap_angle(ang_to_enemy + math.pi + 0.42 * self.strafe_dir)

        # 1. Evaluate best powerup to contest (avoiding head-on collision over contested boxes)
        best_pu = None
        best_pu_val = 0.0
        weights = {
            "laser": 1.75 if laser_shots == 0 else 0.6,
            "shield": 1.65 if not has_shield else 0.4,
            "scatter": 1.35 if scatter_shots == 0 else 0.6,
            "mine": 1.15,
        }
        for pu in powerups:
            ptype = str(pu.get("type", ""))
            px, py = float(pu["x"]), float(pu["y"])
            pdist = max(25.0, float(pu.get("dist", 500.0)))
            w = weights.get(ptype, 1.0)

            # Check if any enemy is contesting this box closely or sitting between us and the box
            contested_collision_risk = False
            for e in enemies:
                edist_to_pu = math.hypot(float(e["x"]) - px, float(e["y"]) - py)
                edist_to_me = float(e.get("dist", 999.0))
                # If enemy is closer or almost equally close to a nearby powerup, don't dive in and collide
                if edist_to_pu < 88.0 and (edist_to_pu <= pdist + 26.0 or edist_to_me < 105.0):
                    contested_collision_risk = True
                    break
                # Or if the enemy lies right along our direct segment to the powerup
                seg_d, _ = _point_to_segment_dist(float(e["x"]), float(e["y"]), mx, my, px, py)
                if seg_d < 62.0 and edist_to_me < pdist + 20.0:
                    contested_collision_risk = True
                    break

            if contested_collision_risk:
                continue

            if nearest_enemy_dist < 135.0 and ptype != "shield" and pdist > 105.0:
                continue
            val = (w * 260.0) / (pdist + 40.0)
            if val > best_pu_val:
                best_pu_val = val
                best_pu = pu

        # Decide whether to pursue powerup or engage enemy
        if best_pu is not None and (best_pu_val > 0.72 or nearest_enemy is None):
            tx, ty = float(best_pu["x"]), float(best_pu["y"])
            self.mode = f"Pickup:{best_pu.get('type', 'pu')}"
            return self._path_angle_to(mx, my, tx, ty, shortest_path, lidar)

        if nearest_enemy is not None:
            ex = float(nearest_enemy["x"])
            ey = float(nearest_enemy["y"])
            has_los = bool(nearest_enemy.get("has_los", False))
            enemy_armed = bool(
                nearest_enemy.get("shield", False)
                or int(nearest_enemy.get("laser_shots", 0)) > 0
                or int(nearest_enemy.get("scatter_shots", 0)) > 0
            )
            we_armed = has_shield or laser_shots > 0 or scatter_shots > 0

            # In LOS combat spacing: strictly maintain safe standoff ring (115~165px)
            if has_los:
                ang_to_enemy = math.atan2(ey - my, ex - mx)
                if random.random() < 0.03:
                    self.strafe_dir *= -1

                if nearest_enemy_dist < 125.0 or (nearest_enemy_dist < 165.0 and enemy_armed and not has_shield):
                    # Back-kite obliquely to prevent ramming while keeping firing angles open
                    self.mode = "KiteBack"
                    return _wrap_angle(ang_to_enemy + math.pi - 0.48 * self.strafe_dir)

                if nearest_enemy_dist < 220.0:
                    # Oblique strafe around the standoff ring (never drive straight at enemy!)
                    self.mode = "CombatStrafe"
                    return _wrap_angle(ang_to_enemy + 0.72 * self.strafe_dir)

                if we_armed and not nearest_enemy.get("shield", False):
                    # Close distance only when far (>220px) and at a slight flank angle
                    self.mode = "FlankAdvance"
                    return _wrap_angle(ang_to_enemy + 0.30 * self.strafe_dir)

            # Non-LOS corner caution: if enemy is close behind a wall/corner, don't hug the corner tightly
            if nearest_enemy_dist < 118.0:
                ang_to_enemy = math.atan2(ey - my, ex - mx)
                self.mode = "CornerGuard"
                return _wrap_angle(ang_to_enemy + 0.85 * self.strafe_dir)

            # Use precomputed next_waypoint if available
            wp = nearest_enemy.get("next_waypoint")
            if isinstance(wp, (tuple, list)) and len(wp) >= 2:
                self.mode = "HuntBFS"
                return math.atan2(float(wp[1]) - my, float(wp[0]) - mx)

            self.mode = "HuntPath"
            return self._path_angle_to(mx, my, ex, ey, shortest_path, lidar)

        # Fallback: Cruise toward open lidar corridor
        self.mode = "Patrol"
        best_idx = max(range(len(lidar)), key=lambda i: lidar[i]) if lidar else 0
        return _wrap_angle(m_angle + best_idx * (math.pi / 6.0))

    def _path_angle_to(
        self,
        mx: float,
        my: float,
        tx: float,
        ty: float,
        shortest_path: Any,
        lidar: list[float],
    ) -> float:
        """Compute next waypoint angle via `shortest_path` helper."""
        if callable(shortest_path):
            try:
                path = shortest_path(mx, my, tx, ty)
                if path:
                    for wx, wy in path:
                        if math.hypot(float(wx) - mx, float(wy) - my) > 22.0:
                            return math.atan2(float(wy) - my, float(wx) - mx)
                    wx, wy = path[-1]
                    return math.atan2(float(wy) - my, float(wx) - mx)
            except Exception:
                pass
        return math.atan2(ty - my, tx - mx)

    def _drive_toward_angle(
        self,
        m_angle: float,
        target_angle: float,
        lidar: list[float],
        allow_reverse: bool = True,
        urgent: bool = False,
    ) -> tuple[int, int]:
        """
        Convert desired world heading into (move, turn) commands,
        incorporating lidar whisker wall-avoidance and bidirectional driving.
        """
        # Wall repulsion via 12-beam lidar (beam 0 = front, clockwise every 30 deg)
        desired_x = math.cos(target_angle)
        desired_y = math.sin(target_angle)

        if len(lidar) == 12:
            for i, dist in enumerate(lidar):
                thresh = 34.0 if urgent else 44.0
                if dist < thresh:
                    beam_angle = m_angle + i * (math.pi / 6.0)
                    push = ((thresh - dist) / thresh) ** 1.5 * 1.45
                    desired_x -= math.cos(beam_angle) * push
                    desired_y -= math.sin(beam_angle) * push

        steered_angle = math.atan2(desired_y, desired_x)
        diff = _wrap_angle(steered_angle - m_angle)

        front_clear = lidar[0] if len(lidar) >= 12 else 100.0
        front_left = lidar[11] if len(lidar) >= 12 else 100.0
        front_right = lidar[1] if len(lidar) >= 12 else 100.0
        back_clear = lidar[6] if len(lidar) >= 12 else 100.0

        # Use reverse gear if target heading is behind us and rear is clear
        if allow_reverse and abs(diff) > (2.05 if not urgent else 1.75) and back_clear > 34.0:
            rev_diff = _wrap_angle(steered_angle - (m_angle + math.pi))
            turn = 1 if rev_diff > 0.04 else (-1 if rev_diff < -0.04 else 0)
            return -1, turn

        turn = 1 if diff > 0.04 else (-1 if diff < -0.04 else 0)

        # Prevent ramming into walls head-on
        if min(front_clear, front_left * 1.15, front_right * 1.15) < 24.0:
            if back_clear > 30.0:
                return -1, (1 if front_left < front_right else -1)
            return 0, (1 if front_left < front_right else -1)

        move = 1 if abs(diff) < 1.35 else 0
        return move, turn
