import React from "react";
import {
  AbsoluteFill, Series, useCurrentFrame, useVideoConfig,
  interpolate, spring, Easing, registerRoot, Composition,
} from "remotion";
import {loadFont as loadDisplay} from "@remotion/google-fonts/SpaceGrotesk";
import {loadFont as loadMono} from "@remotion/google-fonts/JetBrainsMono";

const {fontFamily: display} = loadDisplay();
const {fontFamily: mono} = loadMono();

// ---- palette: near-black, electric purple, cyan ----------------------------
const BG = "radial-gradient(135% 120% at 72% 4%, #1d1340 0%, #0e0a20 46%, #050409 100%)";
const INK = "#ecebff";
const MUTE = "#827fb0";
const PURPLE = "#a855f7";
const CYAN = "#3ae8ff";

const CLAMP = {extrapolateLeft: "clamp", extrapolateRight: "clamp"} as const;
const ease = Easing.bezier(0.16, 1, 0.3, 1);          // ease-out: arrive + settle
const easeInOut = Easing.bezier(0.7, 0, 0.3, 1);

// fade a scene in/out so cuts breathe (all frame-derived, no wall-clock).
function env(frame: number, dur: number, fps: number, fi = 0.3, fo = 0.27): number {
  return (
    interpolate(frame, [0, fi * fps], [0, 1], CLAMP) *
    interpolate(frame, [dur - fo * fps, dur], [1, 0], CLAMP)
  );
}

function hexRgb(h: string): number[] {
  const n = parseInt(h.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function blend(a: string, b: string, t: number): string {
  const A = hexRgb(a), B = hexRgb(b);
  return `rgb(${Math.round(A[0] + (B[0] - A[0]) * t)},${Math.round(A[1] + (B[1] - A[1]) * t)},${Math.round(A[2] + (B[2] - A[2]) * t)})`;
}
const gradText = (deg = 100): React.CSSProperties => ({
  backgroundImage: `linear-gradient(${deg}deg, ${PURPLE} 0%, ${CYAN} 100%)`,
  WebkitBackgroundClip: "text",
  backgroundClip: "text",
  WebkitTextFillColor: "transparent",
  color: "transparent",
});

// ---- ambient depth: drifting glow blobs + neural dust ----------------------
const BgGlow: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  const x1 = 330 + Math.sin(t * 0.5) * 60, y1 = 210 + Math.cos(t * 0.4) * 48;
  const x2 = 980 + Math.cos(t * 0.45) * 70, y2 = 470 + Math.sin(t * 0.55) * 54;
  return (
    <AbsoluteFill style={{pointerEvents: "none"}}>
      <div style={{position: "absolute", left: x1 - 260, top: y1 - 260, width: 520, height: 520, borderRadius: "50%", background: `radial-gradient(circle, ${PURPLE}, transparent 65%)`, opacity: 0.18, filter: "blur(22px)"}} />
      <div style={{position: "absolute", left: x2 - 240, top: y2 - 240, width: 480, height: 480, borderRadius: "50%", background: `radial-gradient(circle, ${CYAN}, transparent 65%)`, opacity: 0.13, filter: "blur(22px)"}} />
    </AbsoluteFill>
  );
};

const DUST = Array.from({length: 48}, (_, i) => ({
  x: ((i * 79) % 128) / 128,
  y: ((i * 47 + 13) % 72) / 72,
  r: 1 + (i % 3),
  c: i % 3 === 0 ? CYAN : PURPLE,
  ph: i * 0.7,
}));
const Dust: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return (
    <AbsoluteFill style={{pointerEvents: "none"}}>
      {DUST.map((d, i) => {
        const tw = 0.05 + 0.07 * (0.5 + 0.5 * Math.sin(frame / (fps * 0.8) + d.ph));
        const dx = Math.sin(frame / (fps * 2) + d.ph) * 6;
        const dy = Math.cos(frame / (fps * 2.4) + d.ph) * 6;
        return <div key={i} style={{position: "absolute", left: d.x * 1280, top: d.y * 720, width: d.r * 2, height: d.r * 2, borderRadius: "50%", background: d.c, opacity: tw, transform: `translate(${dx}px,${dy}px)`, filter: "blur(0.5px)"}} />;
      })}
    </AbsoluteFill>
  );
};

const Kicker: React.FC<{label: string; show: number; color?: string}> = ({label, show, color = CYAN}) => (
  <div style={{display: "flex", alignItems: "center", gap: 12, fontFamily: mono, fontSize: 18, letterSpacing: 5, color, opacity: show, textTransform: "uppercase"}}>
    <span style={{width: 9, height: 9, borderRadius: "50%", background: color, boxShadow: `0 0 12px ${color}`}} />
    {label}
  </div>
);

// ---- 1. hook: "Synapse" wordmark + glowing caret ---------------------------
const Hook: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const e = env(frame, durationInFrames, fps);
  const word = "Synapse".split("");
  const kick = interpolate(frame, [4, 18], [0, 1], {...CLAMP, easing: ease});
  const sub = interpolate(frame, [44, 64], [0, 1], {...CLAMP, easing: ease});
  const lineP = interpolate(frame, [34, 66], [0, 1], {...CLAMP, easing: easeInOut});
  const blink = 0.4 + 0.6 * Math.sin((frame / fps) * Math.PI * 2 * 1.6);
  return (
    <AbsoluteFill style={{justifyContent: "center", paddingLeft: 150, fontFamily: display, opacity: e}}>
      <div style={{marginBottom: 26}}><Kicker label="Neural notes" show={kick} /></div>
      <div style={{display: "flex", alignItems: "flex-end"}}>
        {word.map((ch, i) => {
          const p = spring({frame: frame - 6 - i * 3, fps, config: {damping: 16, mass: 0.8}});
          return (
            <span key={i} style={{display: "inline-block", fontSize: 152, fontWeight: 700, letterSpacing: -5, lineHeight: 1, color: blend(PURPLE, CYAN, i / (word.length - 1)), textShadow: `0 0 34px ${blend(PURPLE, CYAN, i / (word.length - 1))}55`, transform: `translateY(${interpolate(p, [0, 1], [64, 0])}px)`, opacity: Math.min(1, p)}}>
              {ch}
            </span>
          );
        })}
        <div style={{width: 9, height: 116, marginLeft: 12, marginBottom: 16, borderRadius: 4, background: CYAN, boxShadow: `0 0 28px ${CYAN}, 0 0 10px ${CYAN}`, opacity: blink}} />
      </div>
      <div style={{position: "relative", height: 2, marginTop: 30, marginBottom: 24}}>
        <div style={{height: 2, width: interpolate(lineP, [0, 1], [0, 540]), background: `linear-gradient(90deg, ${PURPLE}, ${CYAN})`, boxShadow: `0 0 10px ${CYAN}66`}} />
        <div style={{position: "absolute", left: interpolate(lineP, [0, 1], [0, 540]), top: -4, width: 10, height: 10, borderRadius: "50%", background: CYAN, boxShadow: `0 0 14px ${CYAN}`}} />
      </div>
      <div style={{fontSize: 32, fontWeight: 500, color: MUTE, letterSpacing: 0.5, opacity: sub, transform: `translateY(${interpolate(sub, [0, 1], [12, 0])}px)`}}>
        The notebook that thinks with you.
      </div>
    </AbsoluteFill>
  );
};

// ---- 2. capture: glowing cursor types the line -----------------------------
const Capture: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const e = env(frame, durationInFrames, fps);
  const full = "Capture the thought";
  const chars = full.length;
  const typed = Math.floor(interpolate(frame, [10, 10 + chars * 2], [0, chars], CLAMP));
  const shown = full.slice(0, Math.max(0, typed));
  const done = typed >= chars;
  const p = typed / chars;
  const blink = 0.5 + 0.5 * Math.sin((frame / fps) * Math.PI * 2 * 1.6);
  const caretO = done ? blink : 1;
  const kick = interpolate(frame, [2, 16], [0, 1], {...CLAMP, easing: ease});
  const tail = interpolate(frame, [56, 74], [0, 1], {...CLAMP, easing: ease});
  return (
    <AbsoluteFill style={{justifyContent: "center", alignItems: "flex-start", paddingLeft: 150, fontFamily: display, opacity: e}}>
      <div style={{marginBottom: 34}}><Kicker label="01 — Capture" show={kick} color={PURPLE} /></div>
      <div style={{display: "inline-block", position: "relative"}}>
        <div style={{display: "flex", alignItems: "center"}}>
          <span style={{fontSize: 98, fontWeight: 700, color: INK, letterSpacing: -3, lineHeight: 1.05}}>{shown}</span>
          <div style={{width: 7, height: 78, marginLeft: 7, borderRadius: 3, background: CYAN, boxShadow: `0 0 24px ${CYAN}, 0 0 8px ${CYAN}`, opacity: caretO, transform: `scaleY(${0.9 + 0.1 * Math.sin(frame * 0.5)})`}} />
        </div>
        <div style={{height: 4, borderRadius: 2, marginTop: 16, background: `linear-gradient(90deg, ${PURPLE}, ${CYAN})`, boxShadow: `0 0 14px ${CYAN}`, transformOrigin: "left", transform: `scaleX(${p})`, opacity: 0.9}} />
      </div>
      <div style={{marginTop: 30, fontFamily: mono, fontSize: 22, color: MUTE, letterSpacing: 2, opacity: tail, transform: `translateY(${interpolate(tail, [0, 1], [10, 0])}px)`}}>
        Type, talk, or clip — it&apos;s captured.
      </div>
    </AbsoluteFill>
  );
};

// ---- 3. connect: the neural node graph (distinctive element) ---------------
const NODES = [
  {x: 705, y: 165, r: 9, c: CYAN},
  {x: 880, y: 120, r: 8, c: PURPLE},
  {x: 1040, y: 205, r: 8, c: CYAN},
  {x: 1090, y: 360, r: 10, c: PURPLE},
  {x: 905, y: 330, r: 14, c: CYAN},
  {x: 760, y: 430, r: 8, c: PURPLE},
  {x: 980, y: 480, r: 9, c: CYAN},
  {x: 1140, y: 140, r: 7, c: PURPLE},
];
const EDGES: number[][] = [[0, 1], [1, 2], [2, 7], [1, 4], [4, 3], [3, 6], [4, 5], [0, 4], [4, 6], [2, 3]];

const Connect: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const e = env(frame, durationInFrames, fps);
  const kick = interpolate(frame, [2, 16], [0, 1], {...CLAMP, easing: ease});
  const head = [
    [{t: "It", c: INK}, {t: "connects", c: CYAN}],
    [{t: "the", c: INK}, {t: "dots.", c: PURPLE}],
  ];
  let wi = 0;
  return (
    <AbsoluteFill style={{fontFamily: display, opacity: e}}>
      <svg width={1280} height={720} viewBox="0 0 1280 720" style={{position: "absolute", inset: 0, filter: `drop-shadow(0 0 9px ${PURPLE}55)`}}>
        <defs>
          <linearGradient id="edge" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor={PURPLE} />
            <stop offset="1" stopColor={CYAN} />
          </linearGradient>
        </defs>
        {EDGES.map((eg, i) => {
          const a = NODES[eg[0]], b = NODES[eg[1]];
          const len = Math.hypot(b.x - a.x, b.y - a.y);
          const pr = interpolate(frame, [12 + i * 4, 12 + i * 4 + 16], [0, 1], {...CLAMP, easing: ease});
          const pulse = ((frame * 1.1 + i * 13) % 78) / 78;
          const px = a.x + (b.x - a.x) * pulse, py = a.y + (b.y - a.y) * pulse;
          const po = pr > 0.98 ? interpolate(pulse, [0, 0.12, 0.88, 1], [0, 1, 1, 0], CLAMP) : 0;
          return (
            <g key={i}>
              <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="url(#edge)" strokeWidth={2} strokeLinecap="round" strokeOpacity={0.55} strokeDasharray={len} strokeDashoffset={len * (1 - pr)} />
              <circle cx={px} cy={py} r={3} fill="#ffffff" opacity={po} />
            </g>
          );
        })}
        {NODES.map((n, i) => {
          const pop = spring({frame: frame - 10 - i * 3, fps, config: {damping: 12, mass: 0.6}});
          const breath = 1 + 0.06 * Math.sin(frame / 12 + i);
          const s = Math.min(1, pop) * breath;
          return (
            <g key={i} opacity={Math.min(1, pop)}>
              <circle cx={n.x} cy={n.y} r={n.r * 2.6 * s} fill={n.c} opacity={0.16} />
              <circle cx={n.x} cy={n.y} r={n.r * s} fill={n.c} />
              <circle cx={n.x} cy={n.y} r={n.r * 0.42 * s} fill="#ffffff" opacity={0.9} />
            </g>
          );
        })}
      </svg>
      <div style={{position: "absolute", left: 140, top: 92}}><Kicker label="02 — Connect" show={kick} /></div>
      <div style={{position: "absolute", left: 140, bottom: 110}}>
        {head.map((row, r) => (
          <div key={r} style={{display: "flex", gap: 22, lineHeight: 1.02}}>
            {row.map((w) => {
              const j = wi++;
              const t = interpolate(frame, [26 + j * 7, 26 + j * 7 + 16], [0, 1], {...CLAMP, easing: ease});
              return (
                <span key={w.t} style={{fontSize: 112, fontWeight: 700, letterSpacing: -4, color: w.c, opacity: t, transform: `translateY(${interpolate(t, [0, 1], [34, 0])}px)`, textShadow: w.c === INK ? "none" : `0 0 30px ${w.c}55`}}>
                  {w.t}
                </span>
              );
            })}
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};

// ---- 4. recall: fast kinetic snap ------------------------------------------
const Recall: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const e = env(frame, durationInFrames, fps);
  const kick = interpolate(frame, [2, 14], [0, 1], {...CLAMP, easing: ease});
  const r1 = spring({frame, fps, config: {damping: 14, mass: 0.7}});
  const snap = spring({frame: frame - 12, fps, config: {damping: 9, mass: 0.9, stiffness: 150}});
  const streakX = interpolate(frame, [12, 34], [-720, 720], {...CLAMP, easing: easeInOut});
  const streakO = interpolate(frame, [12, 20, 40], [0, 0.85, 0], CLAMP);
  const chip = interpolate(frame, [30, 44], [0, 1], {...CLAMP, easing: ease});
  return (
    <AbsoluteFill style={{justifyContent: "center", alignItems: "flex-start", paddingLeft: 150, fontFamily: display, opacity: e}}>
      <div style={{marginBottom: 26}}><Kicker label="03 — Recall" show={kick} color={PURPLE} /></div>
      <div style={{position: "relative"}}>
        <div style={{position: "absolute", left: 0, top: 96, width: 620, height: 4, borderRadius: 2, background: `linear-gradient(90deg, transparent, ${CYAN}, transparent)`, boxShadow: `0 0 18px ${CYAN}`, opacity: streakO, transform: `translateX(${streakX}px)`}} />
        <div style={{fontSize: 132, fontWeight: 700, letterSpacing: -5, color: INK, lineHeight: 0.98, transform: `translateY(${interpolate(r1, [0, 1], [50, 0])}px)`, opacity: Math.min(1, r1)}}>
          Recall
        </div>
        <div style={{fontSize: 132, fontWeight: 700, letterSpacing: -5, ...gradText(95), lineHeight: 1, transform: `translateX(${interpolate(snap, [0, 1], [44, 0])}px) scale(${interpolate(snap, [0, 1], [0.7, 1])})`, transformOrigin: "left center", opacity: Math.min(1, snap), filter: `drop-shadow(0 0 26px ${CYAN}66)`}}>
          instantly.
        </div>
      </div>
      <div style={{display: "flex", alignItems: "center", gap: 16, marginTop: 38, opacity: chip, transform: `translateY(${interpolate(chip, [0, 1], [12, 0])}px)`}}>
        <span style={{fontFamily: mono, fontSize: 18, letterSpacing: 3, color: CYAN, border: `1px solid ${CYAN}55`, borderRadius: 999, padding: "8px 16px", boxShadow: `0 0 16px ${CYAN}22`}}>
          FOUND IN 0.02s
        </span>
        <div style={{display: "flex", gap: 8}}>
          {[0, 1, 2].map((i) => {
            const o = interpolate(frame, [32 + i * 4, 32 + i * 4 + 8], [0, 1], {...CLAMP, easing: ease});
            return <div key={i} style={{width: 64, height: 10, borderRadius: 5, background: i === 0 ? PURPLE : `${MUTE}66`, opacity: o, transform: `scaleX(${o})`, transformOrigin: "left"}} />;
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ---- 5. outro: brand resolve + CTA -----------------------------------------
const Outro: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const e = env(frame, durationInFrames, fps, 0.3, 0.34);
  const pop = spring({frame, fps, config: {damping: 13, mass: 0.8}});
  const tag = interpolate(frame, [22, 40], [0, 1], {...CLAMP, easing: ease});
  const cta = spring({frame: frame - 32, fps, config: {damping: 12, mass: 0.7}});
  const drift = 1 + 0.012 * Math.sin(frame / 20);
  const pulse = (frame % 90) / 90;
  return (
    <AbsoluteFill style={{justifyContent: "center", alignItems: "center", fontFamily: display, opacity: e}}>
      <div style={{display: "flex", flexDirection: "column", alignItems: "center", transform: `scale(${drift})`}}>
        <div style={{fontSize: 150, fontWeight: 700, letterSpacing: -5, ...gradText(100), transform: `translateY(${interpolate(pop, [0, 1], [44, 0])}px) scale(${interpolate(pop, [0, 1], [0.86, 1])})`, opacity: Math.min(1, pop), filter: `drop-shadow(0 0 36px ${PURPLE}55)`}}>
          Synapse
        </div>
        <div style={{position: "relative", width: 360, height: 2, marginTop: 18, marginBottom: 30}}>
          <div style={{position: "absolute", inset: 0, background: `linear-gradient(90deg, transparent, ${PURPLE}, ${CYAN}, transparent)`, opacity: tag}} />
          <div style={{position: "absolute", top: -4, left: pulse * 360, width: 10, height: 10, borderRadius: "50%", background: CYAN, boxShadow: `0 0 14px ${CYAN}`, opacity: tag}} />
        </div>
        <div style={{fontFamily: mono, fontSize: 20, letterSpacing: 6, color: MUTE, opacity: tag}}>
          YOUR SECOND BRAIN, WIRED
        </div>
        <div style={{marginTop: 40, fontSize: 26, fontWeight: 500, color: "#04030a", background: `linear-gradient(100deg, ${PURPLE}, ${CYAN})`, padding: "16px 34px", borderRadius: 999, boxShadow: `0 0 30px ${CYAN}44`, opacity: Math.min(1, cta), transform: `translateY(${interpolate(cta, [0, 1], [20, 0])}px) scale(${interpolate(cta, [0, 1], [0.9, 1])})`}}>
          Start capturing  →
        </div>
      </div>
    </AbsoluteFill>
  );
};

const Main: React.FC = () => (
  <AbsoluteFill style={{background: BG}}>
    <BgGlow />
    <Dust />
    <Series>
      <Series.Sequence durationInFrames={90}><Hook /></Series.Sequence>
      <Series.Sequence durationInFrames={90}><Capture /></Series.Sequence>
      <Series.Sequence durationInFrames={120}><Connect /></Series.Sequence>
      <Series.Sequence durationInFrames={75}><Recall /></Series.Sequence>
      <Series.Sequence durationInFrames={75}><Outro /></Series.Sequence>
    </Series>
    <AbsoluteFill style={{pointerEvents: "none", background: "radial-gradient(100% 100% at 50% 45%, transparent 55%, rgba(3,2,8,0.55) 100%)"}} />
  </AbsoluteFill>
);

export const Root: React.FC = () => (
  <Composition id="Video" component={Main} durationInFrames={450} fps={30} width={1280} height={720} />
);

registerRoot(Root);