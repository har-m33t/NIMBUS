import { motion } from "framer-motion";

interface GlossToken {
  token: string;
  confidence: number;
  isError?: boolean;
}

export default function GlossTokenPill({ token, confidence, isError }: GlossToken) {
  return (
    <motion.span
      initial={{ opacity: 0, x: 20, scale: 0.9 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, scale: 0.8 }}
      transition={{ duration: 0.2, ease: [0.4, 0, 0.2, 1] }}
      className={`inline-flex items-center px-3 py-1.5 rounded-lg text-sm font-mono font-medium ${
        isError
          ? "bg-nimbus-coral/20 text-nimbus-coral border border-nimbus-coral/30"
          : "bg-nimbus-elevated text-nimbus-text border border-nimbus-mist/10"
      }`}
      style={{ opacity: isError ? 1 : Math.max(0.5, confidence) }}
    >
      {token}
    </motion.span>
  );
}
