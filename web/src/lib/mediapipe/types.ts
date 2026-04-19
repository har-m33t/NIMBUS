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

// Raw output of the hand landmarker for one video frame.
export interface RawLandmarks {
  hand: Landmark3D[] | null; // 21 landmarks from the first detected hand
}

// Normalized 21-point hand output consumed by the ASL alphabet MLP.
export type Hand21 = Landmark2D[] & { length: 21 };

export const HAND_LANDMARK_COUNT = 21;
export const HAND_FEATURE_COUNT = HAND_LANDMARK_COUNT * 2; // 42 (x, y per landmark)
