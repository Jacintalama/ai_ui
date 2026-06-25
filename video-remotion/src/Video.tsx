import React from "react";
import {AbsoluteFill, Series} from "remotion";
import {SceneParity} from "./theme-parity";
export type Scene = { kind: string; screenshot?: string; headline?: string;
  subtext?: string; motion?: string; durInFrames: number };
export type VideoProps = { theme: string; host: string; title: string;
  fps: number; width: number; height: number; scenes: Scene[] };
const BG_GRADIENT =
  "radial-gradient(125% 120% at 50% -10%, #16161f 0%, #0b0b10 55%, #060608 100%)";
export const Video: React.FC<VideoProps> = ({host, title, scenes}) => (
  <AbsoluteFill style={{background: BG_GRADIENT}}>
    <Series>
      {(scenes || []).map((s, i) => (
        <Series.Sequence key={i} durationInFrames={Math.max(1, s.durInFrames)}>
          <SceneParity scene={s} host={host} title={title} />
        </Series.Sequence>
      ))}
    </Series>
  </AbsoluteFill>
);
