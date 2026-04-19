import type { Landmark2D, Landmark3D, RawLandmarks, Sliced55 } from "./types";
import { SLICED_HAND_COUNT, SLICED_POSE_COUNT, SLICED_TOTAL } from "./types";

const ZERO: Landmark2D = { x: 0, y: 0 };

function take2D(src: Landmark3D[] | null, count: number, offset = 0): Landmark2D[] {
  const out: Landmark2D[] = [];
  for (let i = 0; i < count; i++) {
    const lm = src?.[offset + i];
    out.push(lm ? { x: lm.x, y: lm.y } : { ...ZERO });
  }
  return out;
}

export function sliceTo55Points(raw: RawLandmarks): Sliced55 {
  const out: Landmark2D[] = [
    ...take2D(raw.pose, SLICED_POSE_COUNT),
    ...take2D(raw.leftHand, SLICED_HAND_COUNT),
    ...take2D(raw.rightHand, SLICED_HAND_COUNT),
  ];
  if (out.length !== SLICED_TOTAL) {
    throw new Error(`sliceTo55Points produced ${out.length} points, expected ${SLICED_TOTAL}`);
  }
  return out as Sliced55;
}
