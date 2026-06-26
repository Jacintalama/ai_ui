// Hands-off automated loop: generate (Claude API) -> harness (lint/compile/
// determinism/render); on any gate failure, feed the error back and regenerate
// (max 3). Usage: ANTHROPIC_API_KEY=... npx tsx spike/auto.ts "<brief>" [label]
import {writeFileSync, mkdirSync} from "node:fs";
import {fileURLToPath} from "node:url";
import path from "node:path";
import {generate} from "./generate";
import {harness, GateError} from "./harness";

const OUT_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), "out");

export async function auto(brief: string, label: string, maxAttempts = 3) {
  let feedback: string | undefined;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    console.log(`\n--- attempt ${attempt}/${maxAttempts}: generating from the model ---`);
    const tsx = await generate(brief, feedback);
    mkdirSync(OUT_DIR, {recursive: true});
    writeFileSync(path.join(OUT_DIR, `${label}.gen.tsx`), tsx, "utf-8"); // keep what the model wrote
    try {
      const report = await harness(tsx, label);
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
  if (!brief) {
    console.error('usage: tsx spike/auto.ts "<brief>" [label]');
    process.exit(2);
  }
  try {
    const report = await auto(brief, label);
    console.log("\n=== AUTOMATED PROOF REPORT ===");
    console.log(JSON.stringify(report, null, 2));
  } catch (e) {
    console.error("\n=== AUTOMATED LOOP FAILED ===", String(e));
    process.exitCode = 1;
  }
}

main();
