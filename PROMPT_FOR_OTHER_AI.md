# 给其他 AI 写《坦克回廊 (GitHub Tank Trouble)》参战小车代码的提示词

把下面整段提示词**完整复制**，发给任意大模型或 AI 编程助手（DeepSeek / Claude Code / Codex / Cursor / ChatGPT / Gemini / Qwen）。
- 如果对方是**能读写本地文件的 AI 编程助手**，它会直接把小车脚本写进配置文件夹：
  `C:\Users\24718\.gemini\antigravity\scratch\tank-trouble-github\bots\`
- 生成好后，在游戏顶部栏点 **「🔄 刷新 bots/」**（不必重启游戏），即可在 **1号车 ~ 6号车** 下拉框里把不同 AI 的 `.py` 分别选给不同小车开打！

---

## 复制下面这段 Prompt 发给其他 AI：

```text
请用纯 Python 标准库（如 math、random，不要第三方库）为我的本地《坦克回廊 (Tank Trouble) AI 混战》游戏编写一个参战小车控制脚本。

【零、目标存放路径（重要！请直接写入配置文件夹）】
- 请将生成的完整单文件 `.py` **直接创建/保存**到以下本地配置文件夹中：
  `C:\Users\24718\.gemini\antigravity\scratch\tank-trouble-github\bots\`
- 命名要求：使用简短、唯一的英文小写+下划线文件名，例如 `bots/claude_sniper.py`、`bots/deepseek_tank.py`（不要使用下划线 `_` 开头，也不要修改该目录下原有的 `loader.py`、`__init__.py`、`example_*.py` 或其他已有小车文件）。
- 如果你当前环境具备本地文件写入工具/权限，请**直接在该文件夹下新建并写入这个 `.py` 文件**，写完后告诉我你创建的文件名、AI 名称和战术思路即可。
- 如果你当前环境无法直接操作我的本地文件，请只输出一个完整的单文件 Python 代码块，并注明让我保存到上述目录中。

【一、代码与返回接口规范】
1. 推荐使用类定义（或模块级 `act(state)` 函数）：
   - 类属性 `name = "你的AI名称"`（建议英文或简短中文，≤12字，会在小车头顶和比分榜显示）
   - 类属性 `author = "模型名 / 战术流派"`
   - **重要**：如果写了 `__init__(self)`，必须支持**无参数实例化**（不要有必填参数）。
   - 实例方法 `def act(self, state: dict) -> tuple[int, int, int, int]:`（兼容返回 3 元组 `(move, turn, fire)` 或 4 元组 `(move, turn, fire, special)`，或字典 `{"move": ..., "turn": ..., "fire": ..., "special": ...}`）：
     - `move`：`1` 前进，`0` 停止，`-1` 后退
     - `turn`：`-1` 左转（逆时针，减小 angle），`0` 不转，`1` 右转（顺时针，增大 angle）
     - `fire`：`1` 开炮（或发射已拾取的激光/散射），`0` 不开炮
     - `special`：`1` 放置隐形地雷（当你持有地雷 `mine_charges > 0` 时），`0` 不放
2. 可以在 `self.__init__` 里维护跨帧状态（例如卡墙脱困计时、上几帧坐标记录、游走目标等），请确保 `act()` 执行快且不要抛出未捕获异常。

【二、世界坐标系与实战规则】
- 坐标系：`+x` 向右，`+y` 向下，`angle = 0` 指向正右，`+pi/2` 指向正下；迷宫每格 `96 px`（常见 9x7 或 13x8 格）。
- 核心物理参数（每帧也都会在 `state["arena"]` 中给出）：
  - 坦克半径 `16 px`，移动速度 `120 px/s`，转向速度 `3.0 rad/s`。
  - 普通子弹半径 `3 px`，速度 `180 px/s`，同屏最多存在 5 发，发射约 0.25s 出膛保护期后**碰墙会反弹并能炸死自己**（贴墙或窄巷面对墙时千万别盲射！）。
  - 场上会刷新 4 种经典道具：**散射 (`scatter`)、护盾 (`shield`)、反弹激光 (`laser`)、隐形地雷 (`mine`)**，内墙还可被炮弹/地雷炸毁（迷宫路径会随之变化）。

【三、每帧传入的 `state` 字典结构】
state = {
    "tick": int,
    "arena": {
        "width": float, "height": float, "cell_size": float,
        "tank_radius": 16.0, "shell_radius": 3.0,
        "shell_speed": 180.0, "tank_speed": 120.0, "turn_speed": 3.0,
    },
    "me": {
        "id": int, "x": float, "y": float, "angle": float,
        "alive": bool, "can_fire": bool, "active_shells": int,
        "shield": bool, "shield_timer": float,
        "scatter_shots": int, "laser_shots": int, "mine_charges": int,
        "lidar": list[float],   # 12 条激光雷达测距：lidar[0]正前方，顺时针每30°一条（lidar[3]右, lidar[6]后, lidar[9]左）
    },
    "enemies": [                # 存活敌方小车列表，已按距离从近到远排序
        {
            "id": int, "name": str, "x": float, "y": float, "angle": float,
            "dist": float, "rel_angle": float,      # >0 表示敌人在右侧需 turn=+1
            "maze_steps": int,
            "next_waypoint": (wx, wy),              # 迷宫 BFS 最短路径下一路点
            "has_los": bool,                        # 是否有直线无遮挡射击视野
            "shield": bool, "scatter_shots": int, "laser_shots": int, "mine_charges": int,
        }, ...
    ],
    "shells": [                 # 场上子弹，已按距离排序
        {"owner": int, "is_mine": bool, "x": float, "y": float, "vx": float, "vy": float, "age_sec": float, "dist": float}, ...
    ],
    "powerups": [               # 场上道具，已按距离排序
        {"type": "scatter"|"shield"|"laser"|"mine", "x": float, "y": float, "dist": float, "rel_angle": float}, ...
    ],
    "mines": [                  # 场上地雷
        {"owner": int, "is_mine": bool, "x": float, "y": float, "dist": float, "armed": bool}, ...
    ],
    "helpers": {                # 可直接调用的实时迷宫几何函数（已随破墙实时更新！）
        "raycast":       Callable[[x, y, angle, max_dist], float],
        "trace_bounces": Callable[[x, y, angle, max_dist, max_bounces], list[tuple[float, float]]],
        "shortest_path": Callable[[x0, y0, x1, y1], list[tuple[float, float]]],
        "has_los":       Callable[[x0, y0, x1, y1], bool],
    },
}

【四、战术设计建议】
1. 没有护盾时优先躲避高速逼近的来弹和 `armed=True` 的地雷；开火前先用 `raycast` / `trace_bounces` 确认弹道不会贴墙反弹误杀自己。
2. 持反弹激光（`laser_shots > 0`）或普通弹时，可扫描 `me["angle"] + offset` 调用 `trace_bounces` 寻找一/二跳反弹狙击角度，实现跨墙反弹击杀！
3. 就近抢占 `powerups`（尤其 `laser` 与 `shield`），拿到 `mine_charges > 0` 时在拐角或敌人追击路线上设 `special = 1` 埋雷。
4. 加上卡墙检测（连续多帧位移极小时倒车 + 转向脱困），避免被残墙拐角卡住。

请现在帮我编写这辆专属 AI 小车，直接保存到配置文件夹中（若无写权限则输出完整代码）并简述你的战术设计！
```
