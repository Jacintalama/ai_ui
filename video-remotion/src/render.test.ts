import {describe, it, expect, afterEach} from "vitest";
import {buildRenderConfig, renderConcurrency} from "./render";
describe("buildRenderConfig", () => {
  it("converts seconds to frames and passes the screenshot abs path through", () => {
    const c = buildRenderConfig({jobDir: "/j", theme: "parity", fps: 30,
      width: 1280, height: 720, host: "x.com", title: "X",
      animationPreset: "cursor_click",
      scenes: [{kind: "screenshot", screenshot: "/j/s/screenshot-1.png",
        headline: "Hi", motion: "zoom-in", durationS: 3}]});
    expect(c.inputProps.scenes[0].durInFrames).toBe(90);
    // abs path passed through; the render service converts it to a data: URI.
    expect(c.inputProps.scenes[0].screenshot).toBe("/j/s/screenshot-1.png");
    expect(c.inputProps.animationPreset).toBe("cursor_click");
    expect(c.durationInFrames).toBe(90);
  });
  it("defaults animationPreset to cursor_click", () => {
    const c = buildRenderConfig({jobDir: "/j", theme: "parity", fps: 24,
      width: 1280, height: 720, host: "", title: "",
      scenes: [{kind: "screenshot", durationS: 3}]});
    expect(c.inputProps.animationPreset).toBe("cursor_click");
  });
  it("clamps total duration to MAX_DURATION_S", () => {
    const scenes = Array.from({length: 30}, () => ({kind: "screenshot", durationS: 5}));
    const c = buildRenderConfig({jobDir: "/j", theme: "parity", fps: 30,
      width: 1280, height: 720, host: "", title: "", scenes});
    expect(c.durationInFrames).toBeLessThanOrEqual(40 * 30);
  });
});

describe("renderConcurrency", () => {
  const orig = process.env.REMOTION_CONCURRENCY;
  afterEach(() => {
    if (orig === undefined) delete process.env.REMOTION_CONCURRENCY;
    else process.env.REMOTION_CONCURRENCY = orig;
  });
  it("defaults to a small cap (2) to bound RAM on the constrained host", () => {
    delete process.env.REMOTION_CONCURRENCY;
    expect(renderConcurrency()).toBe(2);
  });
  it("honors a REMOTION_CONCURRENCY override", () => {
    process.env.REMOTION_CONCURRENCY = "1";
    expect(renderConcurrency()).toBe(1);
  });
  it("never returns less than 1", () => {
    process.env.REMOTION_CONCURRENCY = "0";
    expect(renderConcurrency()).toBe(1);
    process.env.REMOTION_CONCURRENCY = "-5";
    expect(renderConcurrency()).toBe(1);
  });
  it("ignores non-numeric values, falling back to the default", () => {
    process.env.REMOTION_CONCURRENCY = "abc";
    expect(renderConcurrency()).toBe(2);
  });
});
