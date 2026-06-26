import {describe, expect, it} from "vitest";
import {clickCursor, CURSOR_VISIBLE_MAX_Y} from "./cursor";

describe("clickCursor", () => {
  const target = {x: 0.5, y: 0.3, label: "Contact"};

  it("is deterministic for the same progress + target", () => {
    expect(clickCursor(0.4, target)).toEqual(clickCursor(0.4, target));
  });

  it("ends on the target once the move-in completes", () => {
    const c = clickCursor(0.6, target); // move-in done by ~0.5
    expect(c.x).toBeCloseTo(target.x, 5);
    expect(c.y).toBeCloseTo(target.y, 5);
  });

  it("starts offset from the target (cursor approaches it)", () => {
    const c = clickCursor(0.0, target);
    expect(c.x).not.toBeCloseTo(target.x, 3);
  });

  it("fires a click pulse mid-scene, not at the start or end", () => {
    expect(clickCursor(0.15, target).pulse).toBeLessThan(0.2);
    expect(clickCursor(0.57, target).pulse).toBeGreaterThan(0.4);
    expect(clickCursor(0.95, target).pulse).toBeLessThan(0.2);
  });

  it("keeps the cursor inside the image box [0,1]", () => {
    for (const p of [0, 0.25, 0.5, 0.75, 1]) {
      for (const t of [{x: 0.02, y: 0.02, label: ""}, {x: 0.98, y: 0.7, label: ""}]) {
        const c = clickCursor(p, t);
        expect(c.x).toBeGreaterThanOrEqual(0);
        expect(c.x).toBeLessThanOrEqual(1);
        expect(c.y).toBeGreaterThanOrEqual(0);
        expect(c.y).toBeLessThanOrEqual(1);
      }
    }
  });

  it("exposes a visible-region cap for skipping below-fold targets", () => {
    expect(CURSOR_VISIBLE_MAX_Y).toBeGreaterThan(0.6);
    expect(CURSOR_VISIBLE_MAX_Y).toBeLessThan(0.8);
  });
});
