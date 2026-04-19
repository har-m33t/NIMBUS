/** Nimbus halo glow ring — used behind CTAs and key focal points */
export default function NimbusGlow({
  size = 200,
  color = "gold",
  pulse = true,
  className = "",
}: {
  size?: number;
  color?: "gold" | "teal";
  pulse?: boolean;
  className?: string;
}) {
  const c =
    color === "gold"
      ? "rgba(232, 185, 49, 0.18)"
      : "rgba(78, 205, 196, 0.15)";
  const c2 =
    color === "gold"
      ? "rgba(232, 185, 49, 0.06)"
      : "rgba(78, 205, 196, 0.05)";

  return (
    <div
      className={`absolute pointer-events-none ${pulse ? "nimbus-halo" : ""} ${className}`}
      aria-hidden="true"
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
        background: `radial-gradient(circle, ${c} 0%, ${c2} 40%, transparent 70%)`,
        filter: "blur(25px)",
      }}
    />
  );
}
