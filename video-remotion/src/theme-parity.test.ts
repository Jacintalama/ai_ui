import {describe, expect, it} from "vitest";
import {SceneParity} from "./theme-parity";

describe("theme-parity", () => {
  it("exports SceneParity as a component function", () => {
    expect(typeof SceneParity).toBe("function");
  });
});
