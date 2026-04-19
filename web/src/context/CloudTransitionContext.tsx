import { createContext, useContext, useState, useCallback, type ReactNode } from "react";

type CloudPhase = "normal" | "envelope" | "parting";

interface CloudTransitionState {
  phase: CloudPhase;
  /** Trigger the envelope (clouds close inward). Returns a promise that resolves when the animation duration elapses. */
  triggerEnvelope: () => Promise<void>;
  /** Trigger the parting (clouds open outward). */
  triggerPart: () => void;
  /** Reset to normal resting position. */
  reset: () => void;
}

const CloudTransitionContext = createContext<CloudTransitionState | null>(null);

export function useCloudTransition(): CloudTransitionState {
  const ctx = useContext(CloudTransitionContext);
  if (!ctx) throw new Error("useCloudTransition must be used within CloudTransitionProvider");
  return ctx;
}

const ENVELOPE_DURATION_MS = 1200;

export function CloudTransitionProvider({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<CloudPhase>("normal");

  const triggerEnvelope = useCallback((): Promise<void> => {
    setPhase("envelope");
    return new Promise((resolve) => setTimeout(resolve, ENVELOPE_DURATION_MS));
  }, []);

  const triggerPart = useCallback(() => setPhase("parting"), []);
  const reset = useCallback(() => setPhase("normal"), []);

  return (
    <CloudTransitionContext.Provider value={{ phase, triggerEnvelope, triggerPart, reset }}>
      {children}
    </CloudTransitionContext.Provider>
  );
}
