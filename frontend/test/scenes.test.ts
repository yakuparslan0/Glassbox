import { describe, expect, it } from "vitest";
import { holdMs, jumpScene, sceneIndexAt } from "../src/lib/scenes";

const scenes = [
  { from_step: 1, to_step: 5, text: "a" },
  { from_step: 6, to_step: 20, text: "b" },
  { from_step: 21, to_step: 30, text: "c" },
];

describe("scene navigation", () => {
  it("finds the scene a step belongs to", () => {
    expect(sceneIndexAt(scenes, 1)).toBe(0);
    expect(sceneIndexAt(scenes, 20)).toBe(1);
    expect(sceneIndexAt(scenes, 99)).toBe(-1);
  });
  it("Shift+Right goes to the next scene start and stops at the last", () => {
    expect(jumpScene(scenes, 3, 1)).toBe(6);
    expect(jumpScene(scenes, 25, 1)).toBe(21);
  });
  it("Shift+Left restarts the current scene first, then goes to the previous one", () => {
    expect(jumpScene(scenes, 10, -1)).toBe(6);
    expect(jumpScene(scenes, 6, -1)).toBe(1);
    expect(jumpScene(scenes, 1, -1)).toBe(1);
  });
  it("has no target without scenes", () => {
    expect(jumpScene([], 3, 1)).toBeNull();
  });
  it("holds longer for longer narration, shorter at higher speed, within bounds", () => {
    expect(holdMs("x", 1)).toBe(1500);
    expect(holdMs("x".repeat(1000), 1)).toBe(8000);
    expect(holdMs("x".repeat(100), 1)).toBe(4500);
    expect(holdMs("x".repeat(100), 4)).toBe(1125);
  });
});
