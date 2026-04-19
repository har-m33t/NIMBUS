import { useEffect, useRef } from "react";
import { useTelemetry } from "../context/TelemetryContext.tsx";
import { useDevMode } from "../hooks/useDevMode.ts";

const SYSTEM_COLOR: Record<string, string> = {
  EDGE_ML:       "text-cyan-400",
  WEBSOCKET_TX:  "text-yellow-400",
  REKOGNITION:   "text-pink-400",
  BEDROCK:       "text-purple-400",
  POLLY:         "text-orange-400",
};

export default function GlassBox() {
  const isDevMode = useDevMode();
  const { logs } = useTelemetry();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  if (!isDevMode) return null;

  return (
    <div className="fixed bottom-4 right-4 w-96 max-h-[50vh] z-50 overflow-y-auto bg-black/80 backdrop-blur-md border border-green-500/30 p-4 rounded-xl shadow-2xl font-mono text-xs">
      {/* Header */}
      <div className="flex items-center justify-between mb-3 sticky top-0 bg-black/60 -mx-4 px-4 py-1 border-b border-green-500/20">
        <span className="text-green-400 font-semibold tracking-widest uppercase text-[10px]">
          ◉ NIMBUS Glass Box
        </span>
        <span className="text-green-500/50 text-[9px]">{logs.length} events</span>
      </div>

      {logs.length === 0 && (
        <p className="text-green-500/40 italic">Waiting for events…</p>
      )}

      {logs.map((log, i) => {
        const color = SYSTEM_COLOR[log.system] ?? "text-green-300";
        return (
          <div key={i} className="mb-1 leading-relaxed">
            <span className="text-green-500/50">{log.timestamp} </span>
            <span className={`${color} font-bold`}>[{log.system}] </span>
            <span className="text-white/80">{log.message}</span>
            {log.latency && (
              <span className="text-green-500/60"> +{log.latency}ms</span>
            )}
          </div>
        );
      })}

      <div ref={bottomRef} />
    </div>
  );
}
