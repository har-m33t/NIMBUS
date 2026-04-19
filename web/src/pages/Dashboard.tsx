import { useState, useEffect, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { useCloudTransition } from "../context/CloudTransitionContext.tsx";
import NimbusGlow from "../components/effects/NimbusGlow.tsx";
import SpotlightCard from "../components/ui/SpotlightCard.tsx";
import MovingBorderButton from "../components/ui/MovingBorderButton.tsx";
import NimbusButton from "../components/ui/NimbusButton.tsx";
import NimbusInput from "../components/ui/NimbusInput.tsx";
import { useRecentSessions } from "../hooks/useRecentSessions.ts";

export default function Dashboard() {
  const navigate = useNavigate();
  const [roomId, setRoomId] = useState("");
  const { phase, triggerPart } = useCloudTransition();
  const { sessions: recentSessions, clearSessions } = useRecentSessions();

  // If clouds are still enveloped (just came from login), trigger the part
  const [contentVisible, setContentVisible] = useState(phase !== "envelope");

  useEffect(() => {
    if (phase === "envelope") {
      const t1 = setTimeout(() => triggerPart(), 200);
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

  function rejoinSession(id: string) {
    navigate(`/session/${id}`);
  }

  function formatDate(iso: string) {
    try {
      const d = new Date(iso);
      return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) +
        " " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    } catch { return iso; }
  }

  return (
    <div className="relative min-h-[calc(100vh-52px)] flex flex-col items-center justify-center px-4 py-12">

      {/* Hero Section */}
      <motion.div
        initial={{ opacity: 0, y: 30 }}
        animate={contentVisible ? { opacity: 1, y: 0 } : { opacity: 0, y: 30 }}
        transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
        className="relative z-10 flex flex-col items-center text-center max-w-2xl mx-auto"
      >
        <div className="relative mb-8">
          <NimbusGlow size={350} color="gold" pulse className="-top-[120px] left-1/2 -translate-x-[175px]" />

          <h1 className="text-4xl md:text-5xl font-bold text-nimbus-text mb-3 relative">
            Begin Interpreting
          </h1>
          <p className="text-lg text-nimbus-mist relative">
            Start a real-time ASL to English session
          </p>
        </div>

        {/* Start Session CTA */}
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
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xs font-medium text-nimbus-mist uppercase tracking-wider">
            Recent Sessions
          </h2>
          {recentSessions.length > 0 && (
            <button
              onClick={clearSessions}
              className="text-[10px] text-nimbus-mist hover:text-nimbus-coral transition-colors"
            >
              Clear all
            </button>
          )}
        </div>
        <div className="space-y-3">
          {recentSessions.length === 0 ? (
            <p className="text-sm text-nimbus-mist/50 italic text-center py-6">
              No recent sessions yet. Start or join a session above.
            </p>
          ) : (
            recentSessions.map((s) => (
              <SpotlightCard key={s.roomId + s.joinedAt} className="rounded-2xl cursor-pointer group" onClick={() => rejoinSession(s.roomId)}>
                <div className="flex items-center justify-between px-5 py-4">
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 rounded-xl bg-nimbus-surface flex items-center justify-center">
                      <svg className="w-5 h-5 text-nimbus-gold" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                      </svg>
                    </div>
                    <div>
                      <p className="text-sm font-medium text-nimbus-text group-hover:text-nimbus-gold transition-colors font-mono">
                        {s.roomId}
                      </p>
                      <p className="text-xs text-nimbus-mist">{formatDate(s.joinedAt)}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-nimbus-teal font-medium">Rejoin</span>
                    <svg className="w-4 h-4 text-nimbus-mist opacity-0 group-hover:opacity-100 transition-opacity" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <polyline points="9 18 15 12 9 6" />
                    </svg>
                  </div>
                </div>
              </SpotlightCard>
            ))
          )}
        </div>
      </motion.div>
    </div>
  );
}
