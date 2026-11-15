# 坦克回廊 · AI 代码混战版 | Tank Trouble AI Code Arena

基于开源项目 [`AbyssWhalen/tank-trouble`](https://github.com/AbyssWhalen/tank-trouble) 扩展改造的多模型 Python AI 小车同场混战版。

> **AI Code Arena Extension**: Built on top of [`AbyssWhalen/tank-trouble`](https://github.com/AbyssWhalen/tank-trouble) (MIT License) with a Flask + Python bot bridge (`server.py`, `py_maze_helpers.py`, `bots/*.py`) so 2–6 AI-written Python tank scripts can battle each other alongside human players and built-in JS AIs.

---

## 新手下载即玩教程（Windows 五步开战）

### 第 1 步：准备 Python 环境（只需一次）
- 如果电脑尚未安装 Python，前往 [python.org/downloads](https://www.python.org/downloads/) 下载安装 Python 3.10 或更高版本。
- **安装界面底部务必勾选 `Add python.exe to PATH`**，然后一路点击 `Install Now`。

### 第 2 步：下载游戏压缩包
1. 打开本仓库右侧（或顶部）的 **[Releases 页面](https://github.com/smallmeim/tank-trouble-ai-arena/releases/latest)**。
2. 在 `Assets` 栏点击下载 **`tank-trouble-ai-arena-v1.1.0.zip`**（不要只下载 `Source code` 源码，直接用打包好的压缩包即可，或者下载任意最新 `.zip`）。
3. 右键下载好的压缩包，选择 **「全部解压缩」** 到电脑任意文件夹（例如 `D:\Games\tank-trouble-ai-arena`）。

### 第 3 步：一键启动（可选生成桌面图标）
- 进入解压后的文件夹，**双击运行 `launch_arena.bat`**：
  - 首次运行会自动检测并安装所需的 `flask` 依赖；
  - 几秒后会自动启动本地服务并打开浏览器进入游戏页面（**游玩期间请保持弹出的黑色终端窗口开启**，关闭它即停止服务）。
- **想在桌面放图标？** 双击运行一次同目录下的 **`create_desktop_shortcut.bat`**，桌面上就会多出一个带坦克图标的 **`坦克回廊 AI混战`** 快捷方式，以后直接双击桌面图标就能开玩！

### 第 4 步：选车 & 开战
- 网页顶部的 **「AI 代码混战」** 配置栏默认已加载 `bots/` 文件夹中的 6 位 AI 选手：
  - `6Astra`（[bots/6astra.py](bots/6astra.py)）
  - `Opus 5.5`（[bots/opus_5_5.py](bots/opus_5_5.py)）
  - `DeepSeek`（[bots/deepseek.py](bots/deepseek.py)）
  - `6.1 Sol`（[bots/6_1_sol.py](bots/6_1_sol.py)）
  - `豆包`（[bots/doubao.py](bots/doubao.py)）
  - `Argon`（[bots/argon.py](bots/argon.py)）
- 你可以自由选择 **2 ~ 6 辆车**，给每辆车指派不同 AI 脚本，也可以混入 **玩家1 (`WASD + 空格 + E`)** / **玩家2 (`方向键 + Enter + 右Shift`)** 亲自下场，点 **「▶ 立即开战」** 即可开打！

### 第 5 步：让其他 AI 写新小车加赛
1. 点击网页顶部的 **「复制 AI 写车提示词」** → **「一键复制提示词」**（系统会自动把当前电脑的 `bots/` 文件夹真实路径填进提示词里）。
2. 把提示词发给任意 AI / 编程助手生成 `.py` 脚本并放进 `bots/` 文件夹。
3. 回到游戏网页点 **「🔄 刷新 bots/」** 即可热加载上场（无需重启游戏）。

---

## 本版新增混战规则亮点

- **两车碰撞双方死亡**：在对战与 AI 混战模式下，两辆存活坦克发生车体接触（中心距 `<= 32 px`）时**双方均会直接爆炸死亡**，且**护盾无法免除撞死**。
- **动态破墙与四种道具**：延续原版散射、护盾、反弹激光、隐形地雷与内墙炸毁同步，Python AI 通过 `helpers` 实时获取破墙后的最短路径与反弹轨迹。
- **开发者校验命令**：`node scripts/smoke.mjs`、`node tests/test_collision_rule.mjs`、`python -m unittest discover -s tests -v`。

---

# 坦克回廊 | Tank Trouble (原版说明)

本地多人对战坦克小游戏，迷宫随机生成 + 子弹反弹 + 人机 AI。

Local multiplayer tank combat game with procedural maze generation, bullet ricochet, and AI opponent.

---

## 游戏特色 | Features

- 🎮 **双人对战 + 人机 + 挑战闯关 + 波次生存** | PvP, PvE, single-player challenge campaign (8 levels) & endless wave survival
- 🗺️ **随机迷宫·三种风格轮换** | Procedural mazes in 3 styles (sparse grid / mirrored arena / rooms & corridors) × 3 size tiers
- 💥 **子弹反弹物理** | Realistic bullet ricochet off walls
- 🎁 **四种道具·菜单可自选组合** | 4 power-ups, individually toggleable:
  - 散射（扇形三连发） | Scatter shot
  - 护盾（挡一发即碎） | One-hit shield
  - 激光（瞬时射线沿墙反弹 + 预瞄虚线） | Bouncing laser with aim preview
  - 地雷（独立道具键布雷，布防后隐形） | Stealth mines on a dedicated key
- 🧱 **可破坏地形** | Destructible terrain: bullets erode inner walls shot by shot, mines blast them instantly (menu-toggleable)
- 🤖 **三档难度 AI** | AI with Easy/Normal/Hard difficulty levels
  - 智能躲弹 + 拦截预判射击 | Adaptive dodging + predictive aim
  - 近战反打决策 | Close-combat counter-attack logic
  - 识别对手道具调整策略、绕雷寻路、边打边布雷 | Reads opponent power-ups, avoids mines, drops mines while fighting
  - 躲对手激光预瞄线（全程弹道含反弹段，绕线走位） | Evades the opponent's laser aim-line (full path incl. bounces)
  - 困难档:跳弹吊射、反弹激光狙 | Hard: bank shots & ricochet laser snipes
- ⌨️ **键位自定义** | Rebindable controls (persisted locally)
- 🖥️ **F11 全屏** | Fullscreen toggle with state memory
- ✨ **手感特效** | Screen shake, muzzle flash, bullet trails & explosions
- 🔊 **程序合成音效·零素材文件** | Procedurally synthesized SFX (Web Audio, zero asset files), mute toggle persisted
- 🎯 **局胜制·先到 5 分赢下整场** | First to 5 rounds wins the match
- ♾️ **波次生存·一条命打到底** | Endless wave survival: one life, waves of AI that grow in count & skill, forced supply drop between waves, arena remapped (and sized up) every 5 waves — your bullet holes and mines carry over inside a chapter; personal best persisted
- ⏱️ **开场倒计时 + 击杀慢动作 + 战绩统计** | Round countdown, kill slow-mo & persistent stats
- 📟 **HUD 武器状态指示** | On-HUD weapon & shield badges with ammo counts
- 📐 **自适应窗口** | Responsive viewport scaling

---

## 按键操作 | Controls

默认键位如下，可在菜单左下角 ⚙ 设置面板的「键位设置」里自定义（重启后保留）。

Default bindings below — rebind them via ⚙ Settings → 键位设置 at the bottom-left of the menu (persisted across restarts).

### 玩家 1 | Player 1
- **移动** | Move: `W` `A` `S` `D`
- **开炮** | Fire: `Space`
- **放道具** | Deploy (mines): `E`

### 玩家 2 | Player 2
- **移动** | Move: `↑` `←` `↓` `→`
- **开炮** | Fire: `Enter`
- **放道具** | Deploy (mines): `右Shift | Right Shift`

### 通用 | Common
- **暂停 / 返回菜单** | Pause / back to menu: `Esc`
- **结算时立即开下一局** | Next round instantly (on round-over): `R`
- **全屏** | Fullscreen: `F11`

---

## 下载与安装 | Download & Installation

### Windows 用户 | For Windows Users

前往 [Releases](https://github.com/AbyssWhalen/tank-trouble/releases) 页面下载最新版 `.exe` 安装包，双击运行即可。

Go to the [Releases](https://github.com/AbyssWhalen/tank-trouble/releases) page, download the latest `.exe` installer, and run it.

### 从源码运行 | Run from Source

需要 Node.js 18+ 和 npm。

Requires Node.js 18+ and npm.

```bash
# 克隆仓库 | Clone repository
git clone https://github.com/AbyssWhalen/tank-trouble.git
cd tank-trouble

# 安装依赖 | Install dependencies
npm install

# 启动游戏 | Launch game
npm start
```

---

## 开发 | Development

```bash
# 开发模式启动（没有 watcher，改完源码重启窗口生效）| Dev mode (no watcher; restart the window to pick up source changes)
npm start

# 打包 Windows 安装包 | Build Windows installer
npm run dist
```

### 项目结构 | Project Structure

```
tank-trouble/
├── src/              # 游戏逻辑模块 | Game logic modules
│   ├── main.js       # 主循环 + 状态机 | Main loop & state machine
│   ├── ui.js         # 菜单/HUD/浮层 | Menus, HUD & overlays
│   ├── ai.js         # AI 控制器 | AI controller
│   ├── levels.js     # 挑战关卡表 | Challenge campaign levels
│   ├── waves.js      # 波次曲线 | Endless wave curve
│   ├── maze.js       # 迷宫生成 | Maze generation
│   ├── tank.js       # 坦克物理 | Tank physics
│   ├── bullet.js     # 子弹 + 反弹 | Bullet & ricochet
│   ├── laser.js      # 激光射线 | Bouncing laser
│   ├── powerup.js    # 道具刷新 | Power-up spawning
│   ├── mine.js       # 地雷 | Mines
│   ├── audio.js      # 程序合成音效 | Procedural SFX (Web Audio)
│   ├── stats.js      # 战绩统计 | Match stats persistence
│   ├── settings.js   # 设置持久化 | Settings persistence
│   ├── collision.js  # 碰撞检测 | Collision detection
│   └── effects.js    # 视觉特效 | Visual effects
├── scripts/          # 冒烟测试 + AI 对打/关卡/波次跑分 | Smoke tests, AI arena, level & wave scorers (npm run smoke / arena)
├── electron/         # Electron 主进程 | Electron main process
└── index.html        # 渲染进程入口 | Renderer entry
```

---

## 技术栈 | Tech Stack

- **渲染引擎** | Rendering: HTML5 Canvas + Vanilla JavaScript (ES Modules)
- **桌面框架** | Desktop: Electron
- **打包工具** | Build: electron-builder

零运行时依赖，纯前端实现。

Zero runtime dependencies, pure frontend implementation.

---

## 开发日志 | Development Log

- **阶段 0-4**：坦克移动、迷宫生成、子弹反弹、双人对战
- **阶段 5**：回合制计分 + 三档地图自适应缩放
- **阶段 6**：人机模式 + AI（BFS 寻路、八向躲弹、拦截预判、近战反打）+ 爆炸特效
- **阶段 7**：Windows 安装包打包
- **阶段 8**：道具系统（散射 / 护盾）+ AI 识别对手道具 + 暂停功能
- **阶段 9**：界面层重构 + 键位自定义（本地持久化）+ F11 全屏
- **阶段 10**：护盾改「挡一发即碎」+ 屏幕震动 / 炮口火光 / 子弹拖尾
- **阶段 11**：新道具穿墙弹 & 地雷 + AI 避雷 / 布雷
- **阶段 12**：独立道具键 + 激光射线（预瞄虚线）替换穿墙弹 + 隐形地雷 + 道具自选组合 + 冒烟测试
- **阶段 13**：AI 强度打磨——捡道具决策修正、激光精确运用、困难档跳弹吊射，headless 对战验证调参
- **阶段 14**：AI 激光预瞄线防守——消费全程弹道（含反弹段）绕线走位、压线即避；AI 对打竞技场收进仓库（npm run arena）
- **阶段 15**：程序合成音效系统（Web Audio 零素材，12 类事件音 + 菜单静音开关持久化）+ v0.2.0 发布
- **阶段 16**：HUD 武器/护盾徽章（剩余次数 + 到期闪烁）+ 局胜制（先到 5 分整场结算，可再来一场）
- **阶段 17**：可破坏内墙——地雷爆炸炸碎波及圈内墙（外墙不破），地形随战斗演变；菜单「地形」开关
- **阶段 18**：子弹磨墙——内墙带耐久，子弹逐发侵蚀（墙渐淡示血量）归零碎掉；破坏从此每回合可见
- **阶段 19**：主菜单瘦身——难度/道具/地形/音效与键位入口全部收进 ⚙ 设置浮层，首屏只留模式选择
- **阶段 20**：表现层打磨——开场 3-2-1-GO 倒计时（冻结双方，修 AI 抢先手）+ 击杀慢动作 + 战绩统计（命中率/最爱武器/连胜，本地持久化）
- **阶段 21**：地图生成器三风格——稀疏格栅 / 180° 对称竞技场（绝对公平）/ 房间走廊（BSP），每回合随机轮换
- **阶段 22**：AI 行为大修——修复隔墙对撞死锁（半径感知导航）、十余项决策 bug；hard 档学会磨墙开路；卡住次数降一个数量级
- **阶段 23**：挑战关卡模式——单人闯关 8 关（1v2 车轮战/激光狙击/限时歼灭/生存），顺序解锁，进度持久化
- **阶段 24**：无尽波次生存——一条命打无限波，配额/同屏双层调度（同屏最多 3 敌），AI 难度随波次从简单滑向困难，每波强制补给，每 5 波换图升档（第 11 波起上 large 大图），破洞与雷阵在章节内跨波保留，历史最高（波次/击杀）持久化

---

## 许可 | License

MIT License

---

## 致谢 | Credits

灵感来源于经典 Flash 游戏 [Tank Trouble](https://tanktrouble.com/)。

Inspired by the classic Flash game [Tank Trouble](https://tanktrouble.com/).

代码与素材完全原创。

All code and assets are original.
