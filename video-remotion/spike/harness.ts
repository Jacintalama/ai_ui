// Validate -> render gates for an AI-authored single-file Remotion composition.
//   lint -> real bundle() (compile) -> renderStill frame 45 TWICE (determinism
//   proof) -> renderMedia. Throws GateError (with .feedback) on any failure so
//   the auto-repair loop can feed the error back to the model.
import {bundle} from "@remotion/bundler";
import {selectComposition, renderStill, renderMedia} from "@remotion/renderer";
import {readFileSync, writeFileSync, mkdirSync, rmSync} from "node:fs";
import {fileURLToPath} from "node:url";
import path from "node:path";
import {lintComposition, lintAssets} from "./lint";
import {renderConcurrency} from "../src/render";

const SPIKE = path.dirname(fileURLToPath(import.meta.url));
const PROJECT = path.dirname(SPIKE);
const TMP_DIR = path.join(PROJECT, "src", "__ai_tmp__");
const TMP_ENTRY = path.join(TMP_DIR, "comp.tsx");
const OUT_DIR = path.join(SPIKE, "out");

export class GateError extends Error {
  constructor(msg: string, public feedback: string, public report: unknown) {
    super(msg);
  }
}

export async function harness(compSrc: string, label: string, allowedAssets: string[] = []) {
  const report: Record<string, unknown> = {label, gates: {}};
  const gates = report.gates as Record<string, unknown>;

  // GATE 1 — determinism heuristic lint + asset allow-list (only provided screenshots)
  const lintErrs = [...lintComposition(compSrc), ...lintAssets(compSrc, allowedAssets)];
  gates.lint = lintErrs.length === 0 ? "pass" : lintErrs;
  if (lintErrs.length) throw new GateError("lint failed", lintErrs.join("\n"), report);

  mkdirSync(TMP_DIR, {recursive: true});
  writeFileSync(TMP_ENTRY, compSrc, "utf-8");

  try {
    // GATE 2 — compile = the real bundle()
    let serveUrl: string;
    try {
      serveUrl = await bundle({entryPoint: TMP_ENTRY});
      gates.compile = "pass";
    } catch (e) {
      const msg = (e as Error)?.message ?? String(e);
      gates.compile = msg;
      throw new GateError("bundle failed", msg, report);
    }

    const composition = await selectComposition({serveUrl, id: "Video", inputProps: {}});
    report.composition = {
      durationInFrames: composition.durationInFrames, fps: composition.fps,
      width: composition.width, height: composition.height,
    };

    // GATE 3 — determinism PROOF: render the same mid frame twice, assert identical
    mkdirSync(OUT_DIR, {recursive: true});
    const frame = Math.min(45, composition.durationInFrames - 1);
    const a = path.join(OUT_DIR, "_det-a.png");
    const b = path.join(OUT_DIR, "_det-b.png");
    try {
      await renderStill({composition, serveUrl, frame, output: a, inputProps: {}});
      await renderStill({composition, serveUrl, frame, output: b, inputProps: {}});
    } catch (e) {
      const msg = (e as Error)?.message ?? String(e);
      gates.render = msg;
      throw new GateError("renderStill failed", msg, report);
    }
    const identical = Buffer.compare(readFileSync(a), readFileSync(b)) === 0;
    gates.determinism = identical
      ? `pass (frame ${frame} byte-identical across 2 independent renders)`
      : `FAIL (frame ${frame} differs across renders)`;
    if (!identical) throw new GateError("non-deterministic", `frame ${frame} differs across two renders`, report);

    // GATE 4 — full render to mp4
    const out = path.join(OUT_DIR, `${label}.mp4`);
    await renderMedia({
      composition, serveUrl, codec: "h264", outputLocation: out,
      imageFormat: "jpeg", pixelFormat: "yuv420p", inputProps: {},
      concurrency: renderConcurrency(),
    });
    gates.renderMedia = "pass";
    report.output = out;
    return report;
  } finally {
    rmSync(TMP_DIR, {recursive: true, force: true});
  }
}
