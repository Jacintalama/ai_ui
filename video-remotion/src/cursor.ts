// Smart cursor-click: the planning AI marks the most relevant clickable element
// in a screenshot as { x, y } image fractions; the composition draws a mouse
// that slides to that point and clicks. All motion is a pure function of the
// scene progress, so the render stays deterministic.

export type ClickTarget = {x: number; y: number; label?: string};
export type ClickCursorState = {x: number; y: number; pulse: number};

const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
const smooth = (x: number) => {
  const t = clamp01(x);
  return t * t * (3 - 2 * t); // smoothstep
};

// Only the top ~72% of a screenshot is on screen — the browser frame's
// maxHeight + title bar clip the bottom. Targets below this should be skipped
// (no cursor) rather than rendered into the hidden region.
export const CURSOR_VISIBLE_MAX_Y = 0.72;

// The cursor slides in from a small offset toward the target (kept small so the
// move-in stays inside the frame's overflow:hidden box).
const START_DX = 0.06;
const START_DY = 0.08;

export function clickCursor(p: number, target: ClickTarget): ClickCursorState {
  const moveIn = smooth(clamp01((p - 0.05) / 0.45)); // 0 -> 1 over [0.05, 0.5]
  const x = clamp01(target.x + START_DX * (1 - moveIn));
  const y = clamp01(target.y + START_DY * (1 - moveIn));
  // Click pulse: ramps up at ~0.5, fades by ~0.82.
  const up = smooth(clamp01((p - 0.5) / 0.08));
  const down = smooth(clamp01((p - 0.66) / 0.16));
  const pulse = up * (1 - down);
  return {x, y, pulse};
}
