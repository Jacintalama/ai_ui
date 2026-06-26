import React from "react";
import {
  AbsoluteFill, Series, useCurrentFrame, useVideoConfig,
  interpolate, spring, Easing, registerRoot, Composition,
} from "remotion";
import {loadFont} from "@remotion/google-fonts/Inter";

const {fontFamily} = loadFont();
const BG = "radial-gradient(120% 120% at 50% 0%, #2a1c12 0%, #1a110a 55%, #0c0805 100%)";
const CREAM = "#f3e9d8";
const ACCENT = "#d9a05b";
const ease = Easing.bezier(0.16, 1, 0.3, 1);

// Fade in over the first ~0.4s and out over the last ~0.4s of a scene.
function envelope(frame: number, dur: number, fps: number): number {
  const f = 0.4 * fps;
  return (
    interpolate(frame, [0, f], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}) *
    interpolate(frame, [dur - f, dur], [1, 0], {extrapolateLeft: "clamp", extrapolateRight: "clamp"})
  );
}

const Title: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const pop = spring({frame, fps, config: {damping: 12, mass: 0.8}});
  const rise = interpolate(pop, [0, 1], [40, 0]);
  const sub = interpolate(frame, [0.7 * fps, 1.3 * fps], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease});
  const env = envelope(frame, durationInFrames, fps);
  return (
    <AbsoluteFill style={{justifyContent: "center", alignItems: "center", fontFamily, opacity: env}}>
      <div style={{fontSize: 150, fontWeight: 800, letterSpacing: -4, color: CREAM, transform: `translateY(${rise}px) scale(${interpolate(pop, [0, 1], [0.8, 1])})`}}>
        DAYBREAK
      </div>
      <div style={{marginTop: 14, fontSize: 30, fontWeight: 600, color: ACCENT, letterSpacing: 6, opacity: sub, transform: `translateY(${interpolate(sub, [0, 1], [12, 0])}px)`}}>
        COFFEE, ON YOUR TIME
      </div>
    </AbsoluteFill>
  );
};

const Kinetic: React.FC<{text: string; size: number; color: string}> = ({text, size, color}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const env = envelope(frame, durationInFrames, fps);
  const words = text.split(" ");
  return (
    <AbsoluteFill style={{justifyContent: "center", alignItems: "center", fontFamily, opacity: env, padding: 80}}>
      <div style={{display: "flex", flexWrap: "wrap", justifyContent: "center", gap: "0 18px", maxWidth: 1000}}>
        {words.map((w, i) => {
          const t = interpolate(frame, [i * 4, i * 4 + 14], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease});
          return (
            <span key={i} style={{fontSize: size, fontWeight: 700, color, opacity: t, transform: `translateY(${interpolate(t, [0, 1], [26, 0])}px)`}}>
              {w}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

const Cup: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const env = envelope(frame, durationInFrames, fps);
  const pop = spring({frame, fps, config: {damping: 13}});
  const cta = interpolate(frame, [1.2 * fps, 1.8 * fps], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease});
  // Steam wisps rising + wobbling. Math.sin is deterministic (allowed) — Math.random is not.
  const steam = (i: number): React.CSSProperties => {
    const local = frame + i * 10;
    const cycle = (local % 60) / 60;
    const y = -interpolate(cycle, [0, 1], [0, 60]);
    const o = interpolate(cycle, [0, 0.2, 1], [0, 0.5, 0]);
    const x = Math.sin((local / 60) * Math.PI * 2 + i) * 8;
    return {transform: `translate(${x}px, ${y}px)`, opacity: o * env};
  };
  return (
    <AbsoluteFill style={{justifyContent: "center", alignItems: "center", fontFamily, opacity: env}}>
      <div style={{transform: `scale(${interpolate(pop, [0, 1], [0.85, 1])})`, display: "flex", flexDirection: "column", alignItems: "center"}}>
        <div style={{position: "relative", width: 60, height: 80, marginBottom: 18}}>
          {[0, 1, 2].map((i) => (
            <div key={i} style={{position: "absolute", left: 18 + i * 12, bottom: 0, width: 6, height: 30, borderRadius: 3, background: ACCENT, ...steam(i)}} />
          ))}
        </div>
        <div style={{width: 150, height: 120, background: CREAM, borderRadius: "14px 14px 22px 22px", position: "relative"}}>
          <div style={{position: "absolute", right: -34, top: 26, width: 40, height: 56, border: `12px solid ${CREAM}`, borderRadius: "0 28px 28px 0"}} />
          <div style={{position: "absolute", left: 16, right: 16, top: 18, height: 14, borderRadius: 7, background: "#3a2a1c"}} />
        </div>
        <div style={{marginTop: 40, fontSize: 44, fontWeight: 800, color: CREAM, opacity: cta, transform: `translateY(${interpolate(cta, [0, 1], [16, 0])}px)`}}>
          Download Daybreak
        </div>
      </div>
    </AbsoluteFill>
  );
};

const Main: React.FC = () => (
  <AbsoluteFill style={{background: BG}}>
    <Series>
      <Series.Sequence durationInFrames={90}><Title /></Series.Sequence>
      <Series.Sequence durationInFrames={90}><Kinetic text="Your morning, brewed right." size={70} color={CREAM} /></Series.Sequence>
      <Series.Sequence durationInFrames={75}><Kinetic text="Order ahead." size={84} color={ACCENT} /></Series.Sequence>
      <Series.Sequence durationInFrames={75}><Kinetic text="Skip the line." size={84} color={ACCENT} /></Series.Sequence>
      <Series.Sequence durationInFrames={120}><Cup /></Series.Sequence>
    </Series>
  </AbsoluteFill>
);

export const Root: React.FC = () => (
  <Composition id="Video" component={Main} durationInFrames={450} fps={30} width={1280} height={720} />
);

registerRoot(Root);
