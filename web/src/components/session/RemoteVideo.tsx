import { useEffect, useRef } from "react";

export default function RemoteVideo({
  stream,
  label,
  muted = false,
  className = "",
}: {
  stream: MediaStream;
  label?: string;
  muted?: boolean;
  className?: string;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.srcObject = stream;
    }
    return () => {
      if (videoRef.current) {
        videoRef.current.srcObject = null;
      }
    };
  }, [stream]);

  return (
    <div className={`relative rounded-xl overflow-hidden border border-nimbus-mist/10 bg-nimbus-elevated ${className}`}>
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted={muted}
        className="w-full h-full object-cover"
      />
      {label && (
        <div className="absolute bottom-2 left-2 px-2 py-0.5 rounded-md bg-black/50 text-white text-xs backdrop-blur-sm">
          {label}
        </div>
      )}
    </div>
  );
}
