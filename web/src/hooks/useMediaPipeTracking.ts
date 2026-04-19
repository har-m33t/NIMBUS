import { useEffect, useRef, useState } from "react";
import {
  createLandmarkers,
  type Landmarkers,
} from "../lib/mediapipe/landmarkers";
import { normalizeHandLandmarks } from "../lib/mediapipe/slicer";
import type {
  Landmark3D,
  RawLandmarks,
  Hand21,
} from "../lib/mediapipe/types";

export interface UseMediaPipeTrackingOptions {
  video: HTMLVideoElement | null;
  enabled: boolean;
  targetFps?: number;
}

export interface MediaPipeTrackingState {
  isTracking: boolean;
  hand21: Hand21 | null;
  rawLandmarks: RawLandmarks | null;
  lastUpdateMs: number | null;
  error: string | null;
}

type NormalizedLandmark = { x: number; y: number; z: number; visibility?: number };

function toLandmark3D(src: NormalizedLandmark[] | undefined): Landmark3D[] | null {
  if (!src || src.length === 0) return null;
  return src.map((p) => ({
    x: p.x,
    y: p.y,
    z: p.z,
    visibility: p.visibility,
  }));
}

export function useMediaPipeTracking({
  video,
  enabled,
  targetFps = 10,
}: UseMediaPipeTrackingOptions): MediaPipeTrackingState {
  const [state, setState] = useState<MediaPipeTrackingState>({
    isTracking: false,
    hand21: null,
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
        const msg = err instanceof Error ? err.message : (typeof err === 'string' ? err : 'Failed to load MediaPipe models');
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
      const handResult = lm.hand.detectForVideo(video, ts);

      // Take the first detected hand
      const hand = toLandmark3D(handResult.landmarks?.[0]);

      const raw: RawLandmarks = { hand };
      const normalized = normalizeHandLandmarks(raw);

      setState({
        isTracking: hand !== null,
        hand21: normalized,
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
