import { useCallback, useEffect, useRef, useState } from "react";
import type { Hand21 } from "../lib/mediapipe/types";
import { HAND_FEATURE_COUNT } from "../lib/mediapipe/types";

const DEBOUNCE_MS = 1000;

export interface Prediction {
  label: string;
  confidence: number;
}

interface WorkerResponse {
  token: string;
  top3: Prediction[];
}

export interface UseGlossInferenceOptions {
  hand21: Hand21 | null;
  enabled: boolean;
  onGloss?: (token: string) => void;
}

export interface GlossInferenceState {
  currentToken: string | null;
  top3: Prediction[];
  inferring: boolean;
  error: string | null;
}

/**
 * Sends each normalized 21-point hand frame to the ONNX worker for single-
 * frame ASL alphabet classification. No rolling buffer — the MLP classifies
 * each frame independently.
 *
 * Tensor layout: flat Float32Array of 42 values [x0, y0, x1, y1, ..., x20, y20].
 * Coordinates arrive wrist-centered and bbox-diagonal-scaled from the slicer.
 */
export function useGlossInference({
  hand21,
  enabled,
  onGloss,
}: UseGlossInferenceOptions): GlossInferenceState {
  const [state, setState] = useState<GlossInferenceState>({
    currentToken: null,
    top3: [],
    inferring: false,
    error: null,
  });

  const workerRef = useRef<Worker | null>(null);
  const lastTokenRef = useRef<string | null>(null);
  const lastTokenTimeRef = useRef<number>(0);
  const inferringRef = useRef(false);
  const handPresentRef = useRef(false);
  const onGlossRef = useRef(onGloss);
  onGlossRef.current = onGloss;

  // Boot / teardown the Web Worker
  useEffect(() => {
    if (!enabled) {
      if (workerRef.current) {
        workerRef.current.terminate();
        workerRef.current = null;
      }
      lastTokenRef.current = null;
      lastTokenTimeRef.current = 0;
      inferringRef.current = false;
      setState({ currentToken: null, top3: [], inferring: false, error: null });
      return;
    }

    const worker = new Worker(
      new URL("../workers/wlaslWorker.js", import.meta.url),
      { type: "module" },
    );

    worker.onmessage = (evt: MessageEvent<WorkerResponse>) => {
      inferringRef.current = false;
      const { token, top3 } = evt.data;

      setState((s) => ({ ...s, top3, inferring: false }));

      if (!token) return;

      const now = performance.now();
      if (token === lastTokenRef.current && now - lastTokenTimeRef.current < DEBOUNCE_MS) {
        return;
      }

      lastTokenRef.current = token;
      lastTokenTimeRef.current = now;
      setState((s) => ({ ...s, currentToken: token }));
      onGlossRef.current?.(token);
    };

    worker.onerror = (err) => {
      inferringRef.current = false;
      setState((s) => ({
        ...s,
        inferring: false,
        error: err.message || "ONNX worker error",
      }));
    };

    workerRef.current = worker;

    return () => {
      worker.terminate();
      workerRef.current = null;
    };
  }, [enabled]);

  // Send each frame to the worker
  const pushFrame = useCallback((frame: Hand21) => {
    if (inferringRef.current || !workerRef.current) return;

    // Skip if hand is all zeros (no detection)
    let allZero = true;
    for (const pt of frame) {
      if (pt.x !== 0 || pt.y !== 0) { allZero = false; break; }
    }
    if (allZero) return;

    inferringRef.current = true;
    setState((s) => ({ ...s, inferring: true }));

    const tensor = new Float32Array(HAND_FEATURE_COUNT);
    for (let i = 0; i < frame.length; i++) {
      tensor[i * 2] = frame[i].x;
      tensor[i * 2 + 1] = frame[i].y;
    }

    workerRef.current.postMessage(tensor, [tensor.buffer]);
  }, []);

  useEffect(() => {
    if (!enabled || !hand21) {
      if (handPresentRef.current) {
        handPresentRef.current = false;
        onGlossRef.current?.("[EOS]");
      }
      return;
    }
    handPresentRef.current = true;
    pushFrame(hand21);
  }, [enabled, hand21, pushFrame]);

  return state;
}
