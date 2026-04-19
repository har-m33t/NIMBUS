import { useState, useEffect, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { useCloudTransition } from "../context/CloudTransitionContext.tsx";
import NimbusGlow from "../components/effects/NimbusGlow.tsx";
import SpotlightCard from "../components/ui/SpotlightCard.tsx";
import MovingBorderButton from "../components/ui/MovingBorderButton.tsx";
import NimbusButton from "../components/ui/NimbusButton.tsx";
import NimbusInput from "../components/ui/NimbusInput.tsx";

export default function Dashboard() {
  const navigate = useNavigate();
  const [roomId, setRoomId] = useState("");
  const { phase, triggerPart } = useCloudTransition();

  // If clouds are still enveloped (just came from login), trigger the part
  const [contentVisible, setContentVisible] = useState(phase !== "envelope");

  useEffect(() => {
    if (phase === "envelope") {
      // Small delay so envelope is visible, then part
      const t1 = setTimeout(() => triggerPart(), 200);
      // Content fades in after clouds start moving
      const t2 = setTimeout(() => setContentVisible(true), 600);
      return () => { clearTimeout(t1); clearTimeout(t2); };
    } else {
      setContentVisible(true);
    }
  }, [phase, triggerPart]);

  function startSession() {
    const id = crypto.randomUUID().slice(0, 8);
    navigate(`/session/${id}`);
  }

  function joinRoom(e: FormEvent) {
    e.preventDefault();
    if (roomId.trim()) {
      navigate(`/session/${roomId.trim()}`);
    }
  }

  // Demo recent sessions
  const recentSessions = [
    { id: "abc123", date: "Apr 18, 2026", duration: "12m 34s", captions: 28 },
    { id: "def456", date: "Apr 17, 2026", duration: "8m 12s", captions: 15 },
    { id: "ghi789", date: "Apr 16, 2026", duration: "23m 01s", captions: 52 },
  ];

  return (
    <div className="relative min-h-[calc(100vh-52px)] flex flex-col items-center justify-center px-4 py-12">

      {/* Hero Section */}
      <motion.div
        initial={{ opacity: 0, y: 30 }}
        animate={contentVisible ? { opacity: 1, y: 0 } : { opacity: 0, y: 30 }}
        transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
        className="relative z-10 flex flex-col items-center text-center max-w-2xl mx-auto"
      >
        {/* Nimbus glow behind CTA */}
        <div className="relative mb-8">
          <NimbusGlow size={350} color="gold" pulse className="-top-[120px] left-1/2 -translate-x-[175px]" />

          <h1 className="text-4xl md:text-5xl font-bold text-nimbus-text mb-3 relative">
            Begin Interpreting
          </h1>
          <p className="text-lg text-nimbus-mist relative">
            Start a real-time ASL to English session
          </p>
        </div>

        {/* Start Session CTA — Moving Border Button */}
        <MovingBorderButton onClick={startSession} className="mb-6">
          <svg className="w-5 h-5 mr-2 text-nimbus-gold" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <polygon points="5 3 19 12 5 21 5 3" />
          </svg>
          Start Session
        </MovingBorderButton>

        {/* Join Room */}
        <form onSubmit={joinRoom} className="flex items-center gap-2 w-full max-w-sm">
          <NimbusInput
            placeholder="Enter Room ID to join…"
            value={roomId}
            onChange={(e) => setRoomId(e.target.value)}
            className="flex-1"
          />
          <NimbusButton type="submit" variant="secondary" disabled={!roomId.trim()}>
            Join
          </NimbusButton>
        </form>
      </motion.div>

      {/* Recent Sessions */}
      <motion.div
        initial={{ opacity: 0, y: 30 }}
        animate={contentVisible ? { opacity: 1, y: 0 } : { opacity: 0, y: 30 }}
        transition={{ duration: 0.8, delay: 0.15, ease: [0.22, 1, 0.36, 1] }}
        className="relative z-10 w-full max-w-2xl mt-16"
      >
        <h2 className="text-xs font-medium text-nimbus-mist uppercase tracking-wider mb-4">
          Recent Sessions
        </h2>
        <div className="space-y-3">
          {recentSessions.map((s) => (
            <SpotlightCard key={s.id} className="rounded-2xl cursor-pointer group">
              <div className="flex items-center justify-between px-5 py-4">
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 rounded-xl bg-nimbus-surface flex items-center justify-center">
                    <svg className="w-5 h-5 text-nimbus-gold" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M12 20h9M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4L16.5 3.5z" />
                    </svg>
                  </div>
                  <div>
                    <p className="text-sm font-medium text-nimbus-text group-hover:text-nimbus-gold transition-colors">
                      Session {s.id}
                    </p>
                    <p className="text-xs text-nimbus-mist">{s.date}</p>
                  </div>
                </div>
                <div className="flex items-center gap-6 text-xs text-nimbus-mist">
                  <span>{s.duration}</span>
                  <span>{s.captions} captions</span>
                  <svg className="w-4 h-4 opacity-0 group-hover:opacity-100 transition-opacity" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <polyline points="9 18 15 12 9 6" />
                  </svg>
                </div>
              </div>
            </SpotlightCard>
          ))}
        </div>
      </motion.div>
    </div>
  );
}
