import { readFile } from "node:fs/promises";
import { extname } from "node:path";
import { fileURLToPath } from "node:url";
import { bundle } from "@remotion/bundler";
import { selectComposition, renderMedia } from "@remotion/renderer";
import { buildRenderConfig, RenderRequest } from "./render.js";

// ---- MIME helper ----

function getMime(filePath: string): string {
  const ext = extname(filePath).toLowerCase();
  if (ext === ".jpg" || ext === ".jpeg") return "image/jpeg";
  if (ext === ".webp") return "image/webp";
  return "image/png";
}

async function toDataUri(filePath: string): Promise<string> {
  const buf = await readFile(filePath);
  const mime = getMime(filePath);
  return `data:${mime};base64,${buf.toString("base64")}`;
}

// ---- Bundle cache (bundle once, reuse the serveUrl across renders) ----

let bundlePromise: Promise<string> | null = null;

function getServeUrl(): Promise<string> {
  if (!bundlePromise) {
    const entryPoint = fileURLToPath(new URL("./index.ts", import.meta.url));
    bundlePromise = bundle({ entryPoint });
  }
  return bundlePromise;
}

// ---- Concurrency mutex (one render at a time to bound RAM) ----

let chain: Promise<void> = Promise.resolve();

// ---- Public API ----

export async function renderJob(
  body: RenderRequest
): Promise<{ outPath: string; frames: number }> {
  return new Promise<{ outPath: string; frames: number }>((resolve, reject) => {
    chain = chain.then(async () => {
      try {
        resolve(await doRender(body));
      } catch (err) {
        reject(err);
      }
    });
  });
}

// ---- Core render logic ----

async function doRender(
  body: RenderRequest
): Promise<{ outPath: string; frames: number }> {
  const cfg = buildRenderConfig(body);

  // Convert abs screenshot paths to data: URIs.
  // headless Chromium refuses file:// images from the http-served bundle,
  // but data: URIs render fine.
  const scenes = await Promise.all(
    cfg.inputProps.scenes.map(async (s) => {
      if (!s.screenshot) return s;
      try {
        const dataUri = await toDataUri(s.screenshot);
        return { ...s, screenshot: dataUri };
      } catch {
        // file unreadable - drop screenshot so the scene still renders
        return { ...s, screenshot: undefined };
      }
    })
  );

  const inputProps: Record<string, unknown> = { ...cfg.inputProps, scenes };

  const serveUrl = await getServeUrl();

  const composition = await selectComposition({
    serveUrl,
    id: "Video",
    inputProps,
  });

  await renderMedia({
    composition,
    serveUrl,
    codec: "h264",
    outputLocation: cfg.outFile,
    inputProps,
    pixelFormat: "yuv420p",
    imageFormat: "jpeg",
  });

  return { outPath: cfg.outFile, frames: composition.durationInFrames };
}
