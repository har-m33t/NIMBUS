import { AnimatePresence } from "framer-motion";
import GlossTokenPill from "./GlossTokenPill.tsx";

interface Token {
  id: string;
  token: string;
  confidence: number;
  isError?: boolean;
}

export default function GlossTicker({ tokens }: { tokens: Token[] }) {
  return (
    <div className="w-full px-4 py-3 bg-white/80 backdrop-blur-sm rounded-xl border border-nimbus-mist/10 shadow-soft overflow-x-auto">
      <div className="flex items-center gap-2 min-h-[36px]">
        {tokens.length === 0 ? (
          <span className="text-sm text-nimbus-mist/50 italic">
            Waiting for signs…
          </span>
        ) : (
          <AnimatePresence mode="popLayout">
            {tokens.map((t) => (
              <GlossTokenPill
                key={t.id}
                token={t.token}
                confidence={t.confidence}
                isError={t.isError}
              />
            ))}
          </AnimatePresence>
        )}
      </div>
    </div>
  );
}
