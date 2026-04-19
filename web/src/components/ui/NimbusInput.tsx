import { type InputHTMLAttributes } from "react";

interface Props extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
}

export default function NimbusInput({ label, error, className = "", id, ...rest }: Props) {
  const inputId = id || label?.toLowerCase().replace(/\s/g, "-");

  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      {label && (
        <label htmlFor={inputId} className="text-sm font-medium text-nimbus-mist">
          {label}
        </label>
      )}
      <input
        id={inputId}
        className={`w-full px-4 py-3 rounded-xl bg-white border text-nimbus-text placeholder:text-nimbus-mist/50 transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-nimbus-gold/50 focus:border-nimbus-gold/30 shadow-soft ${error ? "border-nimbus-coral/50" : "border-nimbus-mist/20"}`}
        {...rest}
      />
      {error && <p className="text-xs text-nimbus-coral">{error}</p>}
    </div>
  );
}
