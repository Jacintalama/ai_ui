import React from "react";
import {
  AbsoluteFill, Series, useCurrentFrame, useVideoConfig,
  interpolate, spring, Easing, random, registerRoot, Composition,
} from "remotion";
import {loadFont as loadDisplay} from "@remotion/google-fonts/Anton";
import {loadFont as loadText} from "@remotion/google-fonts/Inter";

const {fontFamily: DISPLAY} = loadDisplay();
const {fontFamily: TEXT} = loadText();

const BG = "radial-gradient(130% 120% at 72% 16%, #1d1d20 0%, #101012 52%, #060607 100%)";
const WHITE = "#F4F3F1";
const ORANGE = "#FF5A1F";
const ORANGE_HI = "#FF8A45";
const MUTE = "#7C7C82";
const TRACK = "#262629";

const clamp = {extrapolateLeft: "clamp", extrapolateRight: "clamp"} as const;
const easeOut = Easing.bezier(0.16, 1, 0.3, 1);

// Quick fade in / out per scene (energetic, short).
function envelope(frame: number, dur: number, fps: number): number {
  const fin = 0.16 * fps;
  const fout = 0.24 * fps;
  return (
    interpolate(frame, [0, fin], [0, 1], clamp) *
    interpolate(frame, [dur - fout, dur], [1, 0], clamp)
  );
}

// Diagonal speed streaks racing across — continuous, global frame (sits outside the Series).
const Speedlines: React.FC = () => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const N = 16;
  return (
    <AbsoluteFill>
      {new Array(N).fill(0).map((_, i) => {
        const seed = `streak-${i}`;
        const y = random(seed + "y") * height;
        const len = 110 + random(seed + "l") * 260;
        const speed = 7 + random(seed + "v") * 10;
        const wrap = width + 480;
        const x = width + 220 - ((frame * speed + random(seed + "o") * wrap) % wrap);
        const isOrange = random(seed + "c") > 0.8;
        const op = 0.05 + random(seed + "a") * 0.13;
        return (
          <div key={i} style={{
            position: "absolute", left: x, top: y, width: len,
            height: isOrange ? 3 : 2, background: isOrange ? ORANGE : WHITE,
            opacity: op, transform: "rotate(-18deg)", borderRadius: 2,
          }} />
        );
      })}
    </AbsoluteFill>
  );
};

// Bottom pace line that fills across the whole 10s — the running progress motif.
const GlobalProgress: React.FC = () => {
  const frame = useCurrentFrame();
  const {durationInFrames, fps} = useVideoConfig();
  const p = interpolate(frame, [0, durationInFrames], [0, 1], clamp);
  const pulse = 0.55 + 0.45 * Math.sin((frame / fps) * Math.PI * 2);
  return (
    <AbsoluteFill>
      <div style={{position: "absolute", left: 0, bottom: 0, height: 6, width: `${p * 100}%`, background: ORANGE}} />
      <div style={{position: "absolute", bottom: 1, left: `${p * 100}%`, width: 12, height: 12, marginLeft: -6, borderRadius: 6, background: ORANGE_HI, opacity: pulse, boxShadow: `0 0 18px ${ORANGE}`}} />
    </AbsoluteFill>
  );
};

// A word that slams in from the left with a snap + tiny overshoot.
const Slam: React.FC<{text: string; delay: number; size: number; color: string}> = ({text, delay, size, color}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame: Math.max(0, frame - delay), fps, config: {damping: 14, mass: 0.7, stiffness: 170}});
  const x = interpolate(s, [0, 1], [-70, 0]);
  const sc = interpolate(s, [0, 1], [1.16, 1]);
  const op = interpolate(frame, [delay, delay + 4], [0, 1], clamp);
  return (
    <div style={{fontFamily: DISPLAY, fontSize: size, lineHeight: 0.92, color, letterSpacing: -1, opacity: op, transform: `translateX(${x}px) scale(${sc})`, transformOrigin: "left center"}}>
      {text}
    </div>
  );
};

// Scene 1 — "Lace up."
const LaceUp: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const env = envelope(frame, durationInFrames, fps);
  const kick = interpolate(frame, [2, 12], [0, 1], clamp);
  const line = interpolate(frame, [16, 34], [0, 1], {...clamp, easing: easeOut});
  const drift = Math.sin((frame / fps) * Math.PI * 2) * 3;
  return (
    <AbsoluteFill style={{opacity: env, paddingLeft: 120, justifyContent: "center", transform: `translateY(${drift}px)`}}>
      <div style={{fontFamily: TEXT, fontSize: 24, fontWeight: 700, letterSpacing: 8, color: ORANGE, opacity: kick, transform: `translateX(${interpolate(kick, [0, 1], [-22, 0])}px)`}}>
        01 — READY
      </div>
      <div style={{marginTop: 18, display: "flex", flexDirection: "column"}}>
        <Slam text="LACE" delay={6} size={178} color={WHITE} />
        <Slam text="UP." delay={15} size={178} color={ORANGE} />
      </div>
      <div style={{height: 6, width: interpolate(line, [0, 1], [0, 340]), background: WHITE, marginTop: 26}} />
    </AbsoluteFill>
  );
};

// Scene 2 — "Chase the streak." with a streak-of-days row lighting up.
const ChaseStreak: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const env = envelope(frame, durationInFrames, fps);
  const drift = Math.sin((frame / fps) * Math.PI * 2 + 1) * 3;
  return (
    <AbsoluteFill style={{opacity: env, paddingLeft: 120, justifyContent: "center", transform: `translateY(${drift}px)`}}>
      <Slam text="CHASE THE" delay={4} size={90} color={WHITE} />
      <Slam text="STREAK." delay={13} size={186} color={ORANGE} />
      <div style={{display: "flex", gap: 12, marginTop: 34}}>
        {new Array(7).fill(0).map((_, i) => {
          const t = interpolate(frame, [26 + i * 5, 26 + i * 5 + 11], [0, 1], {...clamp, easing: easeOut});
          const filled = i < 6;
          return (
            <div key={i} style={{
              width: 48, height: 48, borderRadius: 11,
              background: filled ? ORANGE : "transparent",
              border: `3px solid ${filled ? ORANGE : MUTE}`,
              opacity: filled ? t : 0.45 * t,
              transform: `scale(${interpolate(t, [0, 1], [0.4, 1])})`,
            }} />
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// Scene 3 — the pace / progress hero: distance count-up + filling bar + moving marker.
const PaceMeter: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const env = envelope(frame, durationInFrames, fps);
  const prog = interpolate(frame, [10, 62], [0, 1], {...clamp, easing: easeOut});
  const dist = (prog * 5).toFixed(2);
  const kick = interpolate(frame, [2, 12], [0, 1], clamp);
  const paceOp = interpolate(frame, [40, 56], [0, 1], {...clamp, easing: easeOut});
  const barLen = 920;
  const pulse = 14 + 8 * Math.sin((frame / fps) * Math.PI * 3);
  return (
    <AbsoluteFill style={{opacity: env, paddingLeft: 120, justifyContent: "center"}}>
      <div style={{fontFamily: TEXT, fontSize: 24, fontWeight: 700, letterSpacing: 8, color: ORANGE, opacity: kick}}>
        TODAY'S RUN
      </div>
      <div style={{display: "flex", alignItems: "flex-end", gap: 18, marginTop: 6}}>
        <div style={{fontFamily: DISPLAY, fontSize: 200, lineHeight: 0.9, color: WHITE, letterSpacing: -2, fontVariantNumeric: "tabular-nums"}}>{dist}</div>
        <div style={{fontFamily: DISPLAY, fontSize: 68, color: ORANGE, marginBottom: 22}}>KM</div>
        <div style={{marginLeft: 46, marginBottom: 30, fontFamily: TEXT, opacity: paceOp, transform: `translateY(${interpolate(paceOp, [0, 1], [12, 0])}px)`}}>
          <div style={{fontSize: 21, color: MUTE, letterSpacing: 4, fontWeight: 600}}>AVG PACE</div>
          <div style={{fontSize: 40, color: WHITE, fontWeight: 800}}>4:48<span style={{color: MUTE, fontSize: 24}}> /km</span></div>
        </div>
      </div>
      <div style={{position: "relative", width: barLen, height: 10, marginTop: 32, background: TRACK, borderRadius: 5}}>
        <div style={{position: "absolute", left: 0, top: 0, height: 10, width: barLen * prog, background: `linear-gradient(90deg, ${ORANGE} 0%, ${ORANGE_HI} 100%)`, borderRadius: 5}} />
        {new Array(6).fill(0).map((_, i) => (
          <div key={i} style={{position: "absolute", left: (barLen / 5) * i, top: -6, width: 2, height: 22, background: MUTE, opacity: 0.5}} />
        ))}
        <div style={{position: "absolute", left: barLen * prog, top: 5, width: 26, height: 26, marginLeft: -13, marginTop: -13, borderRadius: 13, background: WHITE, border: `4px solid ${ORANGE}`, boxShadow: `0 0 ${pulse}px ${ORANGE}`}} />
      </div>
    </AbsoluteFill>
  );
};

// Scene 4 — "Stride." lockup with forward chevrons + drawn underline.
const StrideOutro: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const env = envelope(frame, durationInFrames, fps);
  const s = spring({frame, fps, config: {damping: 13, mass: 0.8, stiffness: 160}});
  const sc = interpolate(s, [0, 1], [1.22, 1]);
  const op = interpolate(frame, [0, 5], [0, 1], clamp);
  const line = interpolate(frame, [18, 38], [0, 1], {...clamp, easing: easeOut});
  const tag = interpolate(frame, [28, 44], [0, 1], {...clamp, easing: easeOut});
  return (
    <AbsoluteFill style={{opacity: env, justifyContent: "center", alignItems: "center"}}>
      <div style={{display: "flex", alignItems: "center", gap: 22}}>
        <div style={{display: "flex", gap: 7}}>
          {[0, 1, 2].map((i) => {
            const c = interpolate((frame + i * 6) % 30, [0, 15, 30], [0.12, 1, 0.12], clamp);
            return (
              <div key={i} style={{width: 0, height: 0, borderTop: "23px solid transparent", borderBottom: "23px solid transparent", borderLeft: `27px solid ${ORANGE}`, opacity: c}} />
            );
          })}
        </div>
        <div style={{fontFamily: DISPLAY, fontSize: 208, color: WHITE, letterSpacing: -3, opacity: op, transform: `scale(${sc})`}}>
          STRIDE<span style={{color: ORANGE}}>.</span>
        </div>
      </div>
      <div style={{height: 7, width: interpolate(line, [0, 1], [0, 520]), background: ORANGE, marginTop: 12}} />
      <div style={{fontFamily: TEXT, fontWeight: 700, fontSize: 29, letterSpacing: 10, color: WHITE, opacity: tag, marginTop: 26, transform: `translateY(${interpolate(tag, [0, 1], [14, 0])}px)`}}>
        EVERY STEP COUNTS
      </div>
    </AbsoluteFill>
  );
};

const Main: React.FC = () => (
  <AbsoluteFill style={{background: BG}}>
    <Speedlines />
    <Series>
      <Series.Sequence durationInFrames={70}><LaceUp /></Series.Sequence>
      <Series.Sequence durationInFrames={75}><ChaseStreak /></Series.Sequence>
      <Series.Sequence durationInFrames={80}><PaceMeter /></Series.Sequence>
      <Series.Sequence durationInFrames={75}><StrideOutro /></Series.Sequence>
    </Series>
    <GlobalProgress />
  </AbsoluteFill>
);

export const Root: React.FC = () => (
  <Composition id="Video" component={Main} durationInFrames={300} fps={30} width={1280} height={720} />
);

registerRoot(Root);