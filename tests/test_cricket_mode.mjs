import assert from "node:assert/strict";
import {
  CRICKET,
  MELEE_COLORS,
  normalizeRespawnDelay,
  stepLoopCount,
  resolveCricketKillDelta,
  pickRespawnSpot,
  formatCricketStats,
} from "../src/cricket.js";
import { Tank } from "../src/tank.js";

// 1) Color palette supports > 6 bots cleanly without duplicates
assert.ok(MELEE_COLORS.length >= 10);
assert.equal(new Set(MELEE_COLORS).size, MELEE_COLORS.length);

// 2) Spectator speed gating: applies only inside py_melee active states
assert.equal(stepLoopCount({ isPyMelee: false, isActiveOrSettlement: true, cricketSpeed: 3 }), 1);
assert.equal(stepLoopCount({ isPyMelee: true, isActiveOrSettlement: false, cricketSpeed: 3 }), 1);
assert.equal(stepLoopCount({ isPyMelee: true, isActiveOrSettlement: true, cricketSpeed: 2 }), 2);
assert.equal(stepLoopCount({ isPyMelee: true, isActiveOrSettlement: true, cricketSpeed: 3 }), 3);
assert.equal(stepLoopCount({ isPyMelee: true, isActiveOrSettlement: true, cricketSpeed: 99 }), 1);

// 3) Deathmatch scoring rules (+1 enemy kill, -1 own bullet self-hit, 0 collision/mine-self)
assert.deepEqual(
  resolveCricketKillDelta({ victimIndex: 1, killerIndex: 0, weapon: "bullet" }),
  { scorerIndex: 0, delta: 1, selfHit: false },
);
assert.deepEqual(
  resolveCricketKillDelta({ victimIndex: 1, killerIndex: 2, weapon: "laser" }),
  { scorerIndex: 2, delta: 1, selfHit: false },
);
assert.deepEqual(
  resolveCricketKillDelta({ victimIndex: 1, killerIndex: 3, weapon: "mine" }),
  { scorerIndex: 3, delta: 1, selfHit: false },
);
assert.deepEqual(
  resolveCricketKillDelta({ victimIndex: 2, killerIndex: 2, weapon: "bullet" }),
  { scorerIndex: 2, delta: -1, selfHit: true },
);
assert.deepEqual(
  resolveCricketKillDelta({ victimIndex: 2, killerIndex: 2, weapon: "scatter" }),
  { scorerIndex: 2, delta: -1, selfHit: true },
);
assert.deepEqual(
  resolveCricketKillDelta({ victimIndex: 2, killerIndex: 2, weapon: "mine" }),
  { scorerIndex: -1, delta: 0, selfHit: false },
);
assert.deepEqual(
  resolveCricketKillDelta({ victimIndex: 1, killerIndex: -1, weapon: "collision" }),
  { scorerIndex: -1, delta: 0, selfHit: false },
);

// 4) Safe random respawn selection avoids tanks, bullets, mines
{
  const spot = pickRespawnSpot({
    cols: 2,
    rows: 1,
    cellSize: 96,
    avoidTanks: [{ x: 48, y: 48 }],
    bullets: [],
    mines: [],
    rng: () => 0.25,
  });
  // Only cell (1,0) center=(144,48) is >= 0.9*96 away from (48,48)
  assert.equal(spot.x, 144);
  assert.equal(spot.y, 48);

  const avoidHazard = pickRespawnSpot({
    cols: 2,
    rows: 1,
    cellSize: 96,
    avoidTanks: [],
    bullets: [{ x: 48, y: 48 }],
    mines: [],
    rng: () => 0.1,
  });
  assert.equal(avoidHazard.x, 144);
  assert.equal(avoidHazard.y, 48);
}

// 5) Respawn delay is 10s + Tank.resetAt grants spawn invulnerability canceled immediately on attack
assert.equal(CRICKET.respawnDelay, 10);
assert.ok(CRICKET.spawnInvuln > 0);
{
  const tank = new Tank(10, 10, 0, "#1ba39c");
  const origRef = tank;
  tank.alive = false;
  tank.shield = true;
  tank.scatterShots = 2;

  tank.resetAt(240, 144, 1.0, CRICKET.spawnInvuln);
  assert.equal(tank, origRef);
  assert.equal(tank.alive, true);
  assert.equal(tank.x, 240);
  assert.equal(tank.y, 144);
  assert.equal(tank.shield, false);
  assert.equal(tank.scatterShots, 0);
  assert.equal(tank.invulnTimer, CRICKET.spawnInvuln);

  // Ticking without attacking preserves remaining invulnTimer smoothly
  tank.update(0.5, [], { turn: 0, move: 0 });
  assert.ok(Math.abs(tank.invulnTimer - (CRICKET.spawnInvuln - 0.5)) < 1e-6);

  // Non-attack frame preserves invuln
  tank.tryFire([], false, []);
  assert.ok(tank.invulnTimer > 0);

  // Firing immediately cancels invulnerability
  const shot = tank.tryFire([], true, []);
  assert.equal(shot.bullets.length, 1);
  assert.equal(tank.invulnTimer, 0);

  // Deploying a mine also immediately cancels invulnerability
  tank.resetAt(240, 144, 0, CRICKET.spawnInvuln);
  tank.applyPowerup("mine");
  const deployed = tank.tryDeploy(true, []);
  assert.ok(deployed !== null);
  assert.equal(tank.invulnTimer, 0);
}

// 5.5) Adjustable respawn delay normalization clamps cleanly [0..60]
assert.equal(normalizeRespawnDelay(10), 10);
assert.equal(normalizeRespawnDelay("5"), 5);
assert.equal(normalizeRespawnDelay(0), 0);
assert.equal(normalizeRespawnDelay(-3), 0);
assert.equal(normalizeRespawnDelay(99), 60);
assert.equal(normalizeRespawnDelay(4.6), 5);
assert.equal(normalizeRespawnDelay("abc"), CRICKET.respawnDelay);
assert.equal(normalizeRespawnDelay(""), CRICKET.respawnDelay);

// 6) Leaderboard formatting sorts by score desc (supporting negative & respawn countdown)
{
  const fmt = formatCricketStats({
    players: [
      { label: "6Astra", color: "#f00", alive: false, respawnTimer: 6.2 },
      { label: "DeepSeek", color: "#0f0", alive: true, respawnTimer: 0 },
      { label: "Argon", color: "#00f", alive: true, respawnTimer: 0 },
    ],
    matchScores: [-1, 3, 1],
    cricketElapsed: 75,
    cricketSpeed: 2,
    cricketRespawnDelay: 5,
  });
  assert.equal(fmt.header, "🦗 无限斗蛐蛐 01:15 · 复活5s · 2x");
  assert.equal(fmt.entries[0].text, "DeepSeek 3分");
  assert.equal(fmt.entries[1].text, "Argon 1分");
  assert.equal(fmt.entries[2].text, "6Astra -1分(↻7s)");
}

console.log("test_cricket_mode: all assertions passed");
