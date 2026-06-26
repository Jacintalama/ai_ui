// Determinism heuristic for an AI-authored single-file Remotion composition.
//
// This is a crude PRE-FILTER, NOT a guarantee. It catches the obvious
// non-deterministic / non-frame-based patterns before we spend a render. Real
// determinism is PROVEN downstream by rendering the same frame twice and
// asserting the pixels are identical (see the harness).

const ALLOWED_EXACT = new Set(["remotion", "react", "react/jsx-runtime"]);

type Rule = {name: string; re: RegExp; msg: string};

const RULES: Rule[] = [
  {name: "Math.random", re: /\bMath\.random\s*\(/, msg: "Math.random() is non-deterministic — use random('seed') from remotion."},
  {name: "Date.now", re: /\bDate\.now\s*\(/, msg: "Date.now() is non-deterministic."},
  {name: "new Date", re: /\bnew\s+Date\s*\(/, msg: "new Date() is non-deterministic."},
  {name: "Date()", re: /\bDate\s*\(\s*\)/, msg: "Date() is non-deterministic."},
  {name: "performance.now", re: /\bperformance\.now\s*\(/, msg: "performance.now() is non-deterministic."},
  {name: "crypto.random", re: /\bcrypto\.(getRandomValues|randomUUID)\s*\(/, msg: "crypto randomness is non-deterministic."},
  {name: "setTimeout", re: /\bsetTimeout\s*\(/, msg: "setTimeout is not frame-based."},
  {name: "setInterval", re: /\bsetInterval\s*\(/, msg: "setInterval is not frame-based."},
  {name: "requestAnimationFrame", re: /\brequestAnimationFrame\s*\(/, msg: "requestAnimationFrame is not frame-based — animate from useCurrentFrame()."},
  {name: "fetch", re: /\bfetch\s*\(/, msg: "fetch() — a composition must not do network I/O."},
  {name: "XMLHttpRequest", re: /\bXMLHttpRequest\b/, msg: "XMLHttpRequest — no network I/O in a composition."},
  {name: "useState", re: /\buseState\s*\(/, msg: "useState — animation must derive from useCurrentFrame(), not React state."},
  {name: "useEffect", re: /\buseEffect\s*\(/, msg: "useEffect — effects don't run deterministically per frame."},
  {name: "css-animation-shorthand", re: /\b(animation|transition)\s*:/, msg: "CSS animation/transition runs on wall-clock time — not deterministic. Animate from useCurrentFrame()."},
  {name: "css-animation-camel", re: /\b(animationName|animationDuration|animationTimingFunction|animationDelay|animationIterationCount|transitionProperty|transitionDuration|transitionTimingFunction|transitionDelay)\b/, msg: "CSS animation/transition runs on wall-clock time — not deterministic."},
  {name: "keyframes", re: /@keyframes\b/, msg: "@keyframes runs on wall-clock time — not deterministic."},
  {name: "animate-class", re: /\banimate-[a-z]/, msg: "Tailwind animate-* utilities are not deterministic."},
];

const IMPORT_RE = /(?:import[^'"]*from\s*|import\s*|require\s*\(\s*)['"]([^'"]+)['"]/g;

function importAllowed(mod: string): boolean {
  return mod.startsWith("@remotion/") || mod.startsWith("react/") || ALLOWED_EXACT.has(mod);
}

export function lintComposition(src: string): string[] {
  const errs: string[] = [];
  for (const r of RULES) {
    if (r.re.test(src)) errs.push(`[${r.name}] ${r.msg}`);
  }
  let m: RegExpExecArray | null;
  IMPORT_RE.lastIndex = 0;
  while ((m = IMPORT_RE.exec(src))) {
    const mod = m[1];
    if (!importAllowed(mod)) {
      errs.push(`[import] disallowed import '${mod}' (allowed: remotion, @remotion/*, react).`);
    }
  }
  return errs;
}
