import {describe, expect, it} from "vitest";
import {cursorTrajectory, scaleCursorTrajectory, CURSOR_BASE_W, CURSOR_BASE_H} from "./cursor";

describe("cursorTrajectory", () => {
  it("is deterministic for the same scene index", () => {
    expect(cursorTrajectory(2)).toEqual(cursorTrajectory(2));
  });

  it("varies the cursor path between consecutive scenes", () => {
    // The bug: every scene replayed one identical sweep. Consecutive scenes must
    // differ in both start and end so it no longer looks copy-pasted.
    const a = cursorTrajectory(0);
    const b = cursorTrajectory(1);
    expect([a.x0, a.y0]).not.toEqual([b.x0, b.y0]);
    expect([a.x1, a.y1]).not.toEqual([b.x1, b.y1]);
  });

  it("keeps the cursor within the 1280x720 canvas", () => {
    for (let i = 0; i < 12; i++) {
      const t = cursorTrajectory(i);
      for (const x of [t.x0, t.x1]) expect(x).toBeGreaterThanOrEqual(0), expect(x).toBeLessThanOrEqual(1280);
      for (const y of [t.y0, t.y1]) expect(y).toBeGreaterThanOrEqual(0), expect(y).toBeLessThanOrEqual(720);
      expect(t.clickStart).toBeGreaterThan(0);
      expect(t.clickFall).toBeGreaterThan(t.clickStart);
    }
  });

  it("handles out-of-range indices without throwing (cycles)", () => {
    expect(() => cursorTrajectory(99)).not.toThrow();
    expect(cursorTrajectory(99)).toEqual(cursorTrajectory(99 % 6));
  });
});

describe("scaleCursorTrajectory", () => {
  it("is identity at the base 1280x720 canvas", () => {
    const t = cursorTrajectory(0);
    expect(scaleCursorTrajectory(t, CURSOR_BASE_W, CURSOR_BASE_H)).toEqual(t);
  });

  it("scales coordinates to a larger canvas, leaving click timing intact", () => {
    const t = cursorTrajectory(0);
    const s = scaleCursorTrajectory(t, CURSOR_BASE_W * 2, CURSOR_BASE_H * 2);
    expect(s.x0).toBe(t.x0 * 2);
    expect(s.y1).toBe(t.y1 * 2);
    expect(s.clickStart).toBe(t.clickStart); // timing is a progress fraction, not px
    expect(s.clickFall).toBe(t.clickFall);
  });
});
