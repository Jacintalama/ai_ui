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

export type Shot = {name: string; path: string};
type Block = {type: "text"; text: string} | {type: "image"; source: {type: "base64"; media_type: string; data: string}};

export async function generate(
  brief: string,
  opts: {feedback?: string; screenshots?: Shot[]} = {},
): Promise<string> {
  const {feedback, screenshots = []} = opts;
  const key = process.env.ANTHROPIC_API_KEY;
  if (!key) throw new Error("ANTHROPIC_API_KEY not set");

  const text: string[] = [`Brief:\n${brief}`];
  if (screenshots.length) {
    text.push(
      `\nAvailable screenshots (embed + animate them with <Img src={staticFile("...")}/>, ` +
      `referencing ONLY these EXACT filenames): ${screenshots.map((s) => s.name).join(", ")}. ` +
      `The images are attached below, in order, so you can see what each shows.`,
    );
  }
  if (feedback) {
    text.push(`\nYour previous attempt FAILED these checks. Fix them and return the COMPLETE corrected single-file composition:\n${feedback}`);
  }
  const content: Block[] = [{type: "text", text: text.join("\n")}];
  for (const s of screenshots) {
    content.push({type: "text", text: `Screenshot ${s.name}:`});
    content.push({type: "image", source: {type: "base64", media_type: "image/png", data: readFileSync(s.path).toString("base64")}});
  }

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
      messages: [{role: "user", content}],
    }),
  });
  if (!res.ok) {
    throw new Error(`anthropic API ${res.status}: ${(await res.text()).slice(0, 300)}`);
  }
  const data = (await res.json()) as {content?: Array<{type: string; text?: string}>};
  const reply = (data.content ?? [])
    .filter((b) => b.type === "text")
    .map((b) => b.text ?? "")
    .join("\n");
  return extractTsx(reply);
}
