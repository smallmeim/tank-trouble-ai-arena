import assert from "node:assert/strict";
import { findCollidingIndices } from "../src/collision.js";
import { TANK } from "../src/config.js";

const D = TANK.radius * 2; // 32 px

// 1) Just above touching distance -> no collision
{
  const hit = findCollidingIndices(
    [
      { x: 100, y: 100 },
      { x: 100 + D + 0.01, y: 100 },
    ],
    D,
  );
  assert.equal(hit.size, 0, "Expected no collision slightly beyond 2*radius");
}

// 2) Exact touching boundary -> both indices collide
{
  const hit = findCollidingIndices(
    [
      { x: 100, y: 100 },
      { x: 100 + D, y: 100 },
    ],
    D,
  );
  assert.deepEqual([...hit].sort(), [0, 1], "Expected boundary touch to collide both tanks");
}

// 3) Multi-tank pile: 0 overlaps 1, 2 overlaps 1, 3 is far away
{
  const hit = findCollidingIndices(
    [
      { x: 100, y: 100 },
      { x: 118, y: 100 },
      { x: 140, y: 100 },
      { x: 300, y: 300 },
    ],
    D,
  );
  assert.deepEqual([...hit].sort(), [0, 1, 2], "Expected all touching tanks in chain to die while far tank survives");
}

console.log("test_collision_rule: all assertions passed");
