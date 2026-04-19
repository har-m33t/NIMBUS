import type { Landmark3D, RawLandmarks } from "./types";

// MediaPipe hand connections (21-landmark topology).
const HAND_CONNECTIONS: Array<[number, number]> = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16],
  [13, 17], [0, 17], [17, 18], [18, 19], [19, 20],
];

// Upper-body pose connections (indices 0..12 only).
const POSE_UPPER_CONNECTIONS: Array<[number, number]> = (
  [
    [11, 12], [11, 13], [13, 15], [12, 14], [14, 16],
    [11, 23], [12, 24], [11, 0], [12, 0],
  ] as Array<[number, number]>
).filter(([a, b]) => a <= 12 && b <= 12);

export interface DrawOptions {
  mirrored?: boolean; // true if the video is rendered with scaleX(-1)
  strokeStyle?: string;
  pointStyle?: string;
  lineWidth?: number;
  pointRadius?: number;
}

export function drawSkeleton(
  ctx: CanvasRenderingContext2D,
  raw: RawLandmarks,
  opts: DrawOptions = {},
): void {
  const {
    mirrored = true,
    strokeStyle = "#29E3C9",
    pointStyle = "#FFFFFF",
    lineWidth = 2,
    pointRadius = 3,
  } = opts;

  const { width: W, height: H } = ctx.canvas;
  ctx.clearRect(0, 0, W, H);

  ctx.save();
  if (mirrored) {
    ctx.translate(W, 0);
    ctx.scale(-1, 1);
  }
  ctx.lineWidth = lineWidth;
  ctx.strokeStyle = strokeStyle;
  ctx.fillStyle = pointStyle;

  const drawSet = (pts: Landmark3D[] | null, conns: Array<[number, number]>) => {
    if (!pts) return;
    ctx.beginPath();
    for (const [a, b] of conns) {
      const pa = pts[a];
      const pb = pts[b];
      if (!pa || !pb) continue;
      ctx.moveTo(pa.x * W, pa.y * H);
      ctx.lineTo(pb.x * W, pb.y * H);
    }
    ctx.stroke();
    for (const pt of pts) {
      ctx.beginPath();
      ctx.arc(pt.x * W, pt.y * H, pointRadius, 0, Math.PI * 2);
      ctx.fill();
    }
  };

  drawSet(raw.pose?.slice(0, 13) ?? null, POSE_UPPER_CONNECTIONS);
  drawSet(raw.leftHand, HAND_CONNECTIONS);
  drawSet(raw.rightHand, HAND_CONNECTIONS);

  ctx.restore();
}
