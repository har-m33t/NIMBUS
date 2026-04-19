import { useRef, useEffect } from "react";

export default function VideoFeed({
  showOverlay = true,
  isTracking = false,
}: {
  showOverlay?: boolean;
  isTracking?: boolean;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    let stream: MediaStream | null = null;

    async function start() {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { width: 1280, height: 720, facingMode: "user" },
          audio: false,
        });
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
        }
      } catch {
        // Camera not available — will show placeholder
      }
    }

    start();
    return () => {
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  return (
    <div className="relative w-full rounded-2xl overflow-hidden border border-nimbus-mist/10 bg-nimbus-elevated">
      {/* Aspect ratio container */}
      <div className="relative w-full" style={{ paddingBottom: "56.25%" }}>
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          className="absolute inset-0 w-full h-full object-cover"
          style={{ transform: "scaleX(-1)" }}
        />

        {/* MediaPipe overlay canvas placeholder */}
        {showOverlay && (
          <canvas
            className="absolute inset-0 w-full h-full pointer-events-none"
            aria-hidden="true"
          />
        )}

        {/* Tracking badge */}
        <div className="absolute top-3 left-3">
          <div
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium backdrop-blur-sm ${
              isTracking
                ? "bg-nimbus-teal/20 text-nimbus-teal border border-nimbus-teal/30"
                : "bg-nimbus-surface/60 text-nimbus-mist border border-nimbus-mist/20"
            }`}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${isTracking ? "bg-nimbus-teal signal-pulse" : "bg-nimbus-mist"}`} />
            {isTracking ? "Tracking" : "Waiting…"}
          </div>
        </div>

        {/* Overlay toggle hint */}
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

        {/* Vignette effect */}
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
