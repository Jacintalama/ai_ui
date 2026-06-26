// Per-scene cursor trajectories for the cursor_click preset.
//
// The original composition hardcoded one cursor path (430,530 -> 820,300) with a
// fixed click window, and every scene resets to frame 0 — so the SAME sweep
// replayed every scene and looked copy-pasted. cursorTrajectory() returns a
// distinct, deterministic path + click timing per scene index so the cursor
// varies scene-to-scene. Coordinates are in the 1280x720 canvas space.

export type CursorTrajectory = {
  x0: number; // start x
  y0: number; // start y
  x1: number; // end x (where the click lands)
  y1: number; // end y
  clickStart: number; // progress fraction the click pulse ramps up at
  clickFall: number; // progress fraction the click pulse ramps down at
};

// Distinct sweeps: different start corners, end targets, and click timing. Kept
// well inside the 1280x720 frame so the cursor never drifts off-canvas.
const CURSOR_TARGETS: CursorTrajectory[] = [
  {x0: 430, y0: 530, x1: 820, y1: 300, clickStart: 0.48, clickFall: 0.68},
  {x0: 880, y0: 300, x1: 470, y1: 560, clickStart: 0.44, clickFall: 0.66},
  {x0: 360, y0: 300, x1: 760, y1: 540, clickStart: 0.52, clickFall: 0.72},
  {x0: 840, y0: 560, x1: 420, y1: 320, clickStart: 0.40, clickFall: 0.62},
  {x0: 520, y0: 240, x1: 900, y1: 520, clickStart: 0.50, clickFall: 0.70},
  {x0: 300, y0: 520, x1: 700, y1: 300, clickStart: 0.46, clickFall: 0.66},
];

export function cursorTrajectory(sceneIndex: number): CursorTrajectory {
  const len = CURSOR_TARGETS.length;
  const i = ((Math.floor(sceneIndex) % len) + len) % len;
  return CURSOR_TARGETS[i];
}
