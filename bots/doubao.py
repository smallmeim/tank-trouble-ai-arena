"""Wraith: evasive bank-shot hunter with powerup routing & stealth mine traps."""

from __future__ import annotations

import math
import random

TWO_PI = 2.0 * math.pi
HALF_PI = math.pi * 0.5


def _wrap(a: float) -> float:
    """Normalize an angle to (-pi, pi]."""
    return (a + math.pi) % TWO_PI - math.pi


def _seg_dist2(px: float, py: float,
               ax: float, ay: float, bx: float, by: float) -> float:
    """Squared distance from point P to segment AB."""
    vx, vy = bx - ax, by - ay
    c2 = vx * vx + vy * vy
    if c2 <= 1e-9:
        dx, dy = px - ax, py - ay
        return dx * dx + dy * dy
    t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / c2))
    dx = px - (ax + t * vx)
    dy = py - (ay + t * vy)
    return dx * dx + dy * dy


class WraithBot:
    """Hybrid tactician: dodge first, ricochet snipe, loot powerups, mine chokepoints."""

    name = "豆包"
    author = "豆包 (Wraith Hybrid)"

    # Aim offsets (rad) scanned for direct / bounce shots, ordered by urgency.
    _OFFSETS = (0.0, -0.06, 0.06, -0.12, 0.12, -0.20, 0.20, -0.30, 0.30,
                -0.44, 0.44, -0.62, 0.62, -0.85, 0.85)
    _PW_BONUS = {"shield": 70.0, "laser": 55.0, "mine": 0.0, "scatter": 0.0}
    _PW_RANGE = {"shield": 380.0, "laser": 360.0, "mine": 250.0, "scatter": 250.0}

    def __init__(self) -> None:
        self.mode = "Roam"
        self._prev_xy: tuple[float, float] | None = None
        self._stuck = 0
        self._unstick_tick = -1
        self._unstick_turn = 1
        self._mine_cd = 0
        self._aim = 0.0
        self._wander = 0.0
        self._rng = random.Random()
        # Anti-ram hysteresis: committed dodge side + its expiry tick.
        self._collision_side = 0
        self._collision_until = -1

    # ------------------------------------------------------------------ #
    # Entry point (never raises: loader also guards, but stay defensive)  #
    # ------------------------------------------------------------------ #
    def act(self, state: dict):
        try:
            return self._act(state)
        except Exception:
            return 0, 0, 0, 0

    def _act(self, state: dict) -> tuple[int, int, int]:
        me = state.get("me", {})
        if not me.get("alive", True):
            return 0, 0, 0, 0

        arena = state.get("arena", {})
        tr = float(arena.get("tank_radius", 16.0))
        sr = float(arena.get("shell_radius", 3.0))
        lidar = me.get("lidar", [9999.0] * 12)
        helpers = state.get("helpers", {})
        raycast = helpers.get("raycast", lambda x, y, a, m: 9999.0)
        trace = helpers.get("trace_bounces", lambda *a: [])
        los_fn = helpers.get("has_los", lambda *a: False)
        path_fn = helpers.get("shortest_path", lambda *a: [])

        enemies = state.get("enemies", [])
        shells = state.get("shells", [])
        mines = state.get("mines", [])
        powerups = state.get("powerups", [])
        tick = int(state.get("tick", 0))

        x, y, angle = float(me["x"]), float(me["y"]), float(me["angle"])
        shielded = bool(me.get("shield", False))

        def rc(a: float, d: float = 120.0) -> float:
            try:
                return float(raycast(x, y, a, d))
            except Exception:
                return 9999.0

        def tb(sx: float, sy: float, a: float, d: float, b: int):
            try:
                return trace(sx, sy, a, d, b)
            except Exception:
                return []

        # -------------------------------------------------------------- #
        # 1. Stuck detection / unstick routine                           #
        # -------------------------------------------------------------- #
        if self._prev_xy is not None:
            moved = math.hypot(x - self._prev_xy[0], y - self._prev_xy[1])
            if moved < 0.9:
                self._stuck += 1
            else:
                self._stuck = max(0, self._stuck - 2)
        self._prev_xy = (x, y)

        if tick < self._unstick_tick:
            self.mode = "Unstick"
            return -1, self._unstick_turn, 0, 0

        if self._stuck > 10:
            side = 1 if lidar[3] >= lidar[9] else -1
            if self._rng.random() < 0.25:
                side = -side  # break repeated corner loops
            self._unstick_turn = side
            self._unstick_tick = tick + 22
            self._stuck = 0
            self.mode = "Unstick"
            return -1, side, 0, 0

        # -------------------------------------------------------------- #
        # 1b. Vehicle collision gate (ram = mutual death, shield ignored)#
        # -------------------------------------------------------------- #
        ram = self._collision_gate(x, y, angle, tr, enemies, lidar, tick, rc)
        if ram is not None:
            self.mode = "AntiRam"
            return ram[0], ram[1], 0, 0

        # -------------------------------------------------------------- #
        # 2. Steer around armed mines (shield or not, they are cheap)    #
        # -------------------------------------------------------------- #
        for mn in mines:
            if mn.get("armed", False) and mn.get("dist", 9999.0) < 78.0:
                away = math.atan2(y - mn["y"], x - mn["x"])
                err = _wrap(away - angle)
                self.mode = "AvoidMine"
                move = 1 if lidar[0] > tr + 12.0 else -1
                return move, (1 if err > 0.1 else -1), 0, 0

        # -------------------------------------------------------------- #
        # 3. Incoming-shell evasion (skipped while shielded)             #
        # -------------------------------------------------------------- #
        if not shielded:
            danger = self._danger_shell(x, y, tr, sr, shells, tb)
            if danger is not None:
                vx, vy = danger
                sa = math.atan2(vy, vx)
                e1, e2 = sa + HALF_PI, sa - HALF_PI
                d1, d2 = rc(e1), rc(e2)
                if max(d1, d2) < 34.0:  # both sides blocked: back out
                    self.mode = "Evade"
                    return -1, (1 if lidar[3] >= lidar[9] else -1), 0, 0
                esc = e1 if d1 >= d2 else e2
                err = _wrap(esc - angle)
                turn = 1 if err > 0.1 else (-1 if err < -0.1 else 0)
                move = 1 if lidar[0] > tr + 16.0 else -1
                self.mode = "Evade"
                return move, turn, 0, 0

        # -------------------------------------------------------------- #
        # 4. Weapon decisions: direct / ricochet / scatter / laser       #
        # -------------------------------------------------------------- #
        fire = 0
        self._aim = 0.0
        front_clear = lidar[0] > 46.0
        can_fire = bool(me.get("can_fire", False))
        has_laser = me.get("laser_shots", 0) > 0
        has_scatter = me.get("scatter_shots", 0) > 0

        # Prefer unshielded targets; fall back to everyone when all shielded.
        targets = [e for e in enemies if not e.get("shield", False)] or enemies

        if can_fire and front_clear and targets:
            # Scatter: loose cone shot at a visible close foe.
            if has_scatter and enemies[0].get("has_los", False) \
                    and abs(enemies[0].get("rel_angle", 9.0)) < 0.32:
                fire = 1
                self.mode = "Scatter"
            else:
                shot_range = 900.0 if has_laser else 560.0
                max_b = 4 if has_laser else 2
                hit_r = tr + sr + 4.0
                self_r = tr + 10.0
                best = None
                for off in self._OFFSETS:
                    pts = tb(x, y, angle + off, shot_range, max_b)
                    if len(pts) < 2:
                        continue
                    self_hit = False
                    hit = False
                    for i in range(len(pts) - 1):
                        ax, ay = pts[i]
                        bx, by = pts[i + 1]
                        if i >= 1 and _seg_dist2(x, y, ax, ay, bx, by) <= self_r ** 2:
                            self_hit = True
                            break
                        if any(_seg_dist2(e["x"], e["y"], ax, ay, bx, by)
                               <= hit_r ** 2 for e in targets):
                            hit = True
                            break
                    if hit and not self_hit:
                        best = off
                        break

                if best is not None:
                    if abs(best) <= 0.07:
                        fire = 1
                        self.mode = "LaserSnipe" if has_laser else "BankFire"
                    else:
                        self._aim = best
                        self.mode = "AimBank"

        # Hold the bank angle: turn first, creep only when room ahead.
        if self._aim:
            turn = 1 if self._aim > 0 else -1
            move = 1 if lidar[0] > tr + 26.0 else 0
            return move, turn, 0, self._maybe_mine(me, enemies, lidar, tick)

        # -------------------------------------------------------------- #
        # 5. Pick a goal: nearby powerup vs nearest enemy                #
        # -------------------------------------------------------------- #
        goal = self._select_goal(me, enemies, powerups, shielded)

        if goal is None:
            # No enemies, no loot: gentle random roaming.
            if tick % 25 == 0:
                self._wander = _wrap(self._wander + self._rng.uniform(-0.9, 0.9))
            if lidar[0] < tr + 22.0:
                self.mode = "Roam"
                return -1, (1 if lidar[3] >= lidar[9] else -1), 0, 0
            err = _wrap(self._wander - angle)
            turn = 1 if err > 0.12 else (-1 if err < -0.12 else 0)
            self.mode = "Roam"
            return 1, turn, 0, 0

        gx, gy, gmode = goal

        # -------------------------------------------------------------- #
        # 6. Path-follow toward the goal                                 #
        # -------------------------------------------------------------- #
        try:
            if los_fn(x, y, gx, gy):
                desired = math.atan2(gy - y, gx - x)
            else:
                p = path_fn(x, y, gx, gy)
                if p and len(p) >= 2:
                    wx, wy = p[1]
                else:
                    wx, wy = gx, gy
                desired = math.atan2(wy - y, wx - x)
        except Exception:
            desired = math.atan2(gy - y, gx - x)

        err = _wrap(desired - angle)
        turn = 1 if err > 0.12 else (-1 if err < -0.12 else 0)
        head_on = (gmode in ("Hunt", "Ambush")
                   and enemies[0].get("has_los", False)
                   and enemies[0].get("dist", 9999.0) < 150.0
                   and abs(err) < 0.4)
        if lidar[0] < tr + 16.0:
            move = -1
        elif head_on:
            # Keep the gun lined up while opening the gap (cut-angle kite).
            move = -1 if lidar[6] > tr + 16.0 else 0
        else:
            move = 1
        self.mode = gmode
        return move, turn, fire, self._maybe_mine(me, enemies, lidar, tick)

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #
    def _collision_gate(self, x: float, y: float, angle: float, tr: float,
                        enemies: list, lidar: list, tick: int, rc):
        """Emergency anti-ram gate. Return (move, turn) or None.

        Triggers at <=72 px (well before the 32 px lethal contact) and uses
        relative-velocity closure time so a head-on rush is caught early.
        """
        threat = None
        for e in enemies:
            d = e.get("dist", 9999.0)
            if d > 72.0:
                continue
            bear = _wrap(math.atan2(e["y"] - y, e["x"] - x) - angle)
            # Relative velocity under the forward-drive assumption (120 px/s).
            evx = 120.0 * math.cos(e["angle"])
            evy = 120.0 * math.sin(e["angle"])
            mvx = 120.0 * math.cos(angle)
            mvy = 120.0 * math.sin(angle)
            rvx, rvy = evx - mvx, evy - mvy
            closing = True
            rr2 = rvx * rvx + rvy * rvy
            if rr2 > 1e-9:
                rx, ry = e["x"] - x, e["y"] - y
                tc = (rx * rvx + ry * rvy) / rr2  # >0 iff closing
                closing = tc > 0.0
            if abs(bear) < 1.25 and (closing or d < 52.0):
                threat = (d, bear)
                break

        if threat is None:
            self._collision_side = 0
            return None

        d, bear = threat

        # Commit one dodge side for several frames (no flip-flop at corners).
        if tick >= self._collision_until or self._collision_side == 0:
            open_right = rc(angle + HALF_PI, 110.0)
            open_left = rc(angle - HALF_PI, 110.0)
            self._collision_side = 1 if open_right >= open_left else -1
            self._collision_until = tick + 12

        if abs(bear) >= 1.0:
            # Foe abeam/behind: punch forward, turn away from it.
            return 1, (1 if bear < 0.0 else -1)

        # Foe ahead: side-slip; back-pedal when nose-to-nose or wall ahead.
        if lidar[0] < tr + 20.0 or (abs(bear) < 0.45 and d < 60.0):
            return -1, self._collision_side
        return 1, self._collision_side

    def _danger_shell(self, x: float, y: float, tr: float, sr: float,
                      shells: list, tb) -> tuple[float, float] | None:
        """Return shell velocity vector if it is on a collision course with me."""
        danger_r = tr + 22.0
        for s in shells:
            if s.get("dist", 9999.0) > 230.0:
                continue
            if s.get("is_mine", False) and s.get("age_sec", 1.0) < 0.35:
                continue
            vx, vy = float(s["vx"]), float(s["vy"])
            sp = math.hypot(vx, vy)
            if sp < 1e-6:
                continue
            rx, ry = x - s["x"], y - s["y"]
            # t > 0 iff the shell is approaching (r . v > 0).
            t = (rx * vx + ry * vy) / (sp * sp)
            if t < 0.0:
                continue  # already moving away
            cx, cy = s["x"] + vx * t, s["y"] + vy * t
            if math.hypot(x - cx, y - cy) < danger_r:
                return vx, vy
            # One-bounce prediction: shell may ricochet into me.
            pts = tb(s["x"], s["y"], math.atan2(vy, vx), 230.0, 1)
            for i in range(len(pts) - 1):
                if _seg_dist2(x, y, pts[i][0], pts[i][1],
                              pts[i + 1][0], pts[i + 1][1]) <= danger_r ** 2:
                    return vx, vy
        return None

    def _select_goal(self, me: dict, enemies: list, powerups: list,
                     shielded: bool):
        """Return (gx, gy, mode) for the best powerup or enemy, else None."""
        best_pw = None
        best_score = float("inf")
        for pw in powerups:
            typ = pw.get("type", "")
            d = pw.get("dist", 9999.0)
            if typ == "shield" and shielded:
                continue
            if typ == "laser" and me.get("laser_shots", 0) >= 2:
                continue
            if typ == "mine" and me.get("mine_charges", 0) >= 2:
                continue
            if typ == "scatter" and me.get("scatter_shots", 0) >= 2:
                continue
            if d >= self._PW_RANGE.get(typ, 0.0):
                continue
            score = d - self._PW_BONUS.get(typ, 0.0)
            if score < best_score:
                best_score = score
                best_pw = pw

        if best_pw is not None:
            my_d = best_pw["dist"]
            # Abandon the crate if any foe is as close to it as we are:
            # racing the last metres risks a mutual ram with no score.
            contested = any(
                math.hypot(e["x"] - best_pw["x"], e["y"] - best_pw["y"])
                < my_d + 20.0 for e in enemies
            )
            near_enemy = enemies[0]["dist"] if enemies else float("inf")
            if not contested and my_d < near_enemy * 1.1 + 40.0:
                return best_pw["x"], best_pw["y"], "Seek:" + best_pw["type"]

        if enemies:
            # Ambush = hold a cut angle / bank shot instead of face-tanking.
            mode = "Ambush" if best_pw is not None else "Hunt"
            return enemies[0]["x"], enemies[0]["y"], mode
        return None

    def _maybe_mine(self, me: dict, enemies: list, lidar: list, tick: int) -> int:
        """Drop a stealth mine at a junction while a foe is pressing close."""
        self._mine_cd = max(0, self._mine_cd - 1)
        if me.get("mine_charges", 0) <= 0 or self._mine_cd > 0 or not enemies:
            return 0
        foe = enemies[0]
        junction = sum(1 for idx in (0, 3, 9) if lidar[idx] > 70.0) >= 2
        on_tail = foe.get("dist", 9999.0) < 190.0 and \
            abs(foe.get("rel_angle", 0.0)) > 1.1
        if (junction and foe.get("dist", 9999.0) < 260.0) or on_tail:
            self._mine_cd = 120
            return 1
        return 0
