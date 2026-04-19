import { type ButtonHTMLAttributes, type ReactNode } from "react";

/**
 * A button with an animated gradient border that orbits the edge.
 * Uses CSS @property for the conic-gradient angle animation.
 */
export default function MovingBorderButton({
  children,
  className = "",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { children: ReactNode }) {
  return (
    <button
      className={`moving-border relative inline-flex items-center justify-center font-semibold rounded-xl px-8 py-4 text-lg text-nimbus-text bg-white transition-all duration-200 hover:shadow-lg focus-visible:outline-2 focus-visible:outline-nimbus-gold disabled:opacity-50 disabled:cursor-not-allowed ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}
