"""Claude AI: Vanguard — velocity-lead shots, powerup routing, corner mine traps."""

from __future__ import annotations
import math


def _wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def _seg2(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    """Squared min-distance from point to segment."""
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    c2 = vx * vx + vy * vy
    if c2 <= 1e-8:
        return wx * wx + wy * wy
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / c2))
    dx, dy = px - (ax + t * vx), py - (ay + t * vy)
    return dx * dx + dy * dy


class VanguardBot:
    """Tracks enemy velocity for lead shots; routes to powerups; lays corner mines."""

    name = "Opus 5.5"
    author = "Claude Opus 5.5 (Vanguard)"

    def __init__(self) -> None:
        self.mode = "Hunt"
        self._last_xy: tuple | None = None
        self._stuck = 0
        self._ehist: dict = {}  # enemy id -> (x, y) prev
        self._evel: dict = {}   # enemy id -> (vx, vy) px/tick, EMA

    def act(self, state: dict) -> tuple:
        try:
            return self._act(state)
        except Exception:
            return 0, 0, 0, 0

    def _act(self, state: dict) -> tuple:  # noqa: C901
        me = state["me"]
        enemies = state.get("enemies") or []
        arena = state["arena"]
        H = state["helpers"]
        tr, sr = arena["tank_radius"], arena["shell_radius"]
        lidar = me["lidar"]

        # --- Stuck detection & escape ---
        if self._last_xy is not None:
            d = math.hypot(me["x"] - self._last_xy[0], me["y"] - self._last_xy[1])
            self._stuck = self._stuck + 1 if d < 0.8 else max(0, self._stuck - 2)
        self._last_xy = (me["x"], me["y"])
        if self._stuck > 12:
            self.mode = "Unstick"
            t = 1 if lidar[3] >= lidar[9] else -1
            if self._stuck > 24:
                self._stuck = 0
            return -1, t, 0, 0

        tb = H["trace_bounces"]
        rc = H["raycast"]  # noqa: F841
        sp = H.get("shortest_path")

        # --- Track enemy velocity (EMA, px/tick) ---
        for e in enemies:
            eid = e["id"]
            if eid in self._ehist:
                ox, oy = self._ehist[eid]
                pvx, pvy = self._evel.get(eid, (0.0, 0.0))
                self._evel[eid] = (0.7*pvx + 0.3*(e["x"]-ox), 0.7*pvy + 0.3*(e["y"]-oy))
            self._ehist[eid] = (e["x"], e["y"])

        # --- PRIORITY 0: LETHAL tank-collision avoidance --------------------------
        # New rule: dist <= 2*tr (32 px) → both die instantly, shield ignored.
        # At max closing speed 240 px/s, 30 Hz → ~8 px/frame.  Start at 68 px
        # (~4-5 frames of response), emergency reverse at 42 px.
        _SAFE, _CRIT = 68.0, 42.0
        for _en in enemies:
            if _en["dist"] > _SAFE:
                continue
            self.mode = "AntiCrash"
            _ang_to = math.atan2(_en["y"] - me["y"], _en["x"] - me["x"])
            _facing = abs(_wrap(_ang_to - me["angle"]))  # 0=facing them, pi=away
            # Turn toward the lidar-open perpendicular side
            _t = 1 if lidar[3] >= lidar[9] else -1
            if _en["dist"] < _CRIT or _facing < 1.2:
                # Enemy roughly ahead OR critically close: reverse to escape
                _mv = -1 if lidar[6] > tr + 10.0 else 1
                # Bonus: drop mine into enemy's path while backing away
                _sp = 1 if (me.get("mine_charges", 0) > 0 and _facing < 1.0) else 0
            else:
                # Facing away already: accelerate out of danger zone
                _mv = 1 if lidar[0] > tr + 10.0 else -1
                _sp = 0
            return _mv, _t, 0, _sp
        # ---------------------------------------------------------------------------

        # --- 1. Armed mine avoidance ---
        for mn in state.get("mines") or []:
            if mn.get("armed") and mn["dist"] < 80.0:
                self.mode = "MineDodge"
                a = _wrap(math.atan2(me["y"]-mn["y"], me["x"]-mn["x"]) - me["angle"])
                return (1 if lidar[0] > tr+10 else -1), (1 if a > 0.1 else -1), 0, 0

        # --- 2. Shell evasion (skipped if shielded) ---
        if not me.get("shield"):
            for s in state.get("shells") or []:
                if s.get("is_mine") and s.get("age_sec", 0) < 0.35:
                    continue
                if s["dist"] > 185.0:
                    continue
                tx2, ty2 = me["x"]-s["x"], me["y"]-s["y"]
                spd = math.hypot(s["vx"], s["vy"]) or 1.0
                dot = (tx2*s["vx"] + ty2*s["vy"]) / spd
                perp = abs(tx2*(-s["vy"]) + ty2*s["vx"]) / spd
                if dot > 0.0 and perp < tr + 22.0:
                    self.mode = "Evade"
                    sa = math.atan2(s["vy"], s["vx"])
                    esc = sa + (math.pi/2 if lidar[3] >= lidar[9] else -math.pi/2)
                    ea = _wrap(esc - me["angle"])
                    return (1 if lidar[0] > tr+14 else -1), (1 if ea > 0.1 else -1), 0, 0

        if not enemies:
            return 1, 0, 0, 0

        e0 = enemies[0]
        special = 0

        # --- 3. Corner mine trap — drop when enemy is close behind ---
        if me.get("mine_charges", 0) > 0 and e0["dist"] < 130.0:
            facing = abs(_wrap(me["angle"] - math.atan2(e0["y"]-me["y"], e0["x"]-me["x"])))
            if facing > 2.0:   # enemy > ~115° from front = mostly behind us
                special = 1

        # --- 4. Powerup routing (shield>laser>scatter>mine, within range) ---
        # Skip contested powerups: if an enemy is also near the same item AND
        # close enough to cause a collision on the approach, skip rather than
        # risk a head-on crash for a pickup.
        nav: tuple | None = None
        for pu in state.get("powerups") or []:
            if pu["dist"] > 270.0:
                continue
            pt = pu["type"]
            pri = (5 if pt == "shield" and not me.get("shield") else
                   4 if pt == "laser" and not me.get("laser_shots", 0) else
                   3 if pt == "scatter" and not me.get("scatter_shots", 0) else
                   2 if pt == "mine" and not me.get("mine_charges", 0) else 0)
            if pri >= 3 and pu["dist"] < 240.0:
                # Contested check: any enemy within 95 px of the powerup →
                # rushing in risks a crash (they may converge on the same point).
                _contested = any(
                    math.hypot(_e["x"] - pu["x"], _e["y"] - pu["y"]) < 95.0
                    for _e in enemies
                )
                if _contested and not me.get("shield"):
                    continue  # skip; don't rush into a crash
                nav = (pu["x"], pu["y"])
                self.mode = "Pickup"
                break

        # --- 5. Scan for direct / bank shot ---
        fire, aim_off = 0, None
        laser = me.get("laser_shots", 0) > 0
        rng = 820.0 if laser else 500.0
        mb = 4 if laser else 2
        hr2 = (tr + sr + 2.0) ** 2
        sr2 = (tr + sr + 10.0) ** 2

        if me["can_fire"] and lidar[0] > tr + 14.0:
            direct = None
            if e0["has_los"]:
                # Velocity-lead aiming: ~60fps → shell ≈ 3px/tick at 180px/s
                vx_e, vy_e = self._evel.get(e0["id"], (0.0, 0.0))
                tl = min(e0["dist"] / 3.0, 90.0)
                lx = e0["x"] + max(-120.0, min(120.0, vx_e * tl))
                ly = e0["y"] + max(-120.0, min(120.0, vy_e * tl))
                direct = _wrap(math.atan2(ly - me["y"], lx - me["x"]) - me["angle"])
            base = [0.0, -0.09, 0.09, -0.22, 0.22, -0.42, 0.42, -0.70, 0.70, -1.05, 1.05]
            scan = ([direct] + [direct + o for o in base]) if direct is not None else base
            for off in scan:
                pts = tb(me["x"], me["y"], me["angle"] + off, rng, mb)
                if len(pts) < 2:
                    continue
                # Self-hit: check bounced segments (skip seg 0 = initial shot)
                if any(_seg2(me["x"], me["y"],
                             pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1]) <= sr2
                       for i in range(1, len(pts)-1)):
                    continue
                # Enemy hit: check all segments
                if any(_seg2(en["x"], en["y"],
                             pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1]) <= hr2
                       for en in enemies for i in range(len(pts)-1)):
                    if abs(off) < 0.06:
                        fire = 1
                        self.mode = "KillShot"
                    else:
                        aim_off = off
                        label = "LeadAim" if direct is not None and abs(off-direct) < 0.12 else "BankAim"
                        self.mode = label
                    break

        if aim_off is not None:
            return (1 if lidar[0] > tr+24 else 0), (1 if aim_off > 0 else -1), fire, special

        # --- 6. Navigate toward powerup, or pursue enemy ---
        if nav is not None:
            nx, ny = nav
            if sp is not None:
                try:
                    path = sp(me["x"], me["y"], nx, ny)
                    if path and len(path) >= 2:
                        nx, ny = path[1]
                except Exception:
                    pass
        elif e0["has_los"]:
            nx, ny = e0["x"], e0["y"]
            self.mode = "Engage"
        else:
            nx, ny = e0["next_waypoint"]
            self.mode = "Hunt"

        da = _wrap(math.atan2(ny - me["y"], nx - me["x"]) - me["angle"])
        turn = 1 if da > 0.14 else (-1 if da < -0.14 else 0)
        if lidar[0] < tr + 14.0:
            move = -1 if abs(da) > 1.0 else 0
        elif e0["has_los"] and e0["dist"] < 115.0 and abs(da) < 0.40:
            move = 0   # hold kite range, keep aiming
        else:
            move = 1
        return move, turn, fire, special



