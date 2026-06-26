import React from "react";
import {
  AbsoluteFill, Series, useCurrentFrame, useVideoConfig,
  interpolate, spring, Easing, registerRoot, Composition,
} from "remotion";
import {loadFont} from "@remotion/google-fonts/Inter";

const {fontFamily} = loadFont();

const BG = "radial-gradient(130% 120% at 72% 8%, #12273f 0%, #0a1a2c 48%, #050e1a 100%)";
const INK = "#eaf3f8";
const MUTED = "#6f8aa0";
const MINT = "#46e3b5";
const MINT_DEEP = "#1f9d7e";
const ease = Easing.bezier(0.16, 1, 0.3, 1);
const easeInOut = Easing.bezier(0.65, 0, 0.35, 1);

const clamp = {extrapolateLeft: "clamp", extrapolateRight: "clamp"} as const;

// Per-scene fade in/out so beats hand off cleanly.
function envelope(frame: number, dur: number, fps: number): number {
  const f = 0.32 * fps;
  return (
    interpolate(frame, [0, f], [0, 1], {...clamp, easing: ease}) *
    interpolate(frame, [dur - f, dur], [1, 0], {...clamp})
  );
}

// Deterministic money formatter (no toLocaleString surprises).
function formatMoney(n: number): string {
  const v = Math.max(0, n);
  let whole = Math.floor(v);
  let cents = Math.round((v - whole) * 100);
  if (cents === 100) { cents = 0; whole += 1; }
  const cs = cents < 10 ? "0" + cents : "" + cents;
  const s = "" + whole;
  let out = "";
  for (let i = 0; i < s.length; i++) {
    if (i > 0 && (s.length - i) % 3 === 0) out += ",";
    out += s[i];
  }
  return out + "." + cs;
}

// Ambient depth: two drifting glows + a global 12s progress rail. Runs on the
// GLOBAL frame (rendered outside <Series>), so it never resets between beats.
const Backdrop: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const dx = Math.sin((frame / fps) * 0.5) * 28;
  const dy = Math.cos((frame / fps) * 0.4) * 22;
  const prog = interpolate(frame, [0, durationInFrames], [0, 1], {...clamp});
  return (
    <AbsoluteFill>
      <div style={{position: "absolute", width: 780, height: 780, left: 720 + dx, top: -270 + dy, borderRadius: "50%", background: "radial-gradient(circle, rgba(70,227,181,0.14), rgba(70,227,181,0) 68%)"}} />
      <div style={{position: "absolute", width: 540, height: 540, left: -200 + dy, bottom: -220 - dx, borderRadius: "50%", background: "radial-gradient(circle, rgba(40,120,200,0.12), rgba(40,120,200,0) 70%)"}} />
      <div style={{position: "absolute", left: 0, right: 0, bottom: 0, height: 3, background: "rgba(120,150,170,0.10)"}} />
      <div style={{position: "absolute", left: 0, bottom: 0, height: 3, width: `${prog * 100}%`, background: MINT}} />
    </AbsoluteFill>
  );
};

const Eyebrow: React.FC<{label: string; t: number}> = ({label, t}) => (
  <div style={{display: "flex", alignItems: "center", gap: 12, opacity: t, transform: `translateX(${interpolate(t, [0, 1], [-16, 0])}px)`}}>
    <div style={{width: 26, height: 2, background: MINT}} />
    <span style={{fontSize: 19, letterSpacing: 6, color: MINT, fontWeight: 600}}>{label}</span>
  </div>
);

// Beat 1 — brand hook. Letters spring in staggered; underline draws on.
const Brand: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const env = envelope(frame, durationInFrames, fps);
  const eyebrow = interpolate(frame, [4, 20], [0, 1], {...clamp, easing: ease});
  const underline = interpolate(frame, [26, 50], [0, 1], {...clamp, easing: ease});
  const tag = interpolate(frame, [34, 54], [0, 1], {...clamp, easing: ease});
  return (
    <AbsoluteFill style={{fontFamily, opacity: env, justifyContent: "center", paddingLeft: 150}}>
      <div style={{maxWidth: 820}}>
        <Eyebrow label="BUDGETING, REIMAGINED" t={eyebrow} />
        <div style={{display: "flex", marginTop: 16}}>
          {"Ledgr".split("").map((ch, i) => {
            const s = spring({frame: frame - 6 - i * 4, fps, config: {damping: 13, mass: 0.7}});
            return (
              <span key={i} style={{fontSize: 168, fontWeight: 800, letterSpacing: -6, color: i === 0 ? MINT : INK, opacity: s, transform: `translateY(${interpolate(s, [0, 1], [46, 0])}px)`}}>{ch}</span>
            );
          })}
        </div>
        <div style={{height: 6, borderRadius: 3, background: MINT, width: interpolate(underline, [0, 1], [0, 300]), marginTop: 4}} />
        <div style={{marginTop: 26, fontSize: 30, fontWeight: 500, color: MUTED, opacity: tag, transform: `translateY(${interpolate(tag, [0, 1], [14, 0])}px)`}}>
          Your whole financial life, calmly in view.
        </div>
      </div>
    </AbsoluteFill>
  );
};

// Beat 2 — "See every dollar" with a count-up hero number.
const Dollars: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const env = envelope(frame, durationInFrames, fps);
  const head = interpolate(frame, [4, 20], [0, 1], {...clamp, easing: ease});
  const count = interpolate(frame, [10, 10 + 1.5 * fps], [0, 8460.2], {...clamp, easing: ease});
  const sub = interpolate(frame, [1.6 * fps, 2.0 * fps], [0, 1], {...clamp, easing: ease});
  return (
    <AbsoluteFill style={{fontFamily, opacity: env, justifyContent: "center", paddingLeft: 150}}>
      <div>
        <Eyebrow label="SEE EVERY DOLLAR" t={head} />
        <div style={{display: "flex", alignItems: "baseline", marginTop: 14}}>
          <span style={{fontSize: 88, fontWeight: 800, color: MINT, marginRight: 6}}>$</span>
          <span style={{fontSize: 140, fontWeight: 800, letterSpacing: -4, color: INK, fontVariantNumeric: "tabular-nums"}}>{formatMoney(count)}</span>
        </div>
        <div style={{display: "flex", alignItems: "center", gap: 16, marginTop: 20, opacity: sub, transform: `translateY(${interpolate(sub, [0, 1], [12, 0])}px)`}}>
          <div style={{display: "flex", alignItems: "center", gap: 9, padding: "7px 15px", borderRadius: 20, background: "rgba(70,227,181,0.12)", border: "1px solid rgba(70,227,181,0.35)"}}>
            <div style={{width: 0, height: 0, borderLeft: "6px solid transparent", borderRight: "6px solid transparent", borderBottom: `9px solid ${MINT}`}} />
            <span style={{fontSize: 22, fontWeight: 600, color: MINT}}>12% under budget</span>
          </div>
          <span style={{fontSize: 22, color: MUTED}}>tracked this month</span>
        </div>
      </div>
    </AbsoluteFill>
  );
};

type Row = {label: string; base: number; target: number; delay: number};
const ROWS: Row[] = [
  {label: "Rent", base: 0.78, target: 0.78, delay: 0},
  {label: "Food", base: 0.62, target: 0.46, delay: 6},
  {label: "Transit", base: 0.34, target: 0.34, delay: 12},
  {label: "Savings", base: 0.40, target: 0.60, delay: 18},
];

const BarRow: React.FC<{row: Row; trackW: number}> = ({row, trackW}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const adjStart = Math.round(1.85 * fps);
  const grow = interpolate(frame, [row.delay, row.delay + 16], [0, row.base], {...clamp, easing: ease});
  const adj = interpolate(frame, [adjStart, adjStart + 18], [row.base, row.target], {...clamp, easing: easeInOut});
  const frac = frame < adjStart ? grow : adj;
  const labelO = interpolate(frame, [row.delay, row.delay + 12], [0, 1], {...clamp, easing: ease});
  return (
    <div style={{display: "flex", alignItems: "center", gap: 22, marginBottom: 22}}>
      <div style={{width: 130, textAlign: "right", fontSize: 24, fontWeight: 600, color: MUTED, opacity: labelO}}>{row.label}</div>
      <div style={{width: trackW, height: 26, borderRadius: 13, background: "rgba(120,150,170,0.10)", position: "relative", overflow: "hidden"}}>
        <div style={{position: "absolute", left: 0, top: 0, bottom: 0, width: frac * trackW, borderRadius: 13, background: `linear-gradient(90deg, ${MINT_DEEP}, ${MINT})`}} />
      </div>
    </div>
  );
};

// Beat 3 — "Budgets that adjust": bars draw on, then Food yields to Savings.
const Budgets: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const env = envelope(frame, durationInFrames, fps);
  const head = interpolate(frame, [4, 20], [0, 1], {...clamp, easing: ease});
  const cap = interpolate(frame, [2.1 * fps, 2.45 * fps], [0, 1], {...clamp, easing: ease});
  return (
    <AbsoluteFill style={{fontFamily, opacity: env, justifyContent: "center", paddingLeft: 150, paddingRight: 130}}>
      <div style={{fontSize: 40, fontWeight: 800, letterSpacing: -1, color: INK, opacity: head, transform: `translateY(${interpolate(head, [0, 1], [16, 0])}px)`, marginBottom: 34}}>
        Budgets that adjust
      </div>
      {ROWS.map((r, i) => <BarRow key={i} row={r} trackW={740} />)}
      <div style={{marginTop: 6, fontSize: 22, color: MUTED, opacity: cap, paddingLeft: 152}}>
        Ledgr rebalances the moment life changes.
      </div>
    </AbsoluteFill>
  );
};

// Beat 4 — "Save without thinking": a savings line that draws on + endpoint pop.
const Save: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const env = envelope(frame, durationInFrames, fps);
  const head = interpolate(frame, [4, 20], [0, 1], {...clamp, easing: ease});
  const prog = interpolate(frame, [16, 16 + 1.4 * fps], [0, 1], {...clamp, easing: ease});
  const area = interpolate(prog, [0.55, 1], [0, 0.16], {...clamp});
  const dot = spring({frame: frame - Math.round(1.55 * fps), fps, config: {damping: 11}});
  const callout = interpolate(frame, [1.7 * fps, 2.0 * fps], [0, 1], {...clamp, easing: ease});
  return (
    <AbsoluteFill style={{fontFamily, opacity: env, justifyContent: "center", paddingLeft: 150}}>
      <div style={{fontSize: 40, fontWeight: 800, letterSpacing: -1, color: INK, opacity: head, transform: `translateY(${interpolate(head, [0, 1], [16, 0])}px)`}}>
        Save without thinking
      </div>
      <div style={{position: "relative", width: 760, height: 300, marginTop: 16}}>
        <svg width={760} height={300} viewBox="0 0 760 300" style={{position: "absolute", left: 0, top: 0}}>
          <path d="M60 250 L180 215 L300 225 L420 160 L540 125 L680 60 L680 300 L60 300 Z" fill={MINT} opacity={area} />
          <path d="M60 250 L180 215 L300 225 L420 160 L540 125 L680 60" fill="none" stroke={MINT} strokeWidth={5} strokeLinecap="round" strokeLinejoin="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - prog} />
          <circle cx={680} cy={60} r={interpolate(dot, [0, 1], [9, 22])} fill="none" stroke={MINT} strokeWidth={2} opacity={interpolate(dot, [0, 1], [0.6, 0])} />
          <circle cx={680} cy={60} r={9} fill={MINT} opacity={dot} />
        </svg>
        <div style={{position: "absolute", left: 560, top: -6, opacity: callout, transform: `translateY(${interpolate(callout, [0, 1], [10, 0])}px)`}}>
          <div style={{fontSize: 36, fontWeight: 800, color: MINT}}>+$340</div>
          <div style={{fontSize: 18, color: MUTED}}>auto-saved / mo</div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// Beat 5 — calm CTA lockup.
const CTA: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const env = envelope(frame, durationInFrames, fps);
  const pop = spring({frame, fps, config: {damping: 13, mass: 0.8}});
  const underline = interpolate(frame, [14, 36], [0, 1], {...clamp, easing: ease});
  const tag = interpolate(frame, [20, 38], [0, 1], {...clamp, easing: ease});
  const btn = spring({frame: frame - Math.round(0.9 * fps), fps, config: {damping: 12}});
  return (
    <AbsoluteFill style={{fontFamily, opacity: env, justifyContent: "center", alignItems: "center"}}>
      <div style={{display: "flex", flexDirection: "column", alignItems: "center"}}>
        <div style={{display: "flex", alignItems: "flex-end", gap: 14, opacity: pop, transform: `scale(${interpolate(pop, [0, 1], [0.85, 1])})`}}>
          <div style={{fontSize: 120, fontWeight: 800, letterSpacing: -5}}>
            <span style={{color: MINT}}>L</span><span style={{color: INK}}>edgr</span>
          </div>
          <div style={{width: 16, height: 16, borderRadius: "50%", background: MINT, marginBottom: 26}} />
        </div>
        <div style={{height: 5, borderRadius: 3, background: MINT, width: interpolate(underline, [0, 1], [0, 260]), marginTop: 4}} />
        <div style={{marginTop: 22, fontSize: 28, fontWeight: 500, color: MUTED, opacity: tag}}>Money, made calm.</div>
        <div style={{marginTop: 30, padding: "16px 42px", borderRadius: 32, background: MINT, opacity: btn, transform: `translateY(${interpolate(btn, [0, 1], [18, 0])}px) scale(${interpolate(btn, [0, 1], [0.9, 1])})`}}>
          <span style={{fontSize: 24, fontWeight: 700, color: "#06121f"}}>Download free</span>
        </div>
      </div>
    </AbsoluteFill>
  );
};

const Main: React.FC = () => (
  <AbsoluteFill style={{background: BG}}>
    <Backdrop />
    <Series>
      <Series.Sequence durationInFrames={66}><Brand /></Series.Sequence>
      <Series.Sequence durationInFrames={84}><Dollars /></Series.Sequence>
      <Series.Sequence durationInFrames={84}><Budgets /></Series.Sequence>
      <Series.Sequence durationInFrames={66}><Save /></Series.Sequence>
      <Series.Sequence durationInFrames={60}><CTA /></Series.Sequence>
    </Series>
  </AbsoluteFill>
);

export const Root: React.FC = () => (
  <Composition id="Video" component={Main} durationInFrames={360} fps={30} width={1280} height={720} />
);

registerRoot(Root);