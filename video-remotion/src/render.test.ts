import {describe, it, expect} from "vitest";
import {buildRenderConfig} from "./render";
describe("buildRenderConfig", () => {
  it("converts seconds to frames and passes the screenshot abs path through", () => {
    const c = buildRenderConfig({jobDir: "/j", theme: "parity", fps: 30,
      width: 1280, height: 720, host: "x.com", title: "X",
      scenes: [{kind: "screenshot", screenshot: "/j/s/screenshot-1.png",
        headline: "Hi", motion: "zoom-in", durationS: 3}]});
    expect(c.inputProps.scenes[0].durInFrames).toBe(90);
    // abs path passed through; the render service converts it to a data: URI.
    expect(c.inputProps.scenes[0].screenshot).toBe("/j/s/screenshot-1.png");
    expect(c.durationInFrames).toBe(90);
  });
  it("clamps total duration to MAX_DURATION_S", () => {
    const scenes = Array.from({length: 30}, () => ({kind: "screenshot", durationS: 5}));
    const c = buildRenderConfig({jobDir: "/j", theme: "parity", fps: 30,
      width: 1280, height: 720, host: "", title: "", scenes});
    expect(c.durationInFrames).toBeLessThanOrEqual(40 * 30);
  });
});
