import { fileURLToPath } from "node:url";
import Fastify from "fastify";
import { renderJob } from "./render-job.js";
import { renderAiComposition } from "./ai-render.js";
import type { RenderRequest } from "./render.js";

export function buildServer() {
  const app = Fastify({ logger: false });

  app.get("/healthz", async () => ({ ok: true }));

  app.post("/render", async (req, reply) => {
    const body = req.body as Record<string, unknown>;

    if (!body?.jobDir || typeof body.jobDir !== "string" || body.jobDir.trim() === "") {
      reply.code(400);
      return { ok: false, error: "jobDir is required and must be a non-empty string" };
    }

    if (!Array.isArray(body.scenes) || body.scenes.length === 0) {
      reply.code(400);
      return { ok: false, error: "scenes must be a non-empty array" };
    }

    try {
      const result = await renderJob(body as unknown as RenderRequest);
      return { ok: true, outPath: result.outPath, frames: result.frames };
    } catch (err: unknown) {
      console.error("[render] failed:", err);  // preserve the full stack in container logs
      reply.code(500);
      const message = err instanceof Error ? err.message : String(err);
      return { ok: false, error: message };
    }
  });

  // Hardened path: render an AI-AUTHORED composition. Static gate + bundler import
  // allow-list + bounded render happen inside renderAiComposition; here we only
  // validate the request shape and map the structured result to HTTP.
  app.post("/render-ai", async (req, reply) => {
    const body = req.body as Record<string, unknown>;

    if (!body?.jobDir || typeof body.jobDir !== "string" || body.jobDir.trim() === "") {
      reply.code(400);
      return { ok: false, error: "jobDir is required and must be a non-empty string" };
    }
    if (!body?.source || typeof body.source !== "string" || body.source.trim() === "") {
      reply.code(400);
      return { ok: false, error: "source is required and must be a non-empty string" };
    }

    const assets = Array.isArray(body.assets)
      ? (body.assets as unknown[]).filter((a): a is string => typeof a === "string")
      : [];

    const result = await renderAiComposition({
      jobDir: body.jobDir,
      source: body.source,
      assets,
      outFile: typeof body.outFile === "string" ? body.outFile : undefined,
    });

    if (result.ok) {
      return { ok: true, outPath: result.outPath, frames: result.frames };
    }
    // gate failures (lint/caps/bundle) = bad composition -> 400; render error -> 500
    reply.code(result.stage === "render" ? 500 : 400);
    return { ok: false, error: result.error, stage: result.stage };
  });

  return app;
}

// Start listening when run directly (e.g. tsx src/server.ts or npm run server)
if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const app = buildServer();
  app.listen({ host: "0.0.0.0", port: Number(process.env.PORT) || 8090 }, (err) => {
    if (err) {
      console.error(err);
      process.exit(1);
    }
    console.log("Remotion render service listening on :8090");
  });
}
