// Hands-off automated loop: generate (Claude API, optionally with screenshots)
// -> harness (lint/assets/compile/determinism/render); on any gate failure,
// feed the error back and regenerate (max 3).
// Usage: ANTHROPIC_API_KEY=... npx tsx spike/auto.ts "<brief>" [label] [shotsDir]
//   shotsDir: a folder of .png screenshots — MUST be the project's public/ so
//   staticFile() resolves them.
import {writeFileSync, mkdirSync, readdirSync} from "node:fs";
import {fileURLToPath} from "node:url";
import path from "node:path";
import {generate, Shot} from "./generate";
import {harness, GateError} from "./harness";

const OUT_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), "out");

export async function auto(
  brief: string,
  label: string,
  opts: {maxAttempts?: number; screenshots?: Shot[]} = {},
) {
  const {maxAttempts = 3, screenshots = []} = opts;
  const allowed = screenshots.map((s) => s.name);
  let feedback: string | undefined;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    console.log(`\n--- attempt ${attempt}/${maxAttempts}: generating from the model ---`);
    const tsx = await generate(brief, {feedback, screenshots});
    mkdirSync(OUT_DIR, {recursive: true});
    writeFileSync(path.join(OUT_DIR, `${label}.gen.tsx`), tsx, "utf-8");
    try {
      const report = await harness(tsx, label, allowed);
      return {attempts: attempt, ...report};
    } catch (e) {
      if (e instanceof GateError) {
        feedback = e.feedback;
        console.error(`--- attempt ${attempt} failed: ${(e as Error).message} — repairing ---`);
        console.error(feedback);
        continue;
      }
      throw e;
    }
  }
  throw new Error(`failed after ${maxAttempts} attempts`);
}

async function main() {
  const brief = process.argv[2];
  const label = process.argv[3] || "auto";
  const shotsDir = process.argv[4];
  if (!brief) {
    console.error('usage: tsx spike/auto.ts "<brief>" [label] [shotsDir]');
    process.exit(2);
  }
  let screenshots: Shot[] = [];
  if (shotsDir) {
    screenshots = readdirSync(shotsDir)
      .filter((f) => /\.png$/i.test(f))
      .sort()
      .map((f) => ({name: f, path: path.join(shotsDir, f)}));
    console.log(`using ${screenshots.length} screenshots: ${screenshots.map((s) => s.name).join(", ")}`);
  }
  try {
    const report = await auto(brief, label, {screenshots});
    console.log("\n=== AUTOMATED PROOF REPORT ===");
    console.log(JSON.stringify(report, null, 2));
  } catch (e) {
    console.error("\n=== AUTOMATED LOOP FAILED ===", String(e));
    process.exitCode = 1;
  }
}

main();
