import { motion, AnimatePresence } from "framer-motion";
import EmotionChip from "../ui/EmotionChip.tsx";

interface Caption {
  id: string;
  text: string;
  emotion: string;
  audioUrl: string | null;
  isMine: boolean;
  isFallback?: boolean;
  timestamp: string;
}

function SpeakerIcon({ active, failed }: { active: boolean; failed: boolean }) {
  if (failed) {
    return (
      <svg className="w-5 h-5 text-nimbus-mist/40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M11 5L6 9H2v6h4l5 4V5z" />
        <line x1="23" y1="9" x2="17" y2="15" />
        <line x1="17" y1="9" x2="23" y2="15" />
      </svg>
    );
  }
  return (
    <svg
      className={`w-5 h-5 transition-colors duration-300 ${active ? "text-nimbus-gold" : "text-nimbus-mist/60"}`}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
    >
      <path d="M11 5L6 9H2v6h4l5 4V5z" />
      <path d="M19.07 4.93a10 10 0 010 14.14M15.54 8.46a5 5 0 010 7.07" opacity={active ? 1 : 0.3} />
    </svg>
  );
}

export default function CaptionBar({ captions }: { captions: Caption[] }) {
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
              <EmotionChip emotion={cap.emotion} />
              <p
                className={`flex-1 text-lg leading-relaxed ${
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
              <SpeakerIcon active={false} failed={cap.audioUrl === null} />
            </motion.div>
          ))}
        </AnimatePresence>
      )}
    </div>
  );
}
