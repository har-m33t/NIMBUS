import {
  FilesetResolver,
  HandLandmarker,
  PoseLandmarker,
} from "@mediapipe/tasks-vision";

// Published model URLs. If CDN availability becomes a concern, copy these
// .task files into web/public/models/ and point modelAssetPath at /models/<file>.
const WASM_URL =
  "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.22/wasm";
const POSE_MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task";
const HAND_MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task";

export interface Landmarkers {
  pose: PoseLandmarker;
  hand: HandLandmarker;
  close: () => void;
}

export async function createLandmarkers(): Promise<Landmarkers> {
  const fileset = await FilesetResolver.forVisionTasks(WASM_URL);

  const [pose, hand] = await Promise.all([
    PoseLandmarker.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: POSE_MODEL_URL, delegate: "GPU" },
      runningMode: "VIDEO",
      numPoses: 1,
    }),
    HandLandmarker.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: HAND_MODEL_URL, delegate: "GPU" },
      runningMode: "VIDEO",
      numHands: 2,
    }),
  ]);

  return {
    pose,
    hand,
    close: () => {
      pose.close();
      hand.close();
    },
  };
}
