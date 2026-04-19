import { type ReactNode } from "react";

interface Props {
  children: ReactNode;
  className?: string;
  strong?: boolean;
  glow?: boolean;
}

export default function GlassCard({ children, className = "", strong = false, glow = false }: Props) {
  return (
    <div
      className={`${strong ? "glass-strong" : "glass"} rounded-2xl ${glow ? "nimbus-glow" : ""} ${className}`}
    >
      {children}
    </div>
  );
}
