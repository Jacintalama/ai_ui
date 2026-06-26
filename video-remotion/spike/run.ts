// CLI: render an existing AI-authored composition file through the harness.
// Usage: npx tsx spike/run.ts <composition.tsx> [label]
import {readFileSync} from "node:fs";
import {harness, GateError} from "./harness";

async function main() {
  const [, , compPath, label = "video"] = process.argv;
  if (!compPath) {
    console.error("usage: tsx spike/run.ts <composition.tsx> [label]");
    process.exit(2);
  }
  try {
    const report = await harness(readFileSync(compPath, "utf-8"), label);
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
  }
}

main();
