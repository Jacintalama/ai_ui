import {AbsoluteFill} from "remotion";
export type Scene = { kind: string; screenshot?: string; headline?: string;
  subtext?: string; motion?: string; durInFrames: number };
export type VideoProps = { theme: string; host: string; title: string;
  fps: number; width: number; height: number; scenes: Scene[] };
export const Video: React.FC<VideoProps> = () => (
  <AbsoluteFill style={{backgroundColor: "#0b0b10"}} />
);
