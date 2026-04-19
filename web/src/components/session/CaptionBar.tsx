import { motion, AnimatePresence } from "framer-motion";

interface Caption {
  id: string;
  text: string;
  source?: "STT" | "ASL";
  isMine: boolean;
  isFallback?: boolean;
  timestamp: string;
}

export default function CaptionBar({
  captions,
  fontSize = "text-base",
  overlay = false,
}: {
  captions: Caption[];
  fontSize?: string;
  overlay?: boolean;
}) {
  if (overlay) {
    // Overlay mode: translucent multi-line captions inside the video
    return (
      <div className="pointer-events-none">
        <AnimatePresence initial={false}>
          {captions.slice(-3).map((cap) => (
            <motion.div
              key={cap.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.25 }}
              className="mb-1"
            >
              <span
                className={`inline-block px-3 py-1.5 rounded-lg bg-black/60 text-white ${fontSize} leading-relaxed max-w-full`}
                style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}
              >
                {cap.text}
              </span>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    );
  }

  // Standard mode (non-overlay)
  return (
    <div
      className="w-full bg-white/80 backdrop-blur-sm rounded-xl border border-nimbus-mist/10 shadow-soft p-4 max-h-64 overflow-y-auto"
      role="log"
      aria-live="polite"
      aria-label="Live captions"
    >
      {captions.length === 0 ? (
        <p className="text-sm text-nimbus-mist/50 italic text-center py-4">
          Captions will appear here as you sign…
        </p>
      ) : (
        <AnimatePresence initial={false}>
          {captions.map((cap) => (
            <motion.div
              key={cap.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, ease: "easeOut" }}
              className={`flex items-start gap-3 py-2.5 ${cap.isMine ? "" : "flex-row-reverse text-right"}`}
            >
              <p
                className={`flex-1 ${fontSize} leading-relaxed ${
                  cap.isFallback
                    ? "font-mono italic text-nimbus-mist/70"
                    : "text-nimbus-text"
                }`}
              >
                {cap.isFallback && (
                  <span className="text-xs bg-nimbus-signal-amber/20 text-nimbus-signal-amber px-1.5 py-0.5 rounded mr-2">
                    ⚠ raw gloss
                  </span>
                )}
                {cap.text}
              </p>
            </motion.div>
          ))}
        </AnimatePresence>
      )}
    </div>
  );
}
