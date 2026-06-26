// Stage-1 proof harness: take an AI-authored single-file Remotion composition,
// run it through the validate -> render gates, and prove it's deterministic.
//
//   lint -> real bundle() (compile gate) -> renderStill frame 45 TWICE
//   (assert byte-identical = determinism) -> renderMedia -> report.
//
// Usage: npx tsx spike/run.ts <composition.tsx> [label]
import {bundle} from "@remotion/bundler";
import {selectComposition, renderStill, renderMedia} from "@remotion/renderer";
import {readFileSync, writeFileSync, mkdirSync, rmSync} from "node:fs";
import {fileURLToPath} from "node:url";
import path from "node:path";
import {lintComposition} from "./lint";
import {renderConcurrency} from "../src/render";

const SPIKE = path.dirname(fileURLToPath(import.meta.url));
const PROJECT = path.dirname(SPIKE);
const TMP_DIR = path.join(PROJECT, "src", "__ai_tmp__");
const TMP_ENTRY = path.join(TMP_DIR, "comp.tsx");
const OUT_DIR = path.join(SPIKE, "out");

class GateError extends Error {
  constructor(msg: string, public feedback: string, public report: unknown) {
    super(msg);
  }
}

export async function harness(compSrc: string, label: string) {
  const report: Record<string, unknown> = {label, gates: {} as Record<string, unknown>};
  const gates = report.gates as Record<string, unknown>;

  // GATE 1 — determinism heuristic lint
  const lintErrs = lintComposition(compSrc);
  gates.lint = lintErrs.length === 0 ? "pass" : lintErrs;
  if (lintErrs.length) throw new GateError("lint failed", lintErrs.join("\n"), report);

  mkdirSync(TMP_DIR, {recursive: true});
  writeFileSync(TMP_ENTRY, compSrc, "utf-8");

  // GATE 2 — compile = the real bundle() (catches unresolved imports/missing exports)
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
  const t0 = Date.now ? 0 : 0; // (no wall-clock in render; timing done by caller)
  await renderMedia({
    composition, serveUrl, codec: "h264", outputLocation: out,
    imageFormat: "jpeg", pixelFormat: "yuv420p", inputProps: {},
    concurrency: renderConcurrency(),
  });
  void t0;
  gates.renderMedia = "pass";
  report.output = out;
  return report;
}

async function main() {
  const [, , compPath, label = "video"] = process.argv;
  if (!compPath) {
    console.error("usage: tsx spike/run.ts <composition.tsx> [label]");
    process.exit(2);
  }
  const src = readFileSync(compPath, "utf-8");
  try {
    const report = await harness(src, label);
    console.log("=== PROOF REPORT ===");
    console.log(JSON.stringify(report, null, 2));
  } catch (e) {
    console.error("=== PROOF FAILED ===");
    if (e instanceof GateError) {
      console.error(JSON.stringify(e.report, null, 2));
      console.error("\nrepair feedback:\n" + e.feedback);
    } else {
      console.error(String(e));
    }
    process.exitCode = 1;
  } finally {
    rmSync(TMP_DIR, {recursive: true, force: true});
  }
}

main();
