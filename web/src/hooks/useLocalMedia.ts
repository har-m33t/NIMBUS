import { useEffect, useRef, useState } from "react";

export type MediaError = "permission-denied" | "no-device" | "unknown" | null;

export function useLocalMedia(enabled: boolean) {
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [error, setError] = useState<MediaError>(null);
  const streamRef = useRef<MediaStream | null>(null);

  useEffect(() => {
    if (!enabled) {
      // Stop existing tracks when disabled
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        setStream(null);
      }
      return;
    }

    let cancelled = false;

    async function acquire() {
      try {
        const ms = await navigator.mediaDevices.getUserMedia({
          video: { width: 1280, height: 720, facingMode: "user" },
          audio: true,
        });
        if (cancelled) {
          ms.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = ms;
        setStream(ms);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException) {
          if (err.name === "NotAllowedError") {
            setError("permission-denied");
          } else if (err.name === "NotFoundError") {
            setError("no-device");
          } else {
            setError("unknown");
          }
        } else {
          setError("unknown");
        }
      }
    }

    acquire();

    return () => {
      cancelled = true;
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        setStream(null);
      }
    };
  }, [enabled]);

  return { stream, error };
}
