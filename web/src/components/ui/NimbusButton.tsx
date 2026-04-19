import { type ButtonHTMLAttributes } from "react";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  size?: "sm" | "md" | "lg";
  glow?: boolean;
  loading?: boolean;
}

export default function NimbusButton({
  variant = "primary",
  size = "md",
  glow = false,
  loading = false,
  className = "",
  children,
  disabled,
  ...rest
}: Props) {
  const base =
    "relative inline-flex items-center justify-center font-semibold rounded-xl transition-all duration-200 focus-visible:outline-2 focus-visible:outline-nimbus-gold";

  const sizes = {
    sm: "px-4 py-2 text-sm",
    md: "px-6 py-3 text-base",
    lg: "px-8 py-4 text-lg",
  };

  const variants = {
    primary:
      "bg-nimbus-gold text-white hover:brightness-110 active:brightness-95 shadow-md",
    secondary:
      "border border-nimbus-mist/20 text-nimbus-text bg-white hover:bg-nimbus-surface hover:border-nimbus-mist/40 shadow-soft",
    danger:
      "border border-nimbus-coral/30 text-nimbus-coral bg-white hover:bg-red-50 hover:border-nimbus-coral/50",
    ghost:
      "text-nimbus-mist hover:text-nimbus-text hover:bg-nimbus-surface/60",
  };

  return (
    <button
      className={`${base} ${sizes[size]} ${variants[variant]} ${glow && variant === "primary" ? "nimbus-glow nimbus-glow-hover" : ""} ${disabled || loading ? "opacity-50 cursor-not-allowed" : ""} ${className}`}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && (
        <svg
          className="animate-spin -ml-1 mr-2 h-4 w-4"
          fill="none"
          viewBox="0 0 24 24"
        >
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      )}
      {children}
    </button>
  );
}
