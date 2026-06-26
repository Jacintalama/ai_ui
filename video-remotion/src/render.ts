export const MAX_DURATION_S = 40;

// renderMedia defaults to one Chromium tab per CPU core, which can OOM the
// memory-constrained render host. Cap it (env-overridable) to bound peak RAM.
export function renderConcurrency(): number {
  const n = Number.parseInt(process.env.REMOTION_CONCURRENCY ?? "", 10);
  if (!Number.isFinite(n)) return 2; // safe default for the small box
  return Math.max(1, n);
}
export type RenderRequest = { jobDir: string; theme: string; fps: number;
  width: number; height: number; host: string; title: string; outFile?: string;
  animationPreset?: string;
  scenes: { kind: string; screenshot?: string; headline?: string;
    subtext?: string; motion?: string; durationS: number;
    click?: { x: number; y: number; label: string } }[] };

export function buildRenderConfig(req: RenderRequest) {
  const fps = req.fps || 24;  // match the animated path's fps for parity
  let totalS = 0;
  const scenes = req.scenes.map((s) => {
    const remaining = Math.max(0, MAX_DURATION_S - totalS);
    const durS = Math.min(Math.max(0.5, s.durationS || 3), remaining || 0.0001);
    totalS += durS;
    return { ...s, durInFrames: Math.round(durS * fps) };
  }).filter((s) => s.durInFrames > 0);
  const durationInFrames = Math.max(1, scenes.reduce((a, s) => a + s.durInFrames, 0));
  const width = req.width || 1280, height = req.height || 720;
  // Pass the screenshot ABS PATH through unchanged. The render service converts it
  // to a data: URI before rendering, because headless Chromium refuses file://
  // images from the http-served bundle (ERR_UNKNOWN_URL_SCHEME).
  const screenshotUrl = (p?: string) => (p ? p : undefined);
  const inputProps = { theme: req.theme, host: req.host, title: req.title,
    fps, width, height,
    animationPreset: req.animationPreset || "cursor_click",
    scenes: scenes.map((s) => ({ kind: s.kind, screenshot: screenshotUrl(s.screenshot),
      headline: s.headline ?? "", subtext: s.subtext ?? "", motion: s.motion ?? "fade",
      durInFrames: s.durInFrames, click: s.click })) };
  return { fps, width, height, durationInFrames, inputProps,
    outFile: req.outFile || (req.jobDir + "/remotion-video.mp4") };
}
