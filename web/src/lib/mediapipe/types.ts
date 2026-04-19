export interface Landmark3D {
  x: number;
  y: number;
  z: number;
  visibility?: number;
}

export interface Landmark2D {
  x: number;
  y: number;
}

// Raw output of the two landmarkers for one video frame.
// `pose` is a single array of 33 landmarks (first person only).
// Hands are either the detected 21-landmark array or null when absent.
export interface RawLandmarks {
  pose: Landmark3D[] | null;
  leftHand: Landmark3D[] | null;
  rightHand: Landmark3D[] | null;
}

// Flat output consumed by the (future) TGCN model: exactly 55 (x,y) points.
export type Sliced55 = Landmark2D[] & { length: 55 };

export const SLICED_POSE_COUNT = 13; // indices 0..12 (upper body)
export const SLICED_HAND_COUNT = 21;
export const SLICED_TOTAL = SLICED_POSE_COUNT + SLICED_HAND_COUNT * 2; // 55
