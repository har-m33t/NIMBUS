import { useState } from "react";
import { useParams } from "react-router-dom";
import VideoFeed from "../components/session/VideoFeed.tsx";
import GlossTicker from "../components/session/GlossTicker.tsx";
import CaptionBar from "../components/session/CaptionBar.tsx";
import ParticipantsPanel from "../components/session/ParticipantsPanel.tsx";
import WarmingOverlay from "../components/session/WarmingOverlay.tsx";
import StatusOrb from "../components/ui/StatusOrb.tsx";
import NimbusButton from "../components/ui/NimbusButton.tsx";

export default function Session() {
  const { roomId } = useParams<{ roomId: string }>();
  const [panelOpen, setPanelOpen] = useState(true);
  const [showWarming, setShowWarming] = useState(false);

  // Demo data — will be driven by WebSocket in production
  const demoTokens = [
    { id: "1", token: "STORE", confidence: 0.92 },
    { id: "2", token: "I", confidence: 0.95 },
    { id: "3", token: "GO", confidence: 0.88 },
    { id: "4", token: "TO", confidence: 0.85 },
  ];

  const demoCaptions = [
    {
      id: "c1",
      text: "I am going to the store.",
      emotion: "HAPPY",
      audioUrl: "https://example.com/audio.mp3",
      isMine: true,
      timestamp: new Date().toISOString(),
    },
    {
      id: "c2",
      text: "The weather is really nice today.",
      emotion: "CALM",
      audioUrl: null,
      isMine: true,
      isFallback: false,
      timestamp: new Date().toISOString(),
    },
    {
      id: "c3",
      text: "HELLO FRIEND WAVE",
      emotion: "HAPPY",
      audioUrl: null,
      isMine: false,
      isFallback: true,
      timestamp: new Date().toISOString(),
    },
  ];

  const demoParticipants = [
    { id: "p1", displayName: "You", isSigning: true },
    { id: "p2", displayName: "Teammate", isSigning: false },
  ];

  const orbState = showWarming ? "warming" as const : "active" as const;

  return (
    <div className="h-[calc(100vh-52px)] flex flex-col bg-nimbus-bg">
      {/* Session toolbar */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-nimbus-mist/10 bg-white/60 backdrop-blur-sm">
        <div className="flex items-center gap-4">
          <span className="text-xs font-mono text-nimbus-mist">
            Room: <span className="text-nimbus-text font-medium">{roomId}</span>
          </span>
        </div>
        <div className="flex items-center gap-4">
          <StatusOrb state={orbState} />

          {/* Toggle overlay */}
          <button
            className="p-2 rounded-lg hover:bg-nimbus-surface text-nimbus-mist hover:text-nimbus-text transition-colors"
            title="Toggle skeleton overlay"
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          </button>

          {/* Toggle participants */}
          <button
            onClick={() => setPanelOpen(!panelOpen)}
            className="p-2 rounded-lg hover:bg-nimbus-surface text-nimbus-mist hover:text-nimbus-text transition-colors"
            title="Toggle participants"
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4-4v2" />
              <circle cx="9" cy="7" r="4" />
              <path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" />
            </svg>
          </button>

          {/* Volume */}
          <input
            type="range"
            min="0"
            max="100"
            defaultValue="80"
            className="w-20 accent-nimbus-gold"
            title="TTS Volume"
          />

          {/* Demo warming toggle */}
          <NimbusButton
            variant="ghost"
            size="sm"
            onClick={() => setShowWarming(!showWarming)}
          >
            {showWarming ? "Hide" : "Show"} Warming
          </NimbusButton>

          {/* End Session */}
          <NimbusButton variant="danger" size="sm">
            End Session
          </NimbusButton>
        </div>
      </div>

      {/* Main session layout */}
      <div className="flex-1 flex gap-4 p-4 overflow-hidden">
        {/* Left: Video + Gloss + Captions */}
        <div className="flex-1 flex flex-col gap-3 min-w-0">
          {/* Video Feed */}
          <div className="flex-shrink-0">
            <VideoFeed showOverlay isTracking />
          </div>

          {/* Gloss Ticker */}
          <GlossTicker tokens={demoTokens} />

          {/* Caption Bar */}
          <div className="flex-1 min-h-0">
            <CaptionBar captions={demoCaptions} />
          </div>
        </div>

        {/* Right: Participants Panel */}
        <ParticipantsPanel
          roomId={roomId || "unknown"}
          participants={demoParticipants}
          emotion="HAPPY"
          emotionConfidence={0.93}
          open={panelOpen}
          onToggle={() => setPanelOpen(false)}
        />
      </div>

      {/* Warming Overlay */}
      <WarmingOverlay visible={showWarming} />
    </div>
  );
}
