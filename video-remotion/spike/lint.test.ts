import {describe, expect, it} from "vitest";
import {lintComposition} from "./lint";

const GOOD = `
import {AbsoluteFill, Sequence, Series, useCurrentFrame, useVideoConfig, interpolate, spring, Easing, registerRoot, Composition} from "remotion";
import {loadFont} from "@remotion/google-fonts/Inter";
import React from "react";
const {fontFamily} = loadFont();
const Comp: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const opacity = interpolate(frame, [0, fps], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.ease});
  const scale = spring({frame, fps, config: {damping: 12}});
  return <AbsoluteFill style={{opacity, transform: \`scale(\${scale})\`, fontFamily}}>hi</AbsoluteFill>;
};
export const Root = () => <Composition id="Video" component={Comp} durationInFrames={120} fps={30} width={1280} height={720} />;
registerRoot(Root);
`;

describe("lintComposition", () => {
  it("passes a clean frame-based Remotion composition", () => {
    expect(lintComposition(GOOD)).toEqual([]);
  });

  it.each([
    ["Math.random", "const x = Math.random();"],
    ["Date.now", "const t = Date.now();"],
    ["new Date", "const d = new Date();"],
    ["bare Date()", "const d = Date();"],
    ["performance.now", "const t = performance.now();"],
    ["crypto random", "const r = crypto.randomUUID();"],
    ["setTimeout", "setTimeout(() => {}, 100);"],
    ["setInterval", "setInterval(() => {}, 100);"],
    ["requestAnimationFrame", "requestAnimationFrame(cb);"],
    ["fetch", "const r = await fetch('/x');"],
    ["XMLHttpRequest", "const x = new XMLHttpRequest();"],
    ["useState", "const [s, set] = useState(0);"],
    ["useEffect", "useEffect(() => {}, []);"],
    ["css animation shorthand", "style={{ animation: 'spin 2s linear' }}"],
    ["css animationName (camel)", "style={{ animationName: 'spin' }}"],
    ["css transitionProperty (camel)", "style={{ transitionProperty: 'opacity' }}"],
    ["@keyframes", "const css = `@keyframes spin { from {} to {} }`;"],
    ["tailwind animate-", "<div className='animate-spin' />"],
  ])("flags %s", (_name, snippet) => {
    expect(lintComposition(snippet).length).toBeGreaterThan(0);
  });

  it("does NOT flag legit Remotion APIs (interpolate/spring/useVideoConfig/staticFile)", () => {
    const s = "const a = interpolate(f,[0,1],[0,1]); const b = spring({frame,fps}); const c = useVideoConfig(); const d = staticFile('x.png');";
    expect(lintComposition(s)).toEqual([]);
  });

  it("flags a disallowed import but allows remotion/@remotion/*/react", () => {
    expect(lintComposition("import axios from 'axios';").length).toBeGreaterThan(0);
    expect(lintComposition("import {x} from '@remotion/shapes'; import React from 'react'; import {y} from 'remotion';")).toEqual([]);
  });

  it("does not false-positive 'fetch' inside 'prefetch'", () => {
    expect(lintComposition("import {prefetch} from 'remotion'; prefetch('x');")).toEqual([]);
  });
});
