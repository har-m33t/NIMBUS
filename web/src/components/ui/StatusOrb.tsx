/**
 * Animated Status Orb — replaces simple signal dot.
 * Changes color + animation based on system state.
 */

const STATES = {
  active: {
    color: "bg-nimbus-teal",
    shadow: "0 0 12px rgba(78, 205, 196, 0.4)",
    animation: "orb-pulse 2s ease-in-out infinite",
    label: "Active",
  },
  warming: {
    color: "bg-nimbus-gold",
    shadow: "0 0 16px rgba(232, 185, 49, 0.5)",
    animation: "orb-breathe 3s ease-in-out infinite",
    label: "Warming",
  },
  error: {
    color: "bg-nimbus-coral",
    shadow: "0 0 10px rgba(239, 68, 68, 0.4)",
    animation: "orb-flicker 1s ease-in-out infinite",
    label: "Error",
  },
  idle: {
    color: "bg-nimbus-signal-gray",
    shadow: "none",
    animation: "none",
    label: "Idle",
  },
} as const;

export default function StatusOrb({
  state = "idle",
}: {
  state: keyof typeof STATES;
}) {
  const cfg = STATES[state];

  return (
    <div className="flex items-center gap-2 group relative" title={cfg.label}>
      <div className="relative">
        {/* Outer glow ring */}
        <div
          className={`absolute inset-0 rounded-full ${cfg.color} opacity-30`}
          style={{
            transform: "scale(1.8)",
            filter: "blur(4px)",
            animation: cfg.animation,
          }}
        />
        {/* Core orb */}
        <div
          className={`w-3 h-3 rounded-full ${cfg.color} relative`}
          style={{
            boxShadow: cfg.shadow,
            animation: cfg.animation,
          }}
        />
      </div>
      <span className="text-xs font-medium text-nimbus-mist">{cfg.label}</span>

      {/* Tooltip */}
      <div className="absolute top-full mt-2 left-1/2 -translate-x-1/2 px-2 py-1 rounded-lg bg-white text-xs text-nimbus-mist shadow-soft opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none border border-nimbus-surface">
        System: {cfg.label}
      </div>
    </div>
  );
}
