import {Composition} from "remotion";
import {Video} from "./Video";
const calc = ({props}: {props: any}) => {
  const fps = props.fps || 24;
  const total = (props.scenes || []).reduce(
    (a: number, s: any) => a + Math.max(1, s.durInFrames || 0), 0);
  return { durationInFrames: Math.max(1, total), fps,
           width: props.width || 1280, height: props.height || 720 };
};
export const Root: React.FC = () => (
  <Composition id="Video" component={Video} durationInFrames={1} fps={24}
    width={1280} height={720} calculateMetadata={calc}
    defaultProps={{theme: "parity", host: "", title: "", fps: 24,
      width: 1280, height: 720, scenes: []}} />
);
