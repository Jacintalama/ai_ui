import { fileURLToPath } from "node:url";
import Fastify from "fastify";
import { renderJob } from "./render-job.js";
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
      reply.code(500);
      const message = err instanceof Error ? err.message : String(err);
      return { ok: false, error: message };
    }
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
