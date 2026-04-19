const STATUS_CONFIG = {
  connected: { color: "bg-nimbus-teal", label: "Connected", ring: "ring-nimbus-teal/30" },
  disconnected: { color: "bg-nimbus-coral", label: "Disconnected", ring: "ring-nimbus-coral/30" },
  reconnecting: { color: "bg-nimbus-signal-amber", label: "Reconnecting…", ring: "ring-nimbus-signal-amber/30" },
} as const;

export default function ConnectionBadge({
  status = "disconnected",
}: {
  status: "connected" | "disconnected" | "reconnecting";
}) {
  const cfg = STATUS_CONFIG[status];

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/80 backdrop-blur-sm border border-nimbus-mist/10 text-xs font-medium shadow-soft">
      <span
        className={`w-2 h-2 rounded-full ${cfg.color} ring-2 ${cfg.ring} ${status === "reconnecting" ? "animate-pulse" : status === "connected" ? "signal-pulse" : ""}`}
      />
      <span className="text-nimbus-mist">{cfg.label}</span>
    </div>
  );
}
