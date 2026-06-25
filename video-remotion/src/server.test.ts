import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock render-job before importing server so no Chromium runs in tests
vi.mock("./render-job", () => ({
  renderJob: vi.fn(async () => ({ outPath: "/j/remotion-video.mp4", frames: 90 })),
}));

import { buildServer } from "./server";

describe("POST /render", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns 400 when jobDir is missing", async () => {
    const app = buildServer();
    const res = await app.inject({
      method: "POST",
      url: "/render",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({}),
    });
    expect(res.statusCode).toBe(400);
    const body = JSON.parse(res.body);
    expect(body.ok).toBe(false);
  });

  it("returns 400 when scenes is empty", async () => {
    const app = buildServer();
    const res = await app.inject({
      method: "POST",
      url: "/render",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ jobDir: "/j", scenes: [] }),
    });
    expect(res.statusCode).toBe(400);
    const body = JSON.parse(res.body);
    expect(body.ok).toBe(false);
  });

  it("returns 400 when scenes is not an array", async () => {
    const app = buildServer();
    const res = await app.inject({
      method: "POST",
      url: "/render",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ jobDir: "/j", scenes: "bad" }),
    });
    expect(res.statusCode).toBe(400);
  });

  it("returns 200 with ok:true and result fields on valid body", async () => {
    const app = buildServer();
    const payload = {
      jobDir: "/j",
      theme: "parity",
      fps: 30,
      width: 1280,
      height: 720,
      host: "x.com",
      title: "Test",
      scenes: [{ kind: "screenshot", durationS: 3 }],
    };
    const res = await app.inject({
      method: "POST",
      url: "/render",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    expect(res.statusCode).toBe(200);
    const body = JSON.parse(res.body);
    expect(body.ok).toBe(true);
    expect(body.outPath).toBe("/j/remotion-video.mp4");
    expect(body.frames).toBe(90);
  });
});

describe("GET /healthz", () => {
  it("returns 200", async () => {
    const app = buildServer();
    const res = await app.inject({ method: "GET", url: "/healthz" });
    expect(res.statusCode).toBe(200);
    const body = JSON.parse(res.body);
    expect(body.ok).toBe(true);
  });
});
