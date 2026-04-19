import { useEffect, useRef } from "react";
import { useMediaPipeTracking } from "../../hooks/useMediaPipeTracking.ts";
import { drawSkeleton } from "../../lib/mediapipe/drawOverlay.ts";

export default function VideoFeed({
  stream = null,
  showOverlay = true,
  enabled = false,
  isTracking: isTrackingProp = false,
}: {
  stream?: MediaStream | null;
  showOverlay?: boolean;
  enabled?: boolean;
  isTracking?: boolean;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.srcObject = stream;
    }
  }, [stream]);

  const { isTracking, rawLandmarks, error } = useMediaPipeTracking({
    video: videoRef.current,
    enabled: enabled && !!stream,
  });

  // Paint the skeleton every time the hook emits new landmarks.
  useEffect(() => {
    const canvas = canvasRef.current;
    const video = videoRef.current;
    if (!canvas || !video || !rawLandmarks) return;

    // Keep the canvas backing store matched to the video's intrinsic size
    // so that landmark coords (normalized to the video frame) land correctly.
    const targetW = video.videoWidth || canvas.clientWidth;
    const targetH = video.videoHeight || canvas.clientHeight;
    if (canvas.width !== targetW) canvas.width = targetW;
    if (canvas.height !== targetH) canvas.height = targetH;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    drawSkeleton(ctx, rawLandmarks, { mirrored: true });
  }, [rawLandmarks]);

  // Clear the overlay when tracking turns off.
  useEffect(() => {
    if (enabled) return;
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (canvas && ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
  }, [enabled]);

  const badgeActive = enabled ? isTracking : isTrackingProp;

  return (
    <div className="relative w-full rounded-2xl overflow-hidden border border-nimbus-mist/10 bg-nimbus-elevated">
      <div className="relative w-full" style={{ paddingBottom: "56.25%" }}>
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          className="absolute inset-0 w-full h-full object-cover"
          style={{ transform: "scaleX(-1)" }}
        />

        {showOverlay && (
          <canvas
            ref={canvasRef}
            className="absolute inset-0 w-full h-full pointer-events-none"
            aria-hidden="true"
          />
        )}

        <div className="absolute top-3 left-3">
          <div
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium backdrop-blur-sm ${
              badgeActive
                ? "bg-nimbus-teal/20 text-nimbus-teal border border-nimbus-teal/30"
                : "bg-nimbus-surface/60 text-nimbus-mist border border-nimbus-mist/20"
            }`}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${badgeActive ? "bg-nimbus-teal signal-pulse" : "bg-nimbus-mist"}`} />
            {badgeActive ? "Tracking" : enabled ? "Initializing…" : "Waiting…"}
          </div>
        </div>

        {showOverlay && (
          <div className="absolute top-3 right-3">
            <button
              className="p-1.5 rounded-lg bg-nimbus-surface/60 text-nimbus-mist hover:text-nimbus-text backdrop-blur-sm border border-nimbus-mist/20 transition-colors"
              title="Toggle skeleton overlay"
              aria-label="Toggle MediaPipe skeleton overlay"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                <circle cx="12" cy="12" r="3" />
              </svg>
            </button>
          </div>
        )}

        {error && (
          <div className="absolute bottom-3 left-3 text-xs text-nimbus-coral bg-nimbus-surface/70 px-2 py-1 rounded-md backdrop-blur-sm">
            Tracking error: {error}
          </div>
        )}

        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background: "radial-gradient(ellipse at center, transparent 60%, rgba(15, 22, 41, 0.4) 100%)",
          }}
          aria-hidden="true"
        />
      </div>
    </div>
  );
}
