import { motion, AnimatePresence } from "framer-motion";
import NimbusGlow from "../effects/NimbusGlow.tsx";
import WarmthParticles from "../effects/WarmthParticles.tsx";

export default function WarmingOverlay({ visible }: { visible: boolean }) {
  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.5, ease: "easeInOut" }}
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: "rgba(248, 250, 255, 0.92)", backdropFilter: "blur(20px)" }}
        >
          <WarmthParticles />

          <div className="relative flex flex-col items-center gap-6 text-center z-10">
            {/* Halo rings */}
            <div className="relative w-40 h-40 flex items-center justify-center">
              <NimbusGlow size={300} color="gold" pulse className="-top-[80px] -left-[80px]" />
              <div className="w-20 h-20 rounded-full border border-nimbus-gold/20 nimbus-halo" />
              <div
                className="absolute w-32 h-32 rounded-full border border-nimbus-gold/10 nimbus-halo"
                style={{ animationDelay: "0.5s" }}
              />
              <div
                className="absolute w-40 h-40 rounded-full border border-nimbus-gold/5 nimbus-halo"
                style={{ animationDelay: "1s" }}
              />
            </div>

            <h2 className="text-2xl font-semibold text-nimbus-text">
              Warming up the AI model…
            </h2>
            <p className="text-nimbus-mist">
              This usually takes 30–90 seconds on first use.
            </p>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
