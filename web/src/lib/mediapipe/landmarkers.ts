import {
  FilesetResolver,
  HandLandmarker,
} from "@mediapipe/tasks-vision";

// Published model URLs. If CDN availability becomes a concern, copy these
// .task files into web/public/models/ and point modelAssetPath at /models/<file>.
const WASM_URL =
  "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.34/wasm";
const HAND_MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task";

export interface Landmarkers {
  hand: HandLandmarker;
  close: () => void;
}

export async function createLandmarkers(): Promise<Landmarkers> {
  const fileset = await FilesetResolver.forVisionTasks(WASM_URL);

  const hand = await HandLandmarker.createFromOptions(fileset, {
    baseOptions: { modelAssetPath: HAND_MODEL_URL, delegate: "CPU" },
    runningMode: "VIDEO",
    numHands: 1,
  });

  return {
    hand,
    close: () => {
      hand.close();
    },
  };
}
