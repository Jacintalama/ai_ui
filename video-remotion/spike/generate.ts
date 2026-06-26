// Programmatic generator: call Claude (one fetch, no SDK) with the vendored
// single-file system prompt + the brief (+ optional repair feedback), and
// extract the composition from the reply.
import {readFileSync} from "node:fs";
import {fileURLToPath} from "node:url";
import path from "node:path";

const SPIKE = path.dirname(fileURLToPath(import.meta.url));
const SYSTEM_PROMPT = readFileSync(path.join(SPIKE, "system-prompt.md"), "utf-8");
const MODEL = process.env.SPIKE_MODEL || "claude-opus-4-8";

const FENCE = /```(?:tsx?|typescript|jsx?)?[^\n]*\n([\s\S]*?)```/g;

export function extractTsx(text: string): string {
  const blocks: string[] = [];
  let m: RegExpExecArray | null;
  FENCE.lastIndex = 0;
  while ((m = FENCE.exec(text))) blocks.push(m[1].trim());
  if (blocks.length === 0) {
    if (/registerRoot\s*\(/.test(text)) return text.trim();
    throw new Error("model output had no code block");
  }
  if (blocks.length > 1) {
    const comp = blocks.find((b) => /registerRoot\s*\(/.test(b));
    return comp ?? blocks[blocks.length - 1];
  }
  return blocks[0];
}

export async function generate(brief: string, feedback?: string): Promise<string> {
  const key = process.env.ANTHROPIC_API_KEY;
  if (!key) throw new Error("ANTHROPIC_API_KEY not set");
  const userContent = feedback
    ? `Brief:\n${brief}\n\nYour previous attempt FAILED these checks. Fix them and return the COMPLETE corrected single-file composition:\n${feedback}`
    : `Brief:\n${brief}`;
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": key,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model: MODEL,
      max_tokens: 8000,
      system: SYSTEM_PROMPT,
      messages: [{role: "user", content: userContent}],
    }),
  });
  if (!res.ok) {
    throw new Error(`anthropic API ${res.status}: ${(await res.text()).slice(0, 300)}`);
  }
  const data = (await res.json()) as {content?: Array<{type: string; text?: string}>};
  const text = (data.content ?? [])
    .filter((b) => b.type === "text")
    .map((b) => b.text ?? "")
    .join("\n");
  return extractTsx(text);
}
