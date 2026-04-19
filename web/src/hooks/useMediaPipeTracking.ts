import { useEffect, useRef, useState } from "react";
import {
  createLandmarkers,
  type Landmarkers,
} from "../lib/mediapipe/landmarkers";
import { sliceTo55Points } from "../lib/mediapipe/slicer";
import type {
  Landmark3D,
  RawLandmarks,
  Sliced55,
} from "../lib/mediapipe/types";

export interface UseMediaPipeTrackingOptions {
  video: HTMLVideoElement | null;
  enabled: boolean;
  targetFps?: number; // defaults to 10 to match PROTOCOLS §3.1
}

export interface MediaPipeTrackingState {
  isTracking: boolean;
  keypoints55: Sliced55 | null;
  rawLandmarks: RawLandmarks | null;
  lastUpdateMs: number | null;
  error: string | null;
}

type NormalizedLandmark = { x: number; y: number; z: number; visibility?: number };
type HandedCategory = { categoryName?: string; displayName?: string };

function toLandmark3D(src: NormalizedLandmark[] | undefined): Landmark3D[] | null {
  if (!src || src.length === 0) return null;
  return src.map((p) => ({
    x: p.x,
    y: p.y,
    z: p.z,
    visibility: p.visibility,
  }));
}

// Hand landmarker returns up to `numHands` hands in detection order. Use the
// handedness label to route each result to left or right.
function partitionHands(
  landmarks: NormalizedLandmark[][] | undefined,
  handedness: HandedCategory[][] | undefined,
): { leftHand: Landmark3D[] | null; rightHand: Landmark3D[] | null } {
  let leftHand: Landmark3D[] | null = null;
  let rightHand: Landmark3D[] | null = null;
  if (!landmarks || !handedness) return { leftHand, rightHand };

  for (let i = 0; i < landmarks.length; i++) {
    const label = handedness[i]?.[0]?.categoryName ?? handedness[i]?.[0]?.displayName;
    const pts = toLandmark3D(landmarks[i]);
    if (!pts) continue;
    if (label === "Left") leftHand = pts;
    else if (label === "Right") rightHand = pts;
  }
  return { leftHand, rightHand };
}

export function useMediaPipeTracking({
  video,
  enabled,
  targetFps = 10,
}: UseMediaPipeTrackingOptions): MediaPipeTrackingState {
  const [state, setState] = useState<MediaPipeTrackingState>({
    isTracking: false,
    keypoints55: null,
    rawLandmarks: null,
    lastUpdateMs: null,
    error: null,
  });

  const landmarkersRef = useRef<Landmarkers | null>(null);
  const rafRef = useRef<number | null>(null);
  const lastEmitRef = useRef<number>(0);
  const disposedRef = useRef(false);

  useEffect(() => {
    if (!enabled || !video) {
      setState((s) => ({ ...s, isTracking: false }));
      return;
    }

    disposedRef.current = false;
    const frameIntervalMs = 1000 / targetFps;

    async function boot() {
      try {
        const lm = await createLandmarkers();
        if (disposedRef.current) {
          lm.close();
          return;
        }
        landmarkersRef.current = lm;
        loop();
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setState((s) => ({ ...s, error: msg, isTracking: false }));
      }
    }

    function loop() {
      if (disposedRef.current) return;
      rafRef.current = requestAnimationFrame(loop);

      const lm = landmarkersRef.current;
      if (!lm || !video || video.readyState < 2) return;

      const now = performance.now();
      if (now - lastEmitRef.current < frameIntervalMs) return;
      lastEmitRef.current = now;

      const ts = Math.floor(now);
      const poseResult = lm.pose.detectForVideo(video, ts);
      const handResult = lm.hand.detectForVideo(video, ts);

      const pose = toLandmark3D(poseResult.landmarks?.[0]);
      const { leftHand, rightHand } = partitionHands(
        handResult.landmarks,
        handResult.handednesses,
      );

      const raw: RawLandmarks = { pose, leftHand, rightHand };
      const sliced = sliceTo55Points(raw);

      setState({
        isTracking: pose !== null || leftHand !== null || rightHand !== null,
        keypoints55: sliced,
        rawLandmarks: raw,
        lastUpdateMs: ts,
        error: null,
      });
    }

    boot();

    return () => {
      disposedRef.current = true;
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      landmarkersRef.current?.close();
      landmarkersRef.current = null;
      lastEmitRef.current = 0;
    };
  }, [enabled, video, targetFps]);

  return state;
}
