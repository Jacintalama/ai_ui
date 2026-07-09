import React from "react";

// Shared cursor assets for every render path. Both are drawn as inline SVG so
// they stay pixel-crisp at any Ken-Burns zoom and need no network fetch.

// Faithful macOS-style arrow pointer. The polygon's (0,0) is the hotspot TIP:
// position the svg's top-left corner on the click point (transformOrigin "0 0").
export const ARROW_POINTS =
  "0,0 0,16.97 4.59,13.23 7.32,19.36 10.36,18.04 7.63,11.91 13.61,11.91";

export const ArrowCursor: React.FC<{style?: React.CSSProperties}> = ({style}) => (
  <svg width={22} height={30} viewBox="-1 -1 15.6 21.4" style={style}>
    <polygon
      points={ARROW_POINTS}
      fill="#fff"
      stroke="#1a1a1a"
      strokeWidth="1.1"
      strokeLinejoin="round"
    />
  </svg>
);

// Pointing-hand cursor (what a real cursor becomes over a link). Hotspot is
// the extended fingertip; HAND_HOTSPOT offsets the svg so placing its
// top-left on the click point puts the FINGERTIP on the click point.
export const HAND_PATH =
  "M9 1.5c-.83 0-1.5.67-1.5 1.5v8.9l-1.83-1.66c-.68-.62-1.73-.6-2.38.06" +
  "-.66.66-.68 1.72-.04 2.4l4.92 5.24c.85.9 2.03 1.41 3.27 1.41h3.66" +
  "c2.49 0 4.5-2.01 4.5-4.5v-4.1c0-1.1-.9-2-2-2h-.55c-.14-.8-.84-1.4-1.68-1.4" +
  "h-.62c-.2-.72-.86-1.25-1.64-1.25h-.61V3c0-.83-.67-1.5-1.5-1.5z";

export const HAND_HOTSPOT = {x: -10, y: -2};

export const HandCursor: React.FC<{style?: React.CSSProperties}> = ({style}) => (
  <svg
    width={26}
    height={26}
    viewBox="0 0 24 24"
    style={{marginLeft: HAND_HOTSPOT.x, marginTop: HAND_HOTSPOT.y, ...style}}
  >
    <path
      d={HAND_PATH}
      fill="#fff"
      stroke="#1a1a1a"
      strokeWidth="1.2"
      strokeLinejoin="round"
    />
  </svg>
);
