"""A cautious ricochet hunter that dodges threats and collects useful powerups."""

import math


def _wrap(angle):
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def _segment_distance2(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 <= 1e-9:
        return (px - ax) ** 2 + (py - ay) ** 2
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2


class PhantomBot:
    """Dodges incoming threats, routes to powerups, and takes safe bank shots."""

    name = "6Astra"
    author = "6Astra (Phantom / Ricochet Hunter)"

    def __init__(self):
        self._last_xy = None
        self._stuck = 0
        self.mode = "Hunt"

    def act(self, state):
        try:
            action = self._act(state)
            return self._avoid_collision(state, action)
        except Exception:
            self.mode = "Recover"
            return 0, 0, 0, 0

    def _avoid_collision(self, state, action):
        me = state["me"]
        arena = state.get("arena", {})
        radius = arena.get("tank_radius", 16.0)
        speed = arena.get("tank_speed", 120.0)
        turn_speed = arena.get("turn_speed", 3.0)
        lidar = me.get("lidar", [0.0] * 12)
        x, y, angle = me["x"], me["y"], me["angle"]
        nearby = [e for e in state.get("enemies", []) if e.get("dist", 1e9) < 90]
        if not nearby:
            return action

        # Consider both directions of enemy travel: heading does not reveal reverse gear.
        horizon = 0.3
        def clearance(move, turn):
            heading = angle + turn * turn_speed * horizon / 2
            mx = x + move * speed * horizon * math.cos(heading)
            my = y + move * speed * horizon * math.sin(heading)
            closest = float("inf")
            for enemy in nearby:
                ex, ey = enemy["x"] - x, enemy["y"] - y
                enemy_angle = enemy.get("angle", 0.0)
                for direction in (-1, 0, 1):
                    dx = ex + direction * speed * horizon * math.cos(enemy_angle) - (mx - x)
                    dy = ey + direction * speed * horizon * math.sin(enemy_angle) - (my - y)
                    closest = min(closest, math.sqrt(_segment_distance2(0, 0, ex, ey, dx, dy)))
            return closest

        move, turn, fire, special = action
        if clearance(move, turn) >= 2 * radius + 20:
            return action

        options = [(0, -1), (0, 1), (0, 0)]
        if lidar[0] > radius + 20:
            options.extend(((1, -1), (1, 0), (1, 1)))
        if lidar[6] > radius + 20:
            options.extend(((-1, -1), (-1, 0), (-1, 1)))
        nearest = min(nearby, key=lambda e: e.get("dist", 1e9))
        away = math.atan2(y - nearest["y"], x - nearest["x"])
        def score(candidate):
            m, t = candidate
            facing = angle + t * turn_speed * horizon
            return (clearance(m, t), -abs(_wrap(away - facing)), m == move and t == turn)
        move, turn = max(options, key=score)
        self.mode = "AvoidTank"
        return move, turn, fire, special

    def _act(self, state):
        me = state["me"]
        arena = state.get("arena", {})
        helpers = state.get("helpers", {})
        x, y, angle = me["x"], me["y"], me["angle"]
        radius = arena.get("tank_radius", 16.0)
        shell_radius = arena.get("shell_radius", 3.0)
        lidar = me.get("lidar", [0.0] * 12)
        enemies = state.get("enemies", [])
        trace = helpers.get("trace_bounces")
        raycast = helpers.get("raycast")

        if self._last_xy is not None and math.hypot(x - self._last_xy[0], y - self._last_xy[1]) < 0.8:
            self._stuck += 1
        else:
            self._stuck = max(0, self._stuck - 2)
        self._last_xy = (x, y)
        if self._stuck > 12:
            self.mode = "Escape"
            turn = 1 if lidar[3] >= lidar[9] else -1
            if self._stuck > 24:
                self._stuck = 0
            return -1, turn, 0, 0

        # Evade armed mines and shells on a near-term collision course.
        if not me.get("shield", False):
            for mine in state.get("mines", []):
                if mine.get("armed") and mine.get("dist", 1e9) < radius + 62:
                    away = math.atan2(y - mine["y"], x - mine["x"])
                    err = _wrap(away - angle)
                    self.mode = "DodgeMine"
                    return (-1 if lidar[6] > radius + 12 else 1), (1 if err >= 0 else -1), 0, 0

            for shell in state.get("shells", []):
                if shell.get("is_mine") and shell.get("age_sec", 0.0) < 0.35:
                    continue
                if shell.get("dist", 1e9) > 220:
                    continue
                vx, vy = shell.get("vx", 0.0), shell.get("vy", 0.0)
                speed2 = vx * vx + vy * vy
                if speed2 < 1:
                    continue
                t = max(0.0, min(1.0, ((x - shell["x"]) * vx + (y - shell["y"]) * vy) / speed2))
                cx, cy = shell["x"] + vx * t, shell["y"] + vy * t
                if (cx - x) ** 2 + (cy - y) ** 2 < (radius + shell_radius + 18) ** 2:
                    evade = math.atan2(-vx, vy)
                    if lidar[9] > lidar[3]:
                        evade += math.pi
                    err = _wrap(evade - angle)
                    self.mode = "DodgeShell"
                    return (1 if lidar[0] > radius + 14 else -1), (1 if err > 0 else -1), 0, 0

        # Seek a useful nearby pickup; otherwise follow the nearest enemy's route.
        target = None
        priorities = {"shield": 4 if not me.get("shield") else 0,
                      "laser": 3 if not me.get("laser_shots") else 0,
                      "scatter": 2 if not me.get("scatter_shots") else 0,
                      "mine": 1 if not me.get("mine_charges") else 0}
        for pickup in state.get("powerups", []):
            contested = any(math.hypot(e["x"] - pickup["x"], e["y"] - pickup["y"]) < 180
                            and math.hypot(e["x"] - pickup["x"], e["y"] - pickup["y"])
                            <= pickup.get("dist", 1e9) + 50 for e in enemies)
            if pickup.get("dist", 1e9) <= 250 and priorities.get(pickup.get("type"), 0) and not contested:
                target = (pickup["x"], pickup["y"])
                self.mode = "Pickup"
                break
        if target is None and enemies:
            enemy = enemies[0]
            if enemy.get("has_los"):
                target = (enemy["x"], enemy["y"])
                self.mode = "Engage"
            else:
                target = enemy.get("next_waypoint", (enemy["x"], enemy["y"]))
                self.mode = "Hunt"

        # Drop a mine when a nearby enemy is behind us or closing in.
        special = 0
        if enemies and me.get("mine_charges", 0) > 0 and enemies[0].get("dist", 1e9) < 125:
            enemy = enemies[0]
            bearing = math.atan2(enemy["y"] - y, enemy["x"] - x)
            special = int(abs(_wrap(bearing - angle)) > 2.0)

        # Fire only when the live maze trace predicts an enemy hit and no self-hit.
        fire, aim = 0, None
        if me.get("can_fire") and enemies and trace:
            laser = me.get("laser_shots", 0) > 0
            hit_r2 = (radius + shell_radius + 8) ** 2
            self_r2 = (radius + shell_radius + 10) ** 2
            for offset in (0.0, -0.10, 0.10, -0.24, 0.24, -0.45, 0.45, -0.72, 0.72):
                shot_angle = angle + offset
                if raycast and raycast(x, y, shot_angle, radius + shell_radius + 20) < radius + shell_radius + 12:
                    continue
                try:
                    points = trace(x, y, shot_angle, 720 if laser else 430, 4 if laser else 2)
                except Exception:
                    continue
                hit = False
                unsafe = any(_segment_distance2(x, y, *points[i], *points[i + 1]) <= self_r2
                             for i in range(1, len(points) - 1))
                if unsafe:
                    continue
                for i in range(len(points) - 1):
                    if any(_segment_distance2(e["x"], e["y"], *points[i], *points[i + 1]) <= hit_r2
                           for e in enemies):
                        hit = True
                        break
                if hit:
                    if abs(offset) <= 0.055:
                        fire = 1
                        self.mode = "BankShot"
                    else:
                        aim = offset
                        self.mode = "AimShot"
                    break

        if aim is not None:
            return (1 if lidar[0] > radius + 24 else 0), (1 if aim > 0 else -1), fire, special

        if target is None:
            self.mode = "Search"
            turn = 1 if lidar[2] >= lidar[10] else -1
            return (1 if lidar[0] > radius + 18 else -1), turn, fire, special

        desired = math.atan2(target[1] - y, target[0] - x)
        err = _wrap(desired - angle)
        turn = 1 if err > 0.13 else (-1 if err < -0.13 else 0)
        if lidar[0] < radius + 17:
            move = -1 if lidar[6] > radius + 12 and abs(err) > 0.8 else 0
        elif enemies and enemies[0].get("has_los") and enemies[0].get("dist", 1e9) < 115:
            move = 0
        else:
            move = 1
        return move, turn, fire, special
