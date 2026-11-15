// ============================================================
// py_bot_bridge.js — Python AI 代码小车桥接与可视化配置栏
// 让用户把其他 AI 生成的 bots/*.py 脚本分别指派给 2~6 辆不同小车，
// 并实时驱动 AbyssWhalen/tank-trouble 原生画布、道具、破墙和反弹系统。
// ============================================================

import { PLAYER_COLORS, ENEMY_COLORS, TANK } from "./config.js";
import { CRICKET, MELEE_COLORS, normalizeRespawnDelay } from "./cricket.js";

const registry = new Map(); // slotIdx -> PyBotController
let lastRoundSeq = -1;
let lastSentWallVer = -1;
let stepAccum = 0;
let tickCounter = 0;
let inFlight = false;
let latestMazePayload = null;

export class PyBotController {
  constructor(slotIndex, botId) {
    this.slotIndex = slotIndex;
    this.botId = botId;
    this.lastCmd = { turn: 0, move: 0 };
    this.pendingFire = false;
    this.pendingSpecial = false;
    this.mode = "Ready";
    registry.set(slotIndex, this);
  }

  applyResult(res) {
    if (!res) return;
    this.lastCmd.move = Number(res.move || 0);
    this.lastCmd.turn = Number(res.turn || 0);
    if (res.fire) this.pendingFire = true;
    if (res.special) this.pendingSpecial = true;
    if (res.mode) this.mode = String(res.mode);
  }

  reset() {
    this.lastCmd.move = 0;
    this.lastCmd.turn = 0;
    this.pendingFire = false;
    this.pendingSpecial = false;
    this.mode = "Respawn";
  }

  update(_dt, _world) {
    const fire = this.pendingFire;
    const special = this.pendingSpecial;
    this.pendingFire = false;
    this.pendingSpecial = false;
    return {
      move: this.lastCmd.move,
      turn: this.lastCmd.turn,
      fire,
      special,
    };
  }
}

export function createPyController(slotIndex, botId) {
  return new PyBotController(slotIndex, botId);
}

function serializeMaze(maze, wallVersion) {
  return {
    cols: maze.cols,
    rows: maze.rows,
    cellSize: maze.cellSize,
    cells: maze.cells,
    walls: maze.walls.map((w) => ({ x1: w.x1, y1: w.y1, x2: w.x2, y2: w.y2 })),
    wallVersion,
  };
}

export async function notifyPyRoundStart(roundId, maze, wallVersion = 1) {
  lastRoundSeq = roundId;
  lastSentWallVer = wallVersion;
  stepAccum = 0.032; // fire an AI poll right on the first frame
  tickCounter = 0;
  latestMazePayload = serializeMaze(maze, wallVersion);
  try {
    await fetch("/api/ai_reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ round_id: roundId, maze: latestMazePayload }),
    });
  } catch (_) {
    // Ignore when static file mode without Python backend
  }
}

export function stepPyBridge(dt, world, players, roundId, wallVersion) {
  const pySlots = [];
  for (let i = 0; i < players.length; i++) {
    const ctrl = players[i]?.ai;
    if (ctrl instanceof PyBotController && players[i].alive) {
      pySlots.push({ slot: i, bot_id: ctrl.botId });
    }
  }
  if (!pySlots.length) return;

  tickCounter++;
  stepAccum += dt;
  if (inFlight || stepAccum < 0.033) return;
  stepAccum = 0;
  inFlight = true;

  const tankOwnerMap = new Map();
  players.forEach((p, idx) => tankOwnerMap.set(p.tank, idx));

  const payload = {
    round_id: roundId,
    tick: tickCounter,
    wall_version: wallVersion,
    requests: pySlots,
    tanks: players.map((p, idx) => ({
      id: idx,
      name: p.label,
      x: p.tank.x,
      y: p.tank.y,
      angle: p.tank.angle,
      alive: p.alive,
      cooldown: p.tank.cooldown,
      shield: !!p.tank.shield,
      shieldTimer: p.tank.shieldTimer || 0,
      invulnTimer: p.tank.invulnTimer || 0,
      scatterShots: p.tank.scatterShots || 0,
      laserShots: p.tank.laserShots || 0,
      mineCharges: p.tank.mineCharges || 0,
      maxAlive: 5 + (p.tank.mods?.maxAlive || 0),
    })),
    bullets: (world.bullets || []).filter((b) => !b.dead).map((b) => ({
      owner: tankOwnerMap.get(b.owner) ?? -1,
      x: b.x,
      y: b.y,
      vx: b.vx,
      vy: b.vy,
      age: b.age || 0,
      bounces: b.bounces || 0,
    })),
    powerups: (world.powerups || []).filter((pw) => !pw.taken).map((pw) => ({
      type: pw.type,
      x: pw.x,
      y: pw.y,
    })),
    mines: (world.mines || []).filter((m) => !m.exploded).map((m) => ({
      owner: tankOwnerMap.get(m.owner) ?? -1,
      x: m.x,
      y: m.y,
      armed: !!m.armed,
    })),
  };

  if (wallVersion !== lastSentWallVer && world.maze) {
    latestMazePayload = serializeMaze(world.maze, wallVersion);
    payload.walls = latestMazePayload.walls;
    payload.cells = latestMazePayload.cells;
    lastSentWallVer = wallVersion;
  }

  fetch("/api/ai_step", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      if (!data) return;
      if (data.need_maze && world.maze) {
        notifyPyRoundStart(roundId, world.maze, wallVersion);
        return;
      }
      if (data.controls) {
        for (const [slotStr, res] of Object.entries(data.controls)) {
          const ctrl = registry.get(Number(slotStr));
          if (ctrl && roundId === lastRoundSeq) ctrl.applyResult(res);
        }
      }
    })
    .catch(() => {})
    .finally(() => {
      inFlight = false;
    });
}

// ============================================================
// UI Overlay: 顶部 AI 代码小车配置 bar + 抽屉 + Prompt 复制窗
// ============================================================
export function setupPyBridgeUI({ onStartMelee, onStartCricket, onCycleSpeed, onChangeRespawn }) {
  if (typeof document === "undefined") return;

  const root = document.getElementById("py-arena-ui");
  if (!root) return;

  let roster = { py_bots: [], builtin: [], errors: [], bots_dir: "bots/" };
  let tankCount = 4;
  let selectedControllers = [
    "py:example_bouncer",
    "py:example_dodger",
    "py:example_berserker",
    "py:example_crate_hunter",
    "github:hard",
    "human1",
  ];
  let drawerOpen = true;

  function controllerLabel(id) {
    const py = roster.py_bots.find((b) => b.id === id);
    if (py) return py.name;
    const bi = roster.builtin.find((b) => b.id === id);
    if (bi) {
      if (id === "human1") return "玩家1(WASD)";
      if (id === "human2") return "玩家2(方向键)";
      return bi.name;
    }
    return id;
  }

  function blurActive() {
    if (document.activeElement && typeof document.activeElement.blur === "function") {
      document.activeElement.blur();
    }
  }

  function buildSlotsPayload() {
    const out = [];
    for (let i = 0; i < tankCount; i++) {
      const cid = selectedControllers[i] || "github:normal";
      out.push({
        controller: cid,
        label: controllerLabel(cid),
      });
    }
    return out;
  }

  function buildAllBotsPayload() {
    const out = roster.py_bots.map((b) => ({ controller: b.id, label: b.name }));
    if (out.length >= 2) return out;
    for (const s of buildSlotsPayload()) {
      if (out.length >= 2) break;
      if (!out.some((x) => x.controller === s.controller)) out.push(s);
    }
    return out.length >= 2 ? out : buildSlotsPayload();
  }

  function renderUI() {
    const countSel = document.getElementById("py-tank-count");
    const slotsWrap = document.getElementById("py-slots-wrap");
    const drawer = document.getElementById("py-drawer");
    const errEl = document.getElementById("py-bot-err");
    if (!countSel || !slotsWrap || !drawer) return;

    drawer.classList.toggle("hidden", !drawerOpen);
    countSel.value = String(tankCount);

    if (errEl) {
      errEl.textContent = roster.errors?.length
        ? `加载失败: ${roster.errors.map((e) => e.file).join(", ")}`
        : `已加载 ${roster.py_bots.length} 个 bots/*.py 脚本`;
    }

    const pyOpts = roster.py_bots
      .map((b) => `<option value="${b.id}">${b.name} (${b.file_name})</option>`)
      .join("");
    const biOpts = roster.builtin
      .map((b) => `<option value="${b.id}">${b.name}</option>`)
      .join("");

    let html = "";
    for (let i = 0; i < tankCount; i++) {
      const col = MELEE_COLORS[i % MELEE_COLORS.length];
      const cur = selectedControllers[i] || "github:normal";
      html += `
        <div class="slot-row">
          <span class="slot-dot" style="background:${col}"></span>
          <span class="slot-title">${i + 1}号车</span>
          <select class="slot-select" data-slot="${i}">
            <optgroup label="外部 AI 脚本 (bots/*.py)">${pyOpts}</optgroup>
            <optgroup label="玩家手操 & 原版内置 AI">${biOpts}</optgroup>
          </select>
        </div>
      `;
    }
    slotsWrap.innerHTML = html;

    slotsWrap.querySelectorAll(".slot-select").forEach((sel) => {
      const idx = Number(sel.getAttribute("data-slot"));
      const val = selectedControllers[idx];
      if ([...sel.options].some((o) => o.value === val)) sel.value = val;
      else if (roster.py_bots[idx]) {
        selectedControllers[idx] = roster.py_bots[idx].id;
        sel.value = selectedControllers[idx];
      }
      sel.addEventListener("change", () => {
        selectedControllers[idx] = sel.value;
        blurActive();
      });
    });
  }

  async function refreshBots(autoFillDefaults = false) {
    try {
      const resp = await fetch("/api/reload_bots", { method: "POST" });
      if (!resp.ok) return;
      roster = await resp.json();
      if (autoFillDefaults && roster.py_bots.length) {
        // Put discovered bots on slots nicely by default
        const defaults = roster.py_bots.map((b) => b.id);
        for (let i = 0; i < 6; i++) {
          if (i < defaults.length) selectedControllers[i] = defaults[i];
          else if (i === defaults.length) selectedControllers[i] = "github:hard";
          else selectedControllers[i] = "human1";
        }
        tankCount = Math.min(6, Math.max(2, defaults.length));
      }
      renderUI();
    } catch (_) {
      // Static without Flask
    }
  }

  document.getElementById("py-toggle-drawer")?.addEventListener("click", () => {
    drawerOpen = !drawerOpen;
    renderUI();
    blurActive();
  });

  document.getElementById("py-tank-count")?.addEventListener("change", (e) => {
    tankCount = Math.max(2, Math.min(6, Number(e.target.value) || 4));
    renderUI();
    blurActive();
  });

  document.getElementById("py-start-btn")?.addEventListener("click", () => {
    drawerOpen = false;
    renderUI();
    onStartMelee(buildSlotsPayload());
    blurActive();
  });

  document.getElementById("py-cricket-btn")?.addEventListener("click", async () => {
    drawerOpen = false;
    renderUI();
    await refreshBots(false);
    onStartCricket?.(buildAllBotsPayload(), { respawnDelay: respawnSec });
    blurActive();
  });

  const RESPAWN_STORAGE_KEY = "py_cricket_respawn_sec";
  let respawnSec = CRICKET.respawnDelay;
  try {
    const saved = localStorage.getItem(RESPAWN_STORAGE_KEY);
    if (saved !== null) respawnSec = normalizeRespawnDelay(saved);
  } catch (_) {}

  const respawnInput = document.getElementById("py-respawn-input");
  function applyRespawnSec(nextVal, commitInput = true) {
    respawnSec = normalizeRespawnDelay(nextVal);
    if (respawnInput && commitInput) respawnInput.value = String(respawnSec);
    try {
      localStorage.setItem(RESPAWN_STORAGE_KEY, String(respawnSec));
    } catch (_) {}
    onChangeRespawn?.(respawnSec);
  }
  if (respawnInput) {
    respawnInput.value = String(respawnSec);
    respawnInput.addEventListener("input", () => {
      if (respawnInput.value === "") return;
      applyRespawnSec(respawnInput.value, false);
    });
    respawnInput.addEventListener("change", () => {
      applyRespawnSec(respawnInput.value, true);
      blurActive();
    });
    respawnInput.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Enter" || e.key === "Escape") {
        applyRespawnSec(respawnInput.value, true);
        blurActive();
      }
    });
    respawnInput.addEventListener("keyup", (e) => e.stopPropagation());
  }
  document.getElementById("py-respawn-dec")?.addEventListener("click", () => {
    applyRespawnSec(respawnSec - 1, true);
    blurActive();
  });
  document.getElementById("py-respawn-inc")?.addEventListener("click", () => {
    applyRespawnSec(respawnSec + 1, true);
    blurActive();
  });
  onChangeRespawn?.(respawnSec);

  let cricketSpeedIdx = 0;
  const speedBtn = document.getElementById("py-speed-btn");
  speedBtn?.addEventListener("click", () => {
    cricketSpeedIdx = (cricketSpeedIdx + 1) % CRICKET.speeds.length;
    const speed = CRICKET.speeds[cricketSpeedIdx];
    speedBtn.textContent = `倍速: ${speed}x`;
    speedBtn.classList.toggle("py-btn-speed-active", speed > 1);
    onCycleSpeed?.(speed);
    blurActive();
  });

  document.getElementById("py-reload-btn")?.addEventListener("click", async () => {
    await refreshBots(false);
    blurActive();
  });

  document.getElementById("py-open-dir-btn")?.addEventListener("click", async () => {
    await fetch("/api/open_bots_dir", { method: "POST" }).catch(() => {});
    blurActive();
  });

  const modal = document.getElementById("py-prompt-modal");
  const txt = document.getElementById("py-prompt-text");
  const copyMsg = document.getElementById("py-copy-msg");

  document.getElementById("py-prompt-btn")?.addEventListener("click", async () => {
    if (modal) modal.classList.remove("hidden");
    if (copyMsg) copyMsg.textContent = "";
    if (txt && !txt.value) {
      try {
        const r = await fetch("/api/prompt_guide");
        if (r.ok) txt.value = (await r.json()).markdown || "";
      } catch (_) {}
    }
    blurActive();
  });

  document.getElementById("py-close-prompt")?.addEventListener("click", () => {
    modal?.classList.add("hidden");
    blurActive();
  });

  document.getElementById("py-copy-prompt")?.addEventListener("click", async () => {
    if (!txt) return;
    try {
      await navigator.clipboard.writeText(txt.value);
      if (copyMsg) copyMsg.textContent = "已复制！去发给其他 AI 生成 .py 放到 bots/ 里吧";
    } catch (_) {
      txt.select();
      document.execCommand("copy");
      if (copyMsg) copyMsg.textContent = "已复制！";
    }
    blurActive();
  });

  refreshBots(true);
}
