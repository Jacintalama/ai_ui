import {describe, expect, it} from "vitest";
import {extractTsx} from "./generate";

describe("extractTsx", () => {
  it("extracts a single tsx fenced block", () => {
    const out = extractTsx("Here you go:\n```tsx\nconst x = 1;\nregisterRoot(Root);\n```\nDone.");
    expect(out).toBe("const x = 1;\nregisterRoot(Root);");
  });

  it("handles a block with no language tag", () => {
    expect(extractTsx("```\nregisterRoot(Root);\n```")).toBe("registerRoot(Root);");
  });

  it("picks the block containing registerRoot when there are several", () => {
    const out = extractTsx("```bash\nnpm i\n```\nthen:\n```tsx\nconst c = 2;\nregisterRoot(Root);\n```");
    expect(out).toContain("registerRoot(Root)");
    expect(out).not.toContain("npm i");
  });

  it("falls back to raw code when there is no fence but registerRoot is present", () => {
    expect(extractTsx("const x = 1; registerRoot(Root);")).toContain("registerRoot(Root)");
  });

  it("throws when there is no usable code", () => {
    expect(() => extractTsx("Sorry, I can't do that.")).toThrow();
  });
});
