const SIGNAL_CONFIG = {
  strong: { color: "bg-nimbus-signal-green", label: "Strong", text: "text-nimbus-signal-green" },
  degraded: { color: "bg-nimbus-signal-amber", label: "Degraded", text: "text-nimbus-signal-amber" },
  poor: { color: "bg-nimbus-signal-red", label: "Poor", text: "text-nimbus-signal-red" },
  offline: { color: "bg-nimbus-signal-gray", label: "Offline", text: "text-nimbus-signal-gray" },
} as const;

function getSignalStatus(latencyMs: number | null): keyof typeof SIGNAL_CONFIG {
  if (latencyMs === null) return "offline";
  if (latencyMs < 800) return "strong";
  if (latencyMs <= 1500) return "degraded";
  return "poor";
}

export default function SignalIndicator({ latencyMs }: { latencyMs: number | null }) {
  const status = getSignalStatus(latencyMs);
  const cfg = SIGNAL_CONFIG[status];

  return (
    <div className="flex items-center gap-2 group relative" title={latencyMs !== null ? `${latencyMs}ms` : "No signal"}>
      <span
        className={`w-2.5 h-2.5 rounded-full ${cfg.color} ${status !== "offline" ? "signal-pulse" : ""}`}
      />
      <span className={`text-xs font-medium ${cfg.text}`}>{cfg.label}</span>

      {/* Tooltip */}
      <div className="absolute top-full mt-2 left-1/2 -translate-x-1/2 px-2 py-1 rounded-lg bg-white text-xs text-nimbus-mist shadow-soft border border-nimbus-surface opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none">
        {latencyMs !== null ? `Pipeline latency: ${latencyMs}ms` : "No response"}
      </div>
    </div>
  );
}
