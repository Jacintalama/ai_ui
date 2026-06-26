import React from "react";
import {AbsoluteFill, Img, useCurrentFrame, useVideoConfig} from "remotion";
import {loadFont} from "@remotion/google-fonts/Inter";
import type {Scene} from "./Video";
import {cursorTrajectory, scaleCursorTrajectory} from "./cursor";

// Load only the weights/subset actually used (600/700/800, latin) to cut the
// font download. loadFont() at module top level auto-blocks the render until ready.
const {fontFamily: interFamily} = loadFont("normal", {
  weights: ["600", "700", "800"],
  subsets: ["latin"],
});
const fontFamily = `${interFamily}, Inter, Segoe UI, system-ui, sans-serif`;

// Easing helpers (ported exactly from the reference)
const clamp = (x: number) => Math.max(0, Math.min(1, x));
const lerp = (a: number, b: number, p: number) => a + (b - a) * p;
const ease = (p: number) => p * p * (3 - 2 * p); // smoothstep
const ease2 = (p: number) => p * p * p * (p * (6 * p - 15) + 10); // smootherstep

const BG_GRADIENT =
  "radial-gradient(125% 120% at 50% -10%, #16161f 0%, #0b0b10 55%, #060608 100%)";

export const SceneParity: React.FC<{
  scene: Scene;
  host: string;
  title: string;
  animationPreset?: string;
  sceneIndex?: number;
}> = ({scene, host, title, animationPreset = "cursor_click", sceneIndex = 0}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const p = clamp(frame / Math.max(1, scene.durInFrames));

  const hasShot = Boolean(scene.screenshot);
  const motion = scene.motion || "fade";
  const preset = animationPreset || "cursor_click";

  // Fade-through envelope: in over first 18%, out over last 18%.
  const env =
    ease2(clamp(p / 0.18)) * (1 - ease2(clamp((p - 0.82) / 0.18)));

  // --- Frame (browser chrome) transform ---
  // Ken Burns (always on for screenshot scenes)
  const kb = lerp(1.0, preset === "zoom_pan" ? 1.13 : 1.06, ease2(p));
  const kx = lerp(0, -1.2, ease2(p)); // percent
  const ky = lerp(0, -1.0, ease2(p)); // percent

  // Motion on top of Ken Burns
  let mz = 1.0;
  let dx = 0;
  let dy = 0;
  if (motion === "zoom-in") {
    mz = lerp(1.0, 1.1, ease2(p));
  } else if (motion === "zoom-out") {
    mz = lerp(1.1, 1.0, ease2(p));
  } else if (motion === "pan-up") {
    dy = lerp(20, -20, ease2(p));
  } else if (motion === "pan-left") {
    dx = lerp(30, -30, ease2(p));
  }
  if (preset === "smooth_scroll") {
    dy += lerp(34, -46, ease2(p));
  }

  const frameOpacity = hasShot ? env : 0;
  const frameTransform = `translate(calc(-50% + ${dx}px), ${dy}px) translate(${kx}%, ${ky}%) scale(${kb * mz})`;
  // Per-scene cursor path + click timing so the cursor varies scene-to-scene
  // instead of replaying one identical sweep every scene. Scaled to the actual
  // composition size so positions stay correct at any resolution.
  const traj = scaleCursorTrajectory(cursorTrajectory(sceneIndex), width, height);
  const cursorX = lerp(traj.x0, traj.x1, ease2(clamp((p - 0.12) / 0.52)));
  const cursorY = lerp(traj.y0, traj.y1, ease2(clamp((p - 0.12) / 0.52)));
  const clickPulse =
    ease2(clamp((p - traj.clickStart) / 0.1)) *
    (1 - ease2(clamp((p - traj.clickFall) / 0.18)));
  const showCursor = hasShot && preset === "cursor_click";

  // --- Eyebrow ---
  const eyebrowOpacity = hasShot ? 0 : env;
  const eyebrowText = title || "OVERVIEW";

  // --- Headline kinetic per-word reveal ---
  const headlineText = scene.headline || "";
  const words = headlineText.split(" ");
  const n = words.length;

  // Headline container extra: rise motion lifts it.
  const hy = motion === "rise" ? lerp(24, 0, ease2(p)) : 0;

  // --- Subtext ---
  const subtextOpacity = scene.subtext ? env : 0;

  // CENTER variant for non-screenshot scenes.
  const eyebrowStyle: React.CSSProperties = hasShot
    ? {bottom: "21%"}
    : {top: "37%", bottom: "auto"};
  const headlineStyle: React.CSSProperties = hasShot
    ? {bottom: "13%"}
    : {top: "44%", bottom: "auto"};
  const subtextStyle: React.CSSProperties = hasShot
    ? {bottom: "8%"}
    : {top: "57%", bottom: "auto"};

  return (
    <AbsoluteFill
      style={{
        background: BG_GRADIENT,
        color: "#fff",
        fontFamily,
        overflow: "hidden",
      }}
    >
      {/* .bgglow */}
      <div
        style={{
          position: "absolute",
          top: "-18%",
          left: "50%",
          width: "88%",
          height: "72%",
          transform: "translateX(-50%)",
          borderRadius: "50%",
          background:
            "radial-gradient(closest-side, rgba(96,108,180,.34), rgba(96,108,180,0))",
          filter: "blur(46px)",
          pointerEvents: "none",
        }}
      />

      {/* .frame (browser chrome) */}
      <div
        style={{
          position: "absolute",
          top: "5.5%",
          left: "50%",
          width: "64%",
          maxHeight: "58%",
          transformOrigin: "50% 50%",
          borderRadius: 14,
          overflow: "hidden",
          background: "#0e0e14",
          border: "1px solid rgba(255,255,255,.07)",
          boxShadow:
            "0 44px 130px rgba(0,0,0,.66),0 10px 28px rgba(0,0,0,.45)",
          opacity: frameOpacity,
          transform: frameTransform,
        }}
      >
        {/* .bar */}
        <div
          style={{
            height: 36,
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "0 14px",
            background: "linear-gradient(#24242f,#191921)",
            borderBottom: "1px solid rgba(255,255,255,.05)",
          }}
        >
          <div style={dotStyle("#ff5f57")} />
          <div style={dotStyle("#febc2e")} />
          <div style={dotStyle("#28c840")} />
          {/* .addr */}
          <div
            style={{
              marginLeft: 12,
              flex: 1,
              height: 20,
              borderRadius: 10,
              background: "rgba(255,255,255,.06)",
              fontSize: 12,
              lineHeight: "20px",
              padding: "0 12px",
              color: "#aab1c8",
              letterSpacing: ".2px",
              overflow: "hidden",
              whiteSpace: "nowrap",
              textOverflow: "ellipsis",
            }}
          >
            {host}
          </div>
        </div>
        {/* #img (screenshot) */}
        {scene.screenshot ? (
          <Img
            src={scene.screenshot}
            style={{display: "block", width: "100%"}}
            // Keep rendering if a screenshot fails to decode rather than
            // stalling the whole render until the frame times out.
            onError={() => {}}
          />
        ) : null}
      </div>

      {/* .eyebrow */}
      <div
        style={{
          position: "absolute",
          left: "6%",
          right: "6%",
          textAlign: "center",
          fontSize: 18,
          fontWeight: 700,
          letterSpacing: 3,
          textTransform: "uppercase",
          color: "#9aa6ff",
          opacity: eyebrowOpacity,
          ...eyebrowStyle,
        }}
      >
        {eyebrowText}
      </div>

      {/* #headline */}
      <div
        style={{
          position: "absolute",
          left: "6%",
          right: "6%",
          textAlign: "center",
          fontSize: 56,
          fontWeight: 800,
          letterSpacing: -1.5,
          transform: `translateY(${hy}px)`,
          ...headlineStyle,
        }}
      >
        {words.map((word, i) => {
          const d = n > 1 ? (i / n) * 0.45 : 0;
          const wo = ease2(clamp((p - d) / 0.4));
          return (
            <span
              key={i}
              style={{
                display: "inline-block",
                whiteSpace: "pre",
                opacity: env * wo,
                transform: `translateY(${lerp(20, 0, wo)}px)`,
              }}
            >
              {i < n - 1 ? word + " " : word}
            </span>
          );
        })}
      </div>

      {/* #subtext */}
      <div
        style={{
          position: "absolute",
          left: "6%",
          right: "6%",
          textAlign: "center",
          fontSize: 28,
          fontWeight: 600,
          opacity: subtextOpacity,
          ...subtextStyle,
        }}
      >
        {scene.subtext}
      </div>

      {/* .vignette (on top of everything) */}
      {hasShot && preset === "spotlight" ? (
        <div
          style={{
            position: "absolute",
            inset: 0,
            opacity: env,
            background:
              "radial-gradient(circle at 65% 42%, rgba(255,255,255,.18) 0 11%, rgba(0,0,0,0) 19%, rgba(0,0,0,.48) 64%)",
            pointerEvents: "none",
          }}
        />
      ) : null}

      {showCursor ? (
        <>
          <div
            style={{
              position: "absolute",
              left: cursorX,
              top: cursorY,
              width: 0,
              height: 0,
              borderTop: "24px solid #f7f5ef",
              borderRight: "15px solid transparent",
              filter: "drop-shadow(0 2px 1px rgba(0,0,0,.55))",
              transform: "rotate(-12deg)",
              opacity: env,
              pointerEvents: "none",
            }}
          />
          <div
            style={{
              position: "absolute",
              left: cursorX,
              top: cursorY,
              width: 82,
              height: 82,
              marginLeft: -41,
              marginTop: -41,
              border: "4px solid rgba(154,166,255,.9)",
              borderRadius: "50%",
              opacity: clickPulse,
              transform: `scale(${lerp(0.35, 1.2, clickPulse)})`,
              pointerEvents: "none",
            }}
          />
        </>
      ) : null}

      <div
        style={{
          position: "absolute",
          inset: 0,
          mixBlendMode: "multiply",
          background:
            "radial-gradient(125% 125% at 50% 48%, rgba(0,0,0,0) 56%, rgba(0,0,0,.6) 100%)",
          pointerEvents: "none",
        }}
      />
    </AbsoluteFill>
  );
};

function dotStyle(color: string): React.CSSProperties {
  return {
    width: 11,
    height: 11,
    borderRadius: "50%",
    background: color,
  };
}
