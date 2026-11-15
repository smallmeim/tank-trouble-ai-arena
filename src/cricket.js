/**
 * Pure Endless Cricket ("电子斗蛐蛐") constants, scoring rules,
 * safe random respawn selection, spectator speed gating, and HUD formatting.
 */

import { PLAYER_COLORS, ENEMY_COLORS } from "./config.js";

export const MELEE_COLORS = [
  PLAYER_COLORS[0],
  ...ENEMY_COLORS,
  "#ea580c",
  "#0d9488",
  "#334155",
  "#65a30d",
];

export const CRICKET = {
  respawnDelay: 10,
  minRespawnDelay: 0,
  maxRespawnDelay: 60,
  spawnInvuln: 3,
  speeds: [1, 2, 3],
};

/** Clamp user-configured respawn seconds into integer [minRespawnDelay, maxRespawnDelay]. */
export function normalizeRespawnDelay(value) {
  if (value === "" || value === null || value === undefined) return CRICKET.respawnDelay;
  const num = Number(value);
  if (!Number.isFinite(num)) return CRICKET.respawnDelay;
  return Math.min(CRICKET.maxRespawnDelay, Math.max(CRICKET.minRespawnDelay, Math.round(num)));
}

/** Compute physics substeps for the current frame; speed applies only inside py_melee active/settlement states. */
export function stepLoopCount({ isPyMelee, isActiveOrSettlement, cricketSpeed }) {
  if (!isPyMelee || !isActiveOrSettlement) return 1;
  return CRICKET.speeds.includes(cricketSpeed) ? cricketSpeed : 1;
}

/**
 * Resolve Endless Cricket score changes on tank death:
 * - Own bullet or scatter pellet hitting self -> -1 point on self
 * - Defeating an opponent (bullet/scatter/laser/mine) -> +1 point on killer
 * - Tank collision (killerIndex === -1) or non-bullet self-kill -> 0 points
 */
export function resolveCricketKillDelta({ victimIndex, killerIndex, weapon }) {
  if (victimIndex < 0) return { scorerIndex: -1, delta: 0, selfHit: false };
  if (killerIndex === victimIndex) {
    const isOwnBullet = weapon === "bullet" || weapon === "scatter";
    return isOwnBullet
      ? { scorerIndex: victimIndex, delta: -1, selfHit: true }
      : { scorerIndex: -1, delta: 0, selfHit: false };
  }
  if (killerIndex >= 0 && killerIndex !== victimIndex) {
    return { scorerIndex: killerIndex, delta: 1, selfHit: false };
  }
  return { scorerIndex: -1, delta: 0, selfHit: false };
}

/**
 * Pick a random grid cell center for respawn, preferring cells clear of
 * living tanks, active bullets, and mines.
 */
export function pickRespawnSpot({
  cols,
  rows,
  cellSize,
  avoidTanks = [],
  bullets = [],
  mines = [],
  rng = Math.random,
}) {
  const half = cellSize / 2;
  const cells = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const x = c * cellSize + half;
      const y = r * cellSize + half;
      let minTankDist = Infinity;
      for (const t of avoidTanks) {
        const d = Math.hypot(x - t.x, y - t.y);
        if (d < minTankDist) minTankDist = d;
      }
      const nearBullet = bullets.some((b) => Math.hypot(x - b.x, y - b.y) < cellSize * 0.65);
      const nearMine = mines.some((m) => Math.hypot(x - m.x, y - m.y) < cellSize * 0.85);
      cells.push({
        x,
        y,
        minTankDist,
        safeTank: minTankDist >= cellSize * 0.9,
        safeHazard: !nearBullet && !nearMine,
      });
    }
  }

  let pool = cells.filter((c) => c.safeTank && c.safeHazard);
  if (!pool.length) pool = cells.filter((c) => c.safeTank);
  if (!pool.length) {
    cells.sort((a, b) => b.minTankDist - a.minTankDist);
    pool = cells.slice(0, Math.min(3, cells.length));
  }
  const chosen = pool[Math.floor(rng() * pool.length)];
  return { x: chosen.x, y: chosen.y, a: rng() * Math.PI * 2 };
}

/** Format header clock and score-sorted tank entries for the bottom Cricket status pill. */
export function formatCricketStats({
  players,
  matchScores,
  cricketElapsed,
  cricketSpeed,
  cricketRespawnDelay = CRICKET.respawnDelay,
}) {
  const secs = Math.max(0, Math.floor(cricketElapsed || 0));
  const mm = String(Math.floor(secs / 60)).padStart(2, "0");
  const ss = String(secs % 60).padStart(2, "0");
  const respawnSec = normalizeRespawnDelay(cricketRespawnDelay);
  const header = `🦗 无限斗蛐蛐 ${mm}:${ss} · 复活${respawnSec}s · ${cricketSpeed}x`;

  const entries = players
    .map((p, i) => {
      const score = matchScores[i] ?? 0;
      const name = String(p.label || `P${i + 1}`).slice(0, 8);
      const wait = !p.alive && (p.respawnTimer ?? 0) > 0 ? `(↻${Math.ceil(p.respawnTimer)}s)` : "";
      const text = `${name} ${score}分${wait}`;
      return { color: p.color, score, alive: p.alive, text };
    })
    .sort((a, b) => b.score - a.score);

  return { header, entries };
}
