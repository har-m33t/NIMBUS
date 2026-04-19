import type { Landmark2D, Landmark3D, RawLandmarks, Hand21 } from "./types";
import { HAND_LANDMARK_COUNT } from "./types";

const ZERO: Landmark2D = { x: 0, y: 0 };

// Minimum bounding-box diagonal to avoid divide-by-near-zero.
const MIN_BBOX_DIAG = 1e-6;

function take2D(src: Landmark3D[] | null, count: number): Landmark2D[] {
  const out: Landmark2D[] = [];
  for (let i = 0; i < count; i++) {
    const lm = src?.[i];
    out.push(lm ? { x: lm.x, y: lm.y } : { ...ZERO });
  }
  return out;
}

/**
 * Wrist-centered, bounding-box-diagonal-scaled normalization.
 *
 * Matches the notebook's `normalize_hand()` exactly:
 *   1. Center on wrist (landmark 0)
 *   2. Scale by sqrt(x_range² + y_range²) of the centered points
 *
 * If the hand is all zeros or the bounding box is degenerate, returns raw.
 */
function normalizeHand(pts: Landmark2D[]): Landmark2D[] {
  const wrist = pts[0];
  if (wrist.x === 0 && wrist.y === 0) return pts;

  const centered = pts.map((p) => ({
    x: p.x - wrist.x,
    y: p.y - wrist.y,
  }));

  let minX = Infinity, maxX = -Infinity;
  let minY = Infinity, maxY = -Infinity;
  for (const p of centered) {
    if (p.x < minX) minX = p.x;
    if (p.x > maxX) maxX = p.x;
    if (p.y < minY) minY = p.y;
    if (p.y > maxY) maxY = p.y;
  }

  const xRange = maxX - minX;
  const yRange = maxY - minY;
  const diag = Math.sqrt(xRange * xRange + yRange * yRange);
  if (diag < MIN_BBOX_DIAG) return centered;

  return centered.map((p) => ({
    x: p.x / diag,
    y: p.y / diag,
  }));
}

/**
 * Extract and normalize 21 hand landmarks from raw MediaPipe output.
 * Returns wrist-centered, bbox-scaled (x, y) points ready for the MLP.
 */
export function normalizeHandLandmarks(raw: RawLandmarks): Hand21 {
  const pts = take2D(raw.hand, HAND_LANDMARK_COUNT);
  if (pts.length !== HAND_LANDMARK_COUNT) {
    throw new Error(`normalizeHandLandmarks produced ${pts.length} points, expected ${HAND_LANDMARK_COUNT}`);
  }
  return normalizeHand(pts) as Hand21;
}
