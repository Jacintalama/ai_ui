// The hardened executor: turn AI-authored composition source into an MP4 safely.
//   static gate (lint + caps, no execution)
//   -> bundle with the import allow-list ENFORCED at webpack (import-guard)
//   -> selectComposition, re-check caps against real metadata
//   -> renderMedia under a concurrency cap + per-frame timeout + a wall-clock
//      timeout that CANCELS the render (frees chrome) instead of leaking it.
// Returns a structured result; never throws out of the function. Heavy deps
// (@remotion/bundler, @remotion/renderer) are imported lazily so the static gates
// stay fast and importing this module is cheap.
import {mkdirSync, writeFileSync, rmSync, existsSync, copyFileSync} from "node:fs";
import {fileURLToPath} from "node:url";
import path from "node:path";
import {lintComposition, lintAssets} from "./lint.js";
import {validateCaps} from "./caps.js";
import {makeImportGuardOverride} from "./import-guard.js";
import {renderConcurrency} from "./render.js";

const SRC = path.dirname(fileURLToPath(import.meta.url));
const TMP_DIR = path.join(SRC, "__ai_tmp__");
// bundle() resolves staticFile() assets from <project>/public — stage the job's
// captured screenshots here so the composition can embed them.
const PUBLIC_DIR = path.join(path.dirname(SRC), "public");

// AI renders on the small box can take minutes; the in-process cap stays just
// under the tasks->/render-ai HTTP timeout (600s) so the render cancels cleanly
// and returns a structured error before the HTTP call drops.
const DEFAULT_TIMEOUT_MS = Number.parseInt(process.env.AI_RENDER_TIMEOUT_MS ?? "", 10) || 540_000;
const FRAME_TIMEOUT_MS = 30_000;

export type AiRenderRequest = {
  jobDir: string;
  source: string;
  assets?: string[];
  outFile?: string;
  timeoutMs?: number;
};
export type AiRenderResult =
  | {ok: true; outPath: string; frames: number}
  | {ok: false; stage: "lint" | "caps" | "bundle" | "render"; error: string};

export function withTimeout<T>(p: Promise<T>, ms: number, label: string, onTimeout?: () => void): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const t = setTimeout(() => {
      onTimeout?.();
      reject(new Error(`${label} exceeded ${ms}ms timeout`));
    }, ms);
    p.then(
      (v) => { clearTimeout(t); resolve(v); },
      (e) => { clearTimeout(t); reject(e); },
    );
  });
}

export type StagePair = {src: string; dest: string};

// Pure: which captured screenshots to copy into public/ (jobDir/screenshots/<name>
// -> publicDir/<name>), skipping names whose source file isn't on disk.
export function assetStagePairs(
  jobDir: string, assets: string[], publicDir: string, exists: (p: string) => boolean,
): StagePair[] {
  const pairs: StagePair[] = [];
  for (const name of assets) {
    const src = path.join(jobDir, "screenshots", name);
    if (exists(src)) pairs.push({src, dest: path.join(publicDir, name)});
  }
  return pairs;
}

let aiRenderChain: Promise<unknown> = Promise.resolve();

// Serialize AI renders: one at a time bounds RAM on the small box AND protects the
// shared public/ staging dir from concurrent jobs clobbering each other's assets.
export function renderAiComposition(req: AiRenderRequest): Promise<AiRenderResult> {
  const run = () => renderAiCompositionImpl(req);
  const p = aiRenderChain.then(run, run);
  aiRenderChain = p.then(() => undefined, () => undefined); // chain never rejects
  return p as Promise<AiRenderResult>;
}

async function renderAiCompositionImpl(req: AiRenderRequest): Promise<AiRenderResult> {
  const {jobDir, source, assets = [], timeoutMs = DEFAULT_TIMEOUT_MS} = req;
  const outFile = req.outFile || path.join(jobDir, "ai-video.mp4");

  // GATE 1 — static, no execution
  const lintErrs = [...lintComposition(source), ...lintAssets(source, assets)];
  if (lintErrs.length) return {ok: false, stage: "lint", error: lintErrs.join("\n")};
  const capErrs = validateCaps(source);
  if (capErrs.length) return {ok: false, stage: "caps", error: capErrs.join("\n")};

  const {bundle} = await import("@remotion/bundler");
  const {selectComposition, renderMedia, makeCancelSignal} = await import("@remotion/renderer");

  // Stage captured screenshots into public/ so staticFile() resolves them at render.
  const stage = assetStagePairs(jobDir, assets, PUBLIC_DIR, existsSync);
  if (stage.length) mkdirSync(PUBLIC_DIR, {recursive: true});
  for (const {src, dest} of stage) {
    try { copyFileSync(src, dest); } catch { /* missing asset: the render gate will surface it */ }
  }

  mkdirSync(TMP_DIR, {recursive: true});
  const entry = path.join(TMP_DIR, "ai-entry.tsx");
  writeFileSync(entry, source, "utf-8");

  try {
    // GATE 2 — bundle with the import allow-list enforced (the real teeth)
    let serveUrl: string;
    try {
      serveUrl = await withTimeout(
        bundle({entryPoint: entry, webpackOverride: makeImportGuardOverride(entry)}),
        timeoutMs,
        "bundle",
      );
    } catch (e) {
      return {ok: false, stage: "bundle", error: (e as Error)?.message ?? String(e)};
    }

    // GATE 3 — real metadata vs caps, then a cancellable, time-bounded render
    try {
      const composition = await selectComposition({serveUrl, id: "Video", inputProps: {}});
      const metaErrs = validateCaps(source, {
        durationInFrames: composition.durationInFrames,
        width: composition.width,
        height: composition.height,
        fps: composition.fps,
      });
      if (metaErrs.length) return {ok: false, stage: "caps", error: metaErrs.join("\n")};

      const {cancelSignal, cancel} = makeCancelSignal();
      await withTimeout(
        renderMedia({
          composition,
          serveUrl,
          codec: "h264",
          outputLocation: outFile,
          imageFormat: "jpeg",
          pixelFormat: "yuv420p",
          inputProps: {},
          concurrency: renderConcurrency(),
          timeoutInMilliseconds: FRAME_TIMEOUT_MS,
          cancelSignal,
        }),
        timeoutMs,
        "render",
        () => cancel(),
      );

      return {ok: true, outPath: outFile, frames: composition.durationInFrames};
    } catch (e) {
      return {ok: false, stage: "render", error: (e as Error)?.message ?? String(e)};
    }
  } finally {
    rmSync(TMP_DIR, {recursive: true, force: true});
    for (const {dest} of stage) rmSync(dest, {force: true});
  }
}
