import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useAuth } from "../context/AuthContext.tsx";
import { useSettings } from "../context/SettingsContext.tsx";
import { useLocalMedia } from "../hooks/useLocalMedia.ts";
import {
  useSessionSocket,
  type InboundSignal,
  type PeerInfo,
} from "../hooks/useSessionSocket.ts";
import { useWebRTC } from "../hooks/useWebRTC.ts";
import VideoFeed from "../components/session/VideoFeed.tsx";
import RemoteVideo from "../components/session/RemoteVideo.tsx";
import CaptionBar from "../components/session/CaptionBar.tsx";
import ParticipantsPanel from "../components/session/ParticipantsPanel.tsx";

export default function Session() {
  const { roomId = "unknown" } = useParams<{ roomId: string }>();
  const { user, idToken } = useAuth();
  const { settings } = useSettings();
  const navigate = useNavigate();
  const [panelOpen, setPanelOpen] = useState(true);
  const [aslEnabled, setAslEnabled] = useState(settings.aslEnabled);

  // Transcript accumulates all captions
  const [transcript, _setTranscript] = useState<{ id: string; text: string; source: "STT" | "ASL"; timestamp: string }[]>([]);
  // _setTranscript will be used when ProcessFrame pipeline sends real captions
  const [showTranscript, setShowTranscript] = useState(false);

  // Stable session ID for this browser tab
  const sessionId = useMemo(() => crypto.randomUUID(), []);

  // Save this session to recent sessions
  useEffect(() => {
    try {
      const STORAGE_KEY = "nimbus_recent_sessions";
      const MAX = 10;
      const raw = localStorage.getItem(STORAGE_KEY);
      const prev: { roomId: string; joinedAt: string }[] = raw ? JSON.parse(raw) : [];
      const filtered = prev.filter((s) => s.roomId !== roomId);
      const next = [{ roomId, joinedAt: new Date().toISOString() }, ...filtered].slice(0, MAX);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch { /* ignore */ }
  }, [roomId]);

  // Local camera + mic
  const { stream: localStream, error: mediaError } = useLocalMedia(true);

  // Ref to hold sendWebRtcSignal once socket is ready
  const sendSignalRef = useRef<(signal: "SDP_OFFER" | "SDP_ANSWER" | "ICE_CANDIDATE", target: string, payload: Record<string, unknown>) => boolean>(
    () => false,
  );

  // WebRTC peer connections
  const {
    peers: remotePeers,
    startOffer,
    handleSignal,
    removePeer,
    cleanup: cleanupWebRTC,
  } = useWebRTC({
    localStream,
    sendWebRtcSignal: useCallback(
      (signal: "SDP_OFFER" | "SDP_ANSWER" | "ICE_CANDIDATE", target: string, payload: Record<string, unknown>) =>
        sendSignalRef.current(signal, target, payload),
      [],
    ),
  });

  // Handle inbound WebSocket messages
  const onMessage = useCallback(
    (msg: InboundSignal) => {
      if (msg.type !== "SIGNAL") return;

      switch (msg.event) {
        case "JOIN_ROOM": {
          const existingPeers = (msg.payload as { status: string; peers: PeerInfo[] }).peers || [];
          existingPeers.forEach((peer) => startOffer(peer));
          break;
        }
        case "PEER_JOINED":
          break;
        case "PEER_LEFT": {
          const payload = msg.payload as PeerInfo;
          removePeer(payload.connectionId);
          break;
        }
        case "SDP_OFFER":
        case "SDP_ANSWER":
        case "ICE_CANDIDATE": {
          handleSignal(msg.event, msg.payload as import("../hooks/useSessionSocket.ts").SdpIceFromRelay);
          break;
        }
      }
    },
    [startOffer, removePeer, handleSignal],
  );

  // WebSocket connection
  const { status: _wsStatus, send, sendWebRtcSignal } = useSessionSocket({
    token: idToken,
    sessionId,
    roomId,
    onMessage,
  });

  sendSignalRef.current = sendWebRtcSignal;

  // Leave room — single handler for both "Leave Room" buttons
  const handleLeaveRoom = useCallback(() => {
    send({ action: "LEAVE_ROOM", sessionId, roomId, payload: {} });
    cleanupWebRTC();
    if (localStream) {
      localStream.getTracks().forEach((t) => t.stop());
    }
    navigate("/");
  }, [send, sessionId, roomId, cleanupWebRTC, localStream, navigate]);

  // Demo captions (will be driven by ProcessFrame pipeline)
  const demoCaptions = [
    {
      id: "c1",
      text: "I am going to the store.",
      source: "ASL" as const,
      isMine: true,
      timestamp: new Date().toISOString(),
    },
  ];

  // Build participants list — show display name, not raw ID
  const participants = [
    { id: sessionId, displayName: user?.displayName || "You", isSigning: true },
    ...remotePeers.map((p, i) => ({
      id: p.sessionId,
      displayName: `Participant ${i + 1}`,
      isSigning: false,
    })),
  ];

  const hasRemote = remotePeers.length > 0;
  const captionFontSize = { small: "text-sm", medium: "text-base", large: "text-xl" }[settings.fontSize];

  return (
    <div className="h-[calc(100vh-52px)] flex flex-col bg-nimbus-bg">
      {/* Session toolbar */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-nimbus-mist/10 bg-white/60 backdrop-blur-sm z-20">
        <div className="flex items-center gap-4">
          <span className="text-xs font-mono text-nimbus-mist">
            Room: <span className="text-nimbus-text font-medium">{roomId}</span>
          </span>
          {mediaError && (
            <span className="text-xs text-nimbus-coral">Camera: {mediaError}</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {/* ASL Translation toggle */}
          <label className="flex items-center gap-2 text-xs text-nimbus-mist cursor-pointer select-none">
            ASL
            <button
              onClick={() => setAslEnabled(!aslEnabled)}
              className={`relative w-9 h-5 rounded-full transition-colors ${aslEnabled ? "bg-nimbus-teal" : "bg-nimbus-mist/30"}`}
            >
              <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${aslEnabled ? "translate-x-4" : ""}`} />
            </button>
          </label>

          {/* Transcript toggle */}
          <button
            onClick={() => setShowTranscript(!showTranscript)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${showTranscript ? "bg-nimbus-gold/20 text-nimbus-gold" : "bg-nimbus-surface text-nimbus-mist hover:text-nimbus-text"}`}
            title="Toggle transcript"
          >
            Transcript
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

        </div>
      </div>

      {/* Main session layout */}
      <div className="flex-1 flex gap-4 p-4 overflow-hidden">
        {/* Left: Video area + Captions overlay */}
        <div className="flex-1 flex flex-col gap-3 min-w-0">
          {/* Video area with caption overlay */}
          <div className="relative flex-1 min-h-0 rounded-2xl overflow-hidden bg-nimbus-elevated border border-nimbus-mist/10">
            {hasRemote ? (
              <>
                <RemoteVideo
                  stream={remotePeers[0].stream}
                  label={`Participant 1`}
                  className="absolute inset-0 w-full h-full"
                />
                {/* Local PIP */}
                <div className="absolute bottom-4 right-4 w-36 h-28 rounded-xl overflow-hidden border-2 border-white/30 shadow-lg z-10">
                  <video
                    autoPlay
                    playsInline
                    muted
                    ref={(el) => { if (el) el.srcObject = localStream; }}
                    className="w-full h-full object-cover"
                    style={{ transform: "scaleX(-1)" }}
                  />
                </div>
              </>
            ) : (
              <VideoFeed stream={localStream} showOverlay={false} isTracking={!!localStream} />
            )}

            {/* Caption overlay INSIDE the video */}
            <div
              className={`absolute left-0 right-0 z-20 px-4 py-2 pointer-events-none ${
                settings.captionPos === "top" ? "top-0" : "bottom-0"
              }`}
            >
              <CaptionBar captions={demoCaptions} fontSize={captionFontSize} overlay />
            </div>
          </div>

          {/* Transcript panel (collapsible) */}
          {showTranscript && (
            <div className="flex-shrink-0 max-h-48 overflow-y-auto bg-white/80 backdrop-blur-sm rounded-xl border border-nimbus-mist/10 shadow-soft p-4">
              <h3 className="text-xs font-medium text-nimbus-mist uppercase tracking-wider mb-2">Transcript</h3>
              {transcript.length === 0 && demoCaptions.length > 0 ? (
                <div className="space-y-1">
                  {demoCaptions.map((c) => (
                    <div key={c.id} className="flex items-start gap-2 text-sm">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${c.source === "ASL" ? "bg-nimbus-teal/20 text-nimbus-teal" : "bg-nimbus-gold/20 text-nimbus-gold"}`}>
                        {c.source}
                      </span>
                      <span className="text-nimbus-text">{c.text}</span>
                      <span className="text-nimbus-mist text-[10px] ml-auto whitespace-nowrap">
                        {new Date(c.timestamp).toLocaleTimeString()}
                      </span>
                    </div>
                  ))}
                </div>
              ) : transcript.length === 0 ? (
                <p className="text-sm text-nimbus-mist/50 italic">Transcript will appear here...</p>
              ) : (
                <div className="space-y-1">
                  {transcript.map((t) => (
                    <div key={t.id} className="flex items-start gap-2 text-sm">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${t.source === "ASL" ? "bg-nimbus-teal/20 text-nimbus-teal" : "bg-nimbus-gold/20 text-nimbus-gold"}`}>
                        {t.source}
                      </span>
                      <span className="text-nimbus-text">{t.text}</span>
                      <span className="text-nimbus-mist text-[10px] ml-auto whitespace-nowrap">
                        {new Date(t.timestamp).toLocaleTimeString()}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right: Participants Panel */}
        <ParticipantsPanel
          roomId={roomId}
          participants={participants}
          open={panelOpen}
          onToggle={() => setPanelOpen(false)}
          onLeaveRoom={handleLeaveRoom}
        />
      </div>
    </div>
  );
}
