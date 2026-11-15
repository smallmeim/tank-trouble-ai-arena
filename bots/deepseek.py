"""Prism: 以自建弹道模拟器为核心的生存+反弹狙击小车。

核心思路（与「照文档拍脑袋」的做法不同，本脚本按仓库源码的真实参数实现）：
  1. 炮口实际在车体中心外 36px；贴墙时游戏会把出膛点压回墙内 4px，子弹随即
     反射回来——而 `selfHitGrace` 只在「未反弹」时生效，一旦反弹就能打死自己。
     所以贴墙开火等于自杀，本脚本把这一条做成硬门（第一段弹道 < 34px 一律不开火）。
  2. 用 state["walls"] 自建射线投射与多次反弹追踪（水平/垂直墙分开存，比逐墙
     做叉积快 3~4 倍），对每一发来袭子弹做**完整反射预测**，而不是只做直线外推。
  3. 机动决策不是「求一个逃跑方向」，而是把 8 种真实操作（前进/倒车/左右弧线/
     倒车弧线/原地左右转）代入运动学积分，逐时间片比较「我会在哪、子弹会在哪」，
     选生存率最高的那一种。这样决策天然与游戏里 move/turn 的实际语义一致。
  4. 开火三重门：炮口不被夹 → 弹道不会在 1.8s 内折返打到自己 → 确实能命中。
  5. 一次反弹用镜像法解析求解，二次反弹用角度扫描；持激光时按 4 次反弹全路径搜索
     （激光是 hitscan，命中半径 16，且首段跳过射手本人）。
"""

from __future__ import annotations

import math

TAU = 2.0 * math.pi
PI = math.pi
SIXTH = PI / 6.0

# 机动候选：(move, turn)。与游戏指令语义一一对应。
MANEUVERS = (
    (1, 0), (1, 1), (1, -1),
    (-1, 0), (-1, 1), (-1, -1),
    (0, 1), (0, -1),
)

# 威胁采样时间片（秒）。前密后疏：近处的生死比远处的更确定。
# 视界 1.38s：坦克转向要 0.5s 才能拐 90°，弹只提前 0.9s 发现等于没时间发力。
SAMPLE_T = (0.06, 0.13, 0.21, 0.30, 0.40, 0.51, 0.63, 0.76, 0.90, 1.05, 1.21, 1.38)
SAMPLE_N = len(SAMPLE_T)

MUZZLE = 36.0          # bodyLength/2 + barrelLength + shellRadius + 2
TANK_R = 16.0
SHELL_R = 3.0
SHELL_V = 180.0        # 子弹速度（m/s 意义上的 px/s），arena 里也会给
HIT_R = TANK_R + SHELL_R   # 子弹命中半径 19

PU_VALUE = {"shield": 0.98, "laser": 1.0, "scatter": 0.52, "mine": 0.34}


def _wrap(a: float) -> float:
    """归一化到 [-pi, pi)。"""
    return (a + PI) % TAU - PI


def _num(v, default: float = 0.0) -> float:
    """宽容地把 state 里任何东西转成有限 float。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f:  # NaN
        return default
    if f == float("inf") or f == float("-inf"):
        return default
    return f


def _pt_seg(px, py, x1, y1, x2, y2):
    """点到线段：返回 (距离, 沿线段走过的长度)。"""
    dx = x2 - x1
    dy = y2 - y1
    l2 = dx * dx + dy * dy
    if l2 < 1e-9:
        return math.hypot(px - x1, py - y1), 0.0
    t = ((px - x1) * dx + (py - y1) * dy) / l2
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    return math.hypot(px - (x1 + dx * t), py - (y1 + dy * t)), t * math.sqrt(l2)


def _parse_walls(raw):
    """墙按水平/垂直/其他分桶。迷宫里绝大多数是水平或垂直段，分桶后可省掉叉积。"""
    hs = []
    vs = []
    gs = []
    for w in raw or ():
        try:
            if isinstance(w, dict):
                x1 = float(w.get("x1", 0.0))
                y1 = float(w.get("y1", 0.0))
                x2 = float(w.get("x2", 0.0))
                y2 = float(w.get("y2", 0.0))
            else:
                x1 = float(w[0])
                y1 = float(w[1])
                x2 = float(w[2])
                y2 = float(w[3])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if abs(y1 - y2) <= 1e-6:
            hs.append((y1, x1 if x1 < x2 else x2, x2 if x1 < x2 else x1))
        elif abs(x1 - x2) <= 1e-6:
            vs.append((x1, y1 if y1 < y2 else y2, y2 if y1 < y2 else y1))
        else:
            gs.append((x1, y1, x2, y2))
    return (hs, vs, gs)


def _cast(px, py, dx, dy, rem, whv):
    """沿单位方向 (dx,dy) 投射 rem 距离，返回 (t∈[0,1], kind, 墙段)。

    kind: 0 无命中 / 1 水平墙 / 2 垂直墙 / 3 斜墙。
    """
    hs, vs, gs = whv
    best = 1.0
    kind = 0
    gw = None
    if dy != 0.0:
        inv = 1.0 / (dy * rem)
        for c, a, b in hs:
            t = (c - py) * inv
            if 0.0 <= t < best:
                x = px + dx * rem * t
                if a <= x <= b:
                    best = t
                    kind = 1
                    gw = None
    if dx != 0.0:
        inv = 1.0 / (dx * rem)
        for c, a, b in vs:
            t = (c - px) * inv
            if 0.0 <= t < best:
                y = py + dy * rem * t
                if a <= y <= b:
                    best = t
                    kind = 2
                    gw = None
    if gs:
        rx = dx * rem
        ry = dy * rem
        for x1, y1, x2, y2 in gs:
            sx = x2 - x1
            sy = y2 - y1
            den = rx * sy - ry * sx
            if den == 0.0 or -1e-9 < den < 1e-9:
                continue
            qx = x1 - px
            qy = y1 - py
            t = (qx * sy - qy * sx) / den
            if 0.0 <= t < best:
                u = (qx * ry - qy * rx) / den
                if 0.0 <= u <= 1.0:
                    best = t
                    kind = 3
                    gw = (x1, y1, x2, y2)
    return best, kind, gw


class SpaceBunnyPrism:
    """弹道几何 + 生存优先的混战小车。"""

    name = "DeepSeek"
    author = "DeepSeek (Prism / 弹道几何·生存优先)"

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def __init__(self) -> None:
        self.mode = "Init"
        self.whv = ([], [], [])
        self.spd = 120.0
        self.tsp = 3.0
        self.foes = []
        self._reset()

    def _reset(self) -> None:
        self.tick = -1
        self.last_x = None
        self.last_y = None
        self.still = 0
        self.unstuck = 0
        self.unstuck_turn = 1
        self.aim_angle = None
        self.aim_score = 0.0
        self.aim_tick = -999
        self.aim_hold = 0
        self.aim_cool = 0
        self.near_dist = 400.0
        self.last_maneuver = (1, 0)
        self.strafe = 1
        self.strafe_tick = 0
        self.mine_cool = 0
        self.mem = {}
        self.was_shield = False
        self.prev_move = 1
        self.goal_s = None
        self.cell = 96.0
        # 交战几何：贴近到 approach_r 内就改成绕圈，环绕半径 engage_r。
        # 混战里贴太近会被多方火力同时覆盖，所以宁可多留一点距离。
        self.approach_r = 420.0
        self.engage_r = 300.0

    # ------------------------------------------------------------------
    # 入口
    # ------------------------------------------------------------------
    def act(self, state):
        try:
            return self._act(state)
        except Exception:
            self.mode = "Err"
            return 0, 0, 0, 0

    # ------------------------------------------------------------------
    def _act(self, state):
        me = state.get("me") or {}
        if not me.get("alive", False):
            self.mode = "Dead"
            return 0, 0, 0, 0

        tick = int(_num(state.get("tick"), 0))
        if tick < self.tick or tick - self.tick > 240:
            self._reset()
        self.tick = tick

        arena = state.get("arena") or {}
        self.spd = max(40.0, _num(arena.get("tank_speed"), 120.0))
        self.tsp = max(1.2, _num(arena.get("turn_speed"), 3.0))
        self.cell = max(48.0, _num(arena.get("cell_size"), 96.0))
        self.whv = _parse_walls(state.get("walls"))

        mx = _num(me.get("x"))
        my = _num(me.get("y"))
        ang = _num(me.get("angle"))
        lidar = [_num(v, 360.0) for v in (me.get("lidar") or ())]
        if len(lidar) < 12:
            lidar = lidar + [360.0] * (12 - len(lidar))
        shield = bool(me.get("shield", False))
        laser = int(_num(me.get("laser_shots")))
        scatter = int(_num(me.get("scatter_shots")))
        mines = int(_num(me.get("mine_charges")))
        can_fire = bool(me.get("can_fire", False))
        active = int(_num(me.get("active_shells")))
        lid = lidar

        if self.mine_cool > 0:
            self.mine_cool -= 1

        # 敌方位置记忆（用于拦截提前量）
        self.foes = []
        nd = 400.0
        for e in state.get("enemies") or ():
            if not e.get("alive", True):
                continue
            ex = _num(e.get("x"))
            ey = _num(e.get("y"))
            eid = e.get("id", id(e))
            vx, vy = self._enemy_vel(eid, ex, ey)
            self.foes.append((ex, ey, bool(e.get("shield", False)), vx, vy))
            dd = math.hypot(ex - mx, ey - my)
            if dd < nd:
                nd = dd
        self.near_dist = max(60.0, nd)

        # --------------------------------------------------------------
        # 1) 卡墙检测 / 脱困
        # --------------------------------------------------------------
        if self.last_x is not None:
            moved = math.hypot(mx - self.last_x, my - self.last_y)
            if moved < 1.6 and self.prev_move != 0:
                self.still += 1
            else:
                self.still = 0
        self.last_x, self.last_y = mx, my

        if self.unstuck > 0:
            self.unstuck -= 1
            self.mode = "脱困"
            return -1, self.unstuck_turn, 0, 0
        if self.still >= 10:
            self.still = 0
            self.unstuck = 10
            left = lid[10] + lid[11] + lid[9]
            right = lid[1] + lid[2] + lid[3]
            self.unstuck_turn = -1 if left > right else 1
            self.aim_angle = None
            self.goal_s = None
            self.mode = "脱困"
            return -1, self.unstuck_turn, 0, 0

        # --------------------------------------------------------------
        # 2) 威胁收集（子弹完整反射预测 + 地雷）
        # --------------------------------------------------------------
        tracks, mines_hz, urgent = self._threats(state, mx, my)

        # --------------------------------------------------------------
        # 3) 开火解算
        # --------------------------------------------------------------
        fire = 0
        if can_fire:
            aim, score = self._pick_shot(state, mx, my, laser)
            if aim is not None:
                if self.aim_angle is None or abs(_wrap(aim - self.aim_angle)) > 0.02:
                    self.aim_hold = 0
                self.aim_angle = aim
                self.aim_score = score
                self.aim_tick = tick
            elif tick - self.aim_tick > 8:
                self.aim_angle = None
        self.aim_hold += 1

        # --------------------------------------------------------------
        # 4) 目标航向
        # --------------------------------------------------------------
        if self.aim_angle is not None:
            goal = self.aim_angle
            goal_w = 26.0
            self.goal_s = self.aim_angle
        else:
            goal, goal_w = self._goal(state, mx, my, shield, laser, scatter, mines)
            goal = self._smooth_goal(goal)
            if goal is None:
                # 场上没敌人也没道具：朝最开阔的方向游走
                bi = 0
                bv = -1.0
                for i in range(12):
                    if lid[i] > bv:
                        bv = lid[i]
                        bi = i
                goal = _wrap(ang + bi * SIXTH)
                goal_w = 8.0
                self.goal_s = goal

        # --------------------------------------------------------------
        # 5) 机动
        # --------------------------------------------------------------
        if self.aim_angle is not None and urgent < 0.20 and self.aim_hold < 24:
            # 精细瞄准走直连转向：机动评分器的时间视界太粗，小角度误差会被
            # 「转过头的惩罚」压住，导致永远转不到位、一炮不开。
            err = _wrap(self.aim_angle - ang)
            tol = max(0.055, min(0.17, math.atan2(13.0, self.near_dist)))
            if self.aim_hold > 7:
                tol = max(tol, 0.13)
            if abs(err) < tol:
                if can_fire:
                    fire = 1
                    self.aim_angle = None
                    self.aim_hold = 0
                move, turn = 0, 0
            elif abs(err) > 2.4:
                # 目标在背后：倒车转向比掉头快
                move, turn = -1, (-1 if err > 0 else 1)
            else:
                turn = 1 if err > 0.03 else (-1 if err < -0.03 else 0)
                move = 1 if (abs(err) < 0.75 and lid[0] > 64.0) else 0
        else:
            if self.aim_hold >= 24:
                self.aim_angle = None
                self.aim_hold = 0
            move, turn = self._maneuver(
                mx, my, ang, lid, goal, goal_w, tracks, mines_hz, urgent, shield
            )

        # --------------------------------------------------------------
        # 6) 布雷
        # --------------------------------------------------------------
        special = 0
        if mines > 0 and self.mine_cool == 0 and move == 1:
            special = self._mine(state, mx, my, ang, lid)
            if special:
                self.mine_cool = 22

        if fire:
            self.mode = "开火"
        elif urgent > 0.35:
            self.mode = "闪避"
        elif self.aim_angle is not None:
            self.mode = "瞄准"
        else:
            self.mode = "游走"

        self.prev_move = move
        return move, turn, fire, special

    def _smooth_goal(self, goal):
        """目标航向限速平滑：抑制路点在格子边界处逐帧翻转造成的来回打转。"""
        if goal is None:
            self.goal_s = None
            return None
        if self.goal_s is None:
            self.goal_s = goal
            return goal
        d = _wrap(goal - self.goal_s)
        lim = 0.5
        if d > lim:
            d = lim
        elif d < -lim:
            d = -lim
        self.goal_s = _wrap(self.goal_s + d)
        return self.goal_s

    # ------------------------------------------------------------------
    # 敌人速度估计（用于提前量）
    # ------------------------------------------------------------------
    def _enemy_vel(self, eid, x, y):
        prev = self.mem.get(eid)
        now = self.tick
        self.mem[eid] = (x, y, now)
        if prev is None:
            return 0.0, 0.0
        dt = (now - prev[2]) / 60.0
        if dt < 0.012 or dt > 0.6:
            return 0.0, 0.0
        return (x - prev[0]) / dt, (y - prev[1]) / dt

    # ------------------------------------------------------------------
    # 弹道追踪
    # ------------------------------------------------------------------
    def _trace(self, ox, oy, angle, max_dist, max_bounces):
        pts = [(ox, oy)]
        px = ox
        py = oy
        ca = math.cos(angle)
        sa = math.sin(angle)
        rem = max_dist
        whv = self.whv
        for _ in range(max_bounces + 1):
            if rem <= 0.6:
                break
            t, kind, gw = _cast(px, py, ca, sa, rem, whv)
            if t >= 1.0:
                pts.append((px + ca * rem, py + sa * rem))
                break
            d = rem * t
            if d < 0.4:          # 起点贴在墙上：断开，避免零长度段死循环
                break
            hx = px + ca * d
            hy = py + sa * d
            pts.append((hx, hy))
            rem -= d
            if kind == 1:
                sa = -sa
            elif kind == 2:
                ca = -ca
            elif gw is not None:
                wx = gw[2] - gw[0]
                wy = gw[3] - gw[1]
                ln = math.hypot(wx, wy) or 1.0
                nx = -wy / ln
                ny = wx / ln
                dot = ca * nx + sa * ny
                ca -= 2.0 * dot * nx
                sa -= 2.0 * dot * ny
            px = hx + ca * 0.5
            py = hy + sa * 0.5
        return pts

    def _muzzle(self, mx, my, angle):
        """与 tank.js 的 muzzlePoint 同算法：贴墙时把出膛点压回墙内侧 4px。"""
        ca = math.cos(angle)
        sa = math.sin(angle)
        dist = MUZZLE
        t, _kind, _gw = _cast(mx, my, ca, sa, MUZZLE, self.whv)
        if t < 1.0:
            cut = t * MUZZLE - SHELL_R - 1.0
            if cut < dist:
                dist = cut
        return mx + ca * dist, my + sa * dist

    # ------------------------------------------------------------------
    # 威胁
    # ------------------------------------------------------------------
    def _threats(self, state, mx, my):
        """返回 (每发子弹在 SAMPLE_T 上的位置轨迹, 地雷列表, 紧急度)。"""
        tracks = []
        urgent = 0.0
        for s in state.get("shells") or ():
            if not isinstance(s, dict):
                continue
            vx = _num(s.get("vx"))
            vy = _num(s.get("vy"))
            spd = math.hypot(vx, vy)
            if spd < 30.0:
                continue
            sx = _num(s.get("x"))
            sy = _num(s.get("y"))
            # 己方未反弹的子弹有 0.25s 出膛豁免
            if s.get("is_mine") and _num(s.get("bounces"), 0) < 1 and _num(s.get("age_sec"), 1.0) < 0.28:
                continue
            d0 = math.hypot(sx - mx, sy - my)
            if d0 > spd * SAMPLE_T[-1] + 40.0:
                continue
            tr = self._track(sx, sy, vx, vy, spd)
            if tr is None:
                continue
            tracks.append(tr)
            # 紧急度：0.55s 内最近距离
            for i, t in enumerate(SAMPLE_T):
                if t > 0.58:
                    break
                px, py = tr[i]
                dd = math.hypot(px - mx, py - my)
                if dd < 46.0:
                    u = (46.0 - dd) / 46.0 / (1.0 + t * 2.0)
                    if u > urgent:
                        urgent = u

        near_mines = []
        for m in state.get("mines") or ():
            if not isinstance(m, dict):
                continue
            nmx = _num(m.get("x"))
            nmy = _num(m.get("y"))
            d = math.hypot(nmx - mx, nmy - my)
            if d < 130.0:
                near_mines.append((nmx, nmy, 1.0 if m.get("armed") else 0.7))
                if m.get("armed") and d < 52.0:
                    u = (52.0 - d) / 52.0
                    if u > urgent:
                        urgent = u
        return tracks, near_mines, urgent

    def _track(self, sx, sy, vx, vy, spd):
        horizon = SAMPLE_T[-1] * spd + 30.0
        pts = self._trace(sx, sy, math.atan2(vy, vx), horizon, 3)
        n = len(pts)
        if n < 2:
            return None
        seg = []
        for i in range(n - 1):
            seg.append(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]))
        out = []
        i = 0
        base = 0.0
        for t in SAMPLE_T:
            arc = spd * t
            while i < n - 1 and base + seg[i] < arc:
                base += seg[i]
                i += 1
            if i >= n - 1:
                out.append(pts[-1])
                continue
            if seg[i] < 1e-6:
                out.append(pts[i])
                continue
            f = (arc - base) / seg[i]
            out.append((
                pts[i][0] + (pts[i + 1][0] - pts[i][0]) * f,
                pts[i][1] + (pts[i + 1][1] - pts[i][1]) * f,
            ))
        return out

    # ------------------------------------------------------------------
    # 开火解算
    # ------------------------------------------------------------------
    def _pick_shot(self, state, mx, my, laser):
        """返回 (角度, 分数)。分数 <= 0 表示不值得瞄。"""
        if not self.foes:
            return None, 0.0

        # 上一帧的解还在有效期内：先复核（1 条弹道，很便宜）
        if self.aim_angle is not None and self.tick - self.aim_tick <= 6:
            sc = self._eval(self.aim_angle, mx, my, laser)
            if sc > 0.0:
                return self.aim_angle, sc

        best_a = None
        best_s = 0.0
        # 1) 直接瞄准（带迭代提前量）
        for ex, ey, esh, evx, evy in self.foes[:3]:
            ang = self._lead_angle(mx, my, ex, ey, evx, evy)
            sc = self._eval(ang, mx, my, laser)
            if sc > best_s:
                best_s, best_a = sc, ang

        # 2) 一次反弹：镜像法解析求解（快且精确）
        if best_s <= 0.0:
            for ex, ey, esh, evx, evy in self.foes[:2]:
                for ang in self._mirror_aims(mx, my, ex, ey):
                    sc = self._eval(ang, mx, my, laser)
                    if sc > best_s:
                        best_s, best_a = sc, ang

        # 3) 角度扫描：补漏（每 6 个决策帧做一次，避免拖慢 30Hz 的决策回路）
        if best_s <= 0.0 and (self.tick % 6 == 0 or self.aim_cool <= 0):
            self.aim_cool = 6
            base = self._base_heading(mx, my)
            step = PI / 10.0 if laser else PI / 9.0
            for k in range(-10, 11):
                ang = _wrap(base + k * step)
                sc = self._eval(ang, mx, my, laser)
                if sc > best_s:
                    best_s, best_a = sc, ang
        if self.aim_cool > 0:
            self.aim_cool -= 1

        if best_a is None:
            return None, 0.0
        return best_a, best_s

    def _base_heading(self, mx, my):
        # 以「指向最近敌人」为扫描中心，比以自身朝向为中心更容易扫到人
        if self.foes:
            ex, ey = self.foes[0][0], self.foes[0][1]
            return math.atan2(ey - my, ex - mx)
        return 0.0

    def _lead_angle(self, mx, my, ex, ey, evx, evy):
        px, py = ex, ey
        for _ in range(2):
            t = math.hypot(px - mx, py - my) / SHELL_V
            if t > 2.2:
                break
            px = ex + evx * t
            py = ey + evy * t
        return math.atan2(py - my, px - mx)

    def _mirror_aims(self, mx, my, ex, ey):
        """把敌人关于每面近墙镜像一次，得到解析的一次反弹瞄准角。"""
        out = []
        for x1, y1, x2, y2 in self._near_segs(ex, ey, 210.0):
            wx = x2 - x1
            wy = y2 - y1
            ln2 = wx * wx + wy * wy
            if ln2 < 1e-6:
                continue
            # 镜像点
            t = ((ex - x1) * wx + (ey - y1) * wy) / ln2
            bx = x1 + wx * t
            by = y1 + wy * t
            vx = ex - bx
            vy = ey - by
            sx = bx - vx
            sy = by - vy
            out.append(math.atan2(sy - my, sx - mx))
        return out

    def _near_segs(self, x, y, rad):
        hs, vs, gs = self.whv
        out = []
        for c, a, b in hs:
            if abs(c - y) > rad:
                continue
            if x < a - rad or x > b + rad:
                continue
            out.append((a, c, b, c))
        for c, a, b in vs:
            if abs(c - x) > rad:
                continue
            if y < a - rad or y > b + rad:
                continue
            out.append((c, a, c, b))
        for seg in gs:
            out.append(seg)
        return out[:9]

    def _eval(self, angle, mx, my, laser):
        """评估一条弹道：>0 = 能命中敌人，<=0 = 无解或不安全。"""
        mzx, mzy = self._muzzle(mx, my, angle)
        if math.hypot(mzx - mx, mzy - my) < 27.0:
            return -1.0                       # 炮口被墙夹住，开火必自爆
        maxd = 990.0 if laser else 740.0
        mb = 4 if laser else 2
        pts = self._trace(mzx, mzy, angle, maxd, mb)
        n = len(pts)
        if n < 2:
            return -1.0
        first = math.hypot(pts[1][0] - mzx, pts[1][1] - mzy)
        if not laser and first < 34.0:
            return -1.0                       # 出膛即贴墙

        cum = 0.0
        hit_travel = -1.0
        hit_bounce = 0
        hit_shield = False
        for i in range(n - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            seg = math.hypot(x2 - x1, y2 - y1)

            # 反弹后折返打自己（自伤豁免只在「首段且未反弹」时有效）
            if i >= 1:
                d, along = _pt_seg(mx, my, x1, y1, x2, y2)
                if d < 25.0:
                    if laser:
                        return -1.0
                    if (cum + along) / SHELL_V < 1.80 and not self.was_shield:
                        return -1.0

            for fx, fy, fsh, _evx, _evy in self.foes:
                if laser:
                    thr = TANK_R
                else:
                    thr = HIT_R - min(7.0, (cum / SHELL_V) * 6.0)
                d, along = _pt_seg(fx, fy, x1, y1, x2, y2)
                if d <= thr:
                    tr = cum + along
                    if hit_travel < 0.0 or tr < hit_travel:
                        hit_travel = tr
                        hit_bounce = i
                        hit_shield = fsh
            cum += seg

        if hit_travel < 0.0:
            return 0.0
        score = 104.0 - hit_travel * 0.055 - hit_bounce * 12.0
        if hit_shield:
            score *= 0.45
        if laser:
            score += 16.0
        return score

    # ------------------------------------------------------------------
    # 目标
    # ------------------------------------------------------------------
    def _goal(self, state, mx, my, shield, laser, scatter, mines):
        powerups = state.get("powerups") or ()
        best = None
        best_val = 0.0
        for pu in powerups:
            if not isinstance(pu, dict):
                continue
            ptype = str(pu.get("type", ""))
            w = PU_VALUE.get(ptype, 0.25)
            if ptype == "shield" and shield:
                w = 0.14
            elif ptype == "laser" and laser > 0:
                w = 0.10
            elif ptype == "scatter" and scatter > 0:
                w = 0.20
            elif ptype == "mine" and mines > 0:
                w = 0.14
            pd = math.hypot(_num(pu.get("x")) - mx, _num(pu.get("y")) - my)
            if pd > 560.0:
                continue
            val = w / (70.0 + pd)
            if val > best_val:
                best_val = val
                best = (_num(pu.get("x")), _num(pu.get("y")))

        has_target = best is not None and best_val > 0.0011

        enemy = self._pick_enemy(mx, my)
        if has_target:
            # 近身缠斗时不为了道具横穿人家的弹道
            if enemy is not None:
                ed = math.hypot(enemy[0] - mx, enemy[1] - my)
                if ed < 130.0 and best_val < 0.0032:
                    has_target = False
            if has_target:
                return self._path_heading(mx, my, best[0], best[1], state), 12.0

        if enemy is not None:
            ex, ey = enemy
            d = math.hypot(ex - mx, ey - my)
            if d > self.approach_r:
                return self._path_heading(mx, my, ex, ey, state), 12.0
            # 绕圈走位：目标点取敌人外侧 engage_r、偏约 0.95rad 的位置，形成环绕
            if self.tick - self.strafe_tick > 110:
                self.strafe_tick = self.tick
                self.strafe = -self.strafe
            b = math.atan2(my - ey, mx - ex) + 0.95 * self.strafe
            tx = ex + math.cos(b) * self.engage_r
            ty = ey + math.sin(b) * self.engage_r
            return self._path_heading(mx, my, tx, ty, state), 9.0

        # 无对手：找最开阔的方向游走
        return None, 0.0

    def _pick_enemy(self, mx, my):
        if not self.foes:
            return None
        best = None
        bd = 1e9
        for ex, ey, _sh, _vx, _vy in self.foes:
            d = math.hypot(ex - mx, ey - my)
            if d < bd:
                bd = d
                best = (ex, ey)
        return best

    def _path_heading(self, mx, my, tx, ty, state):
        """沿 BFS 路径取「下一个不同的格子」的中心作为目标点。

        不能用「第一个超过 N 像素的路点」——那会在阈值附近逐帧跳点，
        导致目标航向在两个格子间翻转、车子原地抽搐。
        """
        helpers = state.get("helpers") or {}
        sp = helpers.get("shortest_path")
        if callable(sp):
            try:
                path = sp(mx, my, tx, ty)
            except Exception:
                path = None
            if path:
                cs = self.cell
                mc = (int(mx // cs), int(my // cs))
                for wp in path:
                    wx = _num(wp[0])
                    wy = _num(wp[1])
                    if (int(wx // cs), int(wy // cs)) != mc:
                        return math.atan2(wy - my, wx - mx)
                wx = _num(path[-1][0])
                wy = _num(path[-1][1])
                return math.atan2(wy - my, wx - mx)
        return math.atan2(ty - my, tx - mx)

    # ------------------------------------------------------------------
    # 机动
    # ------------------------------------------------------------------
    def _motion(self, mx, my, angle, move, turn, ts):
        """把 (move,turn) 指令在 ts 秒后的位移算出来（与 tank.js 的积分一致）。"""
        if move == 0:
            return mx, my
        v = self.spd * move
        w = self.tsp * turn
        if w == 0.0:
            return mx + math.cos(angle) * v * ts, my + math.sin(angle) * v * ts
        a1 = angle + w * ts
        return (
            mx + (v / w) * (math.sin(a1) - math.sin(angle)),
            my - (v / w) * (math.cos(a1) - math.cos(angle)),
        )

    def _maneuver(self, mx, my, ang, lid, goal, goal_w, tracks, mines_hz, urgent, shield):
        R = 27.0
        R2 = R * R
        best = None
        best_score = -1e9
        threat_w = 90.0 if not shield else 55.0
        goal_w = goal_w * (1.0 if urgent < 0.2 else max(0.0, 1.0 - urgent * 1.6))

        for move, turn in MANEUVERS:
            pos = [self._motion(mx, my, ang, move, turn, t) for t in SAMPLE_T]

            # —— 子弹 ——
            pen = 0.0
            for tr in tracks:
                for i in range(SAMPLE_N):
                    px, py = pos[i]
                    dx = px - tr[i][0]
                    dy = py - tr[i][1]
                    d2 = dx * dx + dy * dy
                    if d2 < R2:
                        d = math.sqrt(d2)
                        pen += (R - d) * (R - d) * (1.0 - i * 0.05)
            if pen > 0.0:
                pen *= threat_w * 0.06

            # —— 地雷 ——
            for nmx, nmy, armed in mines_hz:
                md2 = 1e18
                for px, py in pos:
                    dx = px - nmx
                    dy = py - nmy
                    d2 = dx * dx + dy * dy
                    if d2 < md2:
                        md2 = d2
                lim = 74.0 if armed > 0.9 else 56.0
                if md2 < lim * lim:
                    pen += (lim - math.sqrt(md2)) * 1.6 * armed

            # —— 撞墙 / 转向 ——
            h_now = ang + self.tsp * turn * 0.35
            dirn = h_now if move >= 0 else h_now + PI
            fwd = lid[int(round(_wrap(dirn - ang) / SIXTH)) % 12]
            if fwd < 52.0:
                pen += (52.0 - fwd) * (1.35 if fwd < 30.0 else 0.55)
            if move == 0:
                pen += 3.5
            elif move < 0:
                pen += 1.2

            # —— 目标吸引 ——
            if goal is not None:
                pen -= math.cos(dirn - goal) * goal_w

            # —— 惯性（防抖） ——
            if (move, turn) == self.last_maneuver:
                pen -= 1.6

            if -pen > best_score:
                best_score = -pen
                best = (move, turn)

        if best is None:
            return 1, 0
        self.last_maneuver = best
        return best[0], best[1]

    # ------------------------------------------------------------------
    # 布雷
    # ------------------------------------------------------------------
    def _mine(self, state, mx, my, ang, lid):
        for m in state.get("mines") or ():
            if not isinstance(m, dict):
                continue
            if math.hypot(_num(m.get("x")) - mx, _num(m.get("y")) - my) < 105.0:
                return 0
        for ex, ey, _sh, _vx, _vy in self.foes:
            d = math.hypot(ex - mx, ey - my)
            if d > 420.0:
                continue
            # 敌人在我身后，或正要穿过我刚走过的窄口
            bx = mx - ex
            by = my - ey
            dot = (bx * math.cos(ang) + by * math.sin(ang)) / (d or 1.0)
            if dot > 0.25:
                return 1
            if lid[3] + lid[9] < 210.0:
                return 1
        return 0
