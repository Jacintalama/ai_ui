// Hard input caps for an AI-authored composition, checked BEFORE any bundle or
// render. Pure and fast (no execution). Returns a list of violations; empty = ok.
// Source-only checks run on the raw text; metadata checks run when the real
// composition metadata is available (post-selectComposition).

const MAX_SOURCE_BYTES = Number.parseInt(process.env.AI_MAX_SOURCE_BYTES ?? "", 10) || 64 * 1024;
const MAX_FRAMES = Number.parseInt(process.env.AI_MAX_FRAMES ?? "", 10) || 1800; // ~60s @30fps
const MAX_WIDTH = 1920;
const MAX_HEIGHT = 1080;
const MIN_FPS = 24;
const MAX_FPS = 60;

export type CompMeta = {durationInFrames?: number; width?: number; height?: number; fps?: number};

export function validateCaps(source: string, meta: CompMeta = {}): string[] {
  const errs: string[] = [];

  if (source.length > MAX_SOURCE_BYTES) {
    errs.push(`source too large: ${source.length} bytes (max ${MAX_SOURCE_BYTES}).`);
  }

  const registerRoots = (source.match(/registerRoot\s*\(/g) || []).length;
  if (registerRoots === 0) {
    errs.push("missing registerRoot(...) call.");
  } else if (registerRoots > 1) {
    errs.push(`expected exactly one registerRoot(...), found ${registerRoots}.`);
  }

  if (!/id\s*=\s*["'`]Video["'`]/.test(source)) {
    errs.push('composition id must be "Video".');
  }

  const {durationInFrames, width, height, fps} = meta;
  if (durationInFrames != null && durationInFrames > MAX_FRAMES) {
    errs.push(`duration too long: ${durationInFrames} frames (max ${MAX_FRAMES}).`);
  }
  if (width != null && width > MAX_WIDTH) {
    errs.push(`width too large: ${width} (max ${MAX_WIDTH}).`);
  }
  if (height != null && height > MAX_HEIGHT) {
    errs.push(`height too large: ${height} (max ${MAX_HEIGHT}).`);
  }
  if (fps != null && (fps < MIN_FPS || fps > MAX_FPS)) {
    errs.push(`fps out of range: ${fps} (allowed ${MIN_FPS}-${MAX_FPS}).`);
  }

  return errs;
}
