import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useAuth } from "../context/AuthContext.tsx";
import { useSettings } from "../context/SettingsContext.tsx";
import { useTelemetry } from "../context/TelemetryContext.tsx";
import { useLocalMedia } from "../hooks/useLocalMedia.ts";
import {
  useSessionSocket,
  type InboundSignal,
  type PeerInfo,
} from "../hooks/useSessionSocket.ts";
import { useWebRTC } from "../hooks/useWebRTC.ts";
import { useSpeechCaptions } from "../hooks/useSpeechCaptions.ts";
import VideoFeed from "../components/session/VideoFeed.tsx";
import RemoteVideo from "../components/session/RemoteVideo.tsx";
import CaptionBar from "../components/session/CaptionBar.tsx";
import ParticipantsPanel from "../components/session/ParticipantsPanel.tsx";

export default function Session() {
  const { roomId = "unknown" } = useParams<{ roomId: string }>();
  const { user, idToken } = useAuth();
  const { settings } = useSettings();
  const { addLog } = useTelemetry();
  const navigate = useNavigate();
  const [panelOpen, setPanelOpen] = useState(true);
  const [aslEnabled, setAslEnabled] = useState(settings.aslEnabled);
  const [sttEnabled, setSttEnabled] = useState(false);
  const [targetLanguage, setTargetLanguage] = useState("en");

  // Live captions shown in the overlay (last few)
  const [captions, setCaptions] = useState<{ id: string; text: string; source: "ASL" | "STT"; isMine: boolean; isFallback?: boolean; timestamp: string }[]>([]);
  // Transcript accumulates all captions
  const [transcript, setTranscript] = useState<{ id: string; text: string; source: "STT" | "ASL"; speaker: string; timestamp: string }[]>([]);
  const ttsAudioRef = useRef<HTMLAudioElement | null>(null);

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
      if (msg.type === "EMOTION") {
        addLog("REKOGNITION", `Emotion Override: ${msg.payload.emotion}`);
        return;
      }

      if (msg.type === "CAPTION") {
        addLog("BEDROCK", `NLP Generation: ${msg.payload.text}`);
        if (msg.payload.ssmlUrl) {
          addLog("POLLY", "Neural Voice Audio URL Ready");
        }

        const entry = {
          id: `${msg.sequenceNumber}-${msg.timestamp}`,
          text: msg.payload.text,
          source: "ASL" as const,
          isMine: msg.sessionId === sessionId,
          isFallback: msg.payload.rawGlossFallback,
          timestamp: msg.timestamp,
        };
        setCaptions((prev) => [...prev.slice(-9), entry]);
        setTranscript((prev) => [...prev, { id: entry.id, text: entry.text, source: "ASL", speaker: entry.isMine ? (user?.displayName || "You") : "Participant", timestamp: entry.timestamp }]);
        if (msg.payload.ssmlUrl) {
          if (ttsAudioRef.current) ttsAudioRef.current.pause();
          ttsAudioRef.current = new Audio(msg.payload.ssmlUrl);
          ttsAudioRef.current.play().catch(() => {});
        }
        return;
      }

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
    [sessionId, startOffer, removePeer, handleSignal, addLog],
  );

  // WebSocket connection
  const { status: _wsStatus, send, sendWebRtcSignal } = useSessionSocket({
    token: idToken,
    sessionId,
    roomId,
    userId: user?.id,
    onMessage,
  });

  sendSignalRef.current = sendWebRtcSignal;

  // STT captions — fires for each final spoken sentence
  const { interimText, supported: sttSupported } = useSpeechCaptions({
    enabled: sttEnabled,
    onCaption: useCallback((caption) => {
      const entry = { id: caption.id, text: caption.text, source: "STT" as const, isMine: true, timestamp: caption.timestamp };
      setCaptions((prev) => [...prev.slice(-9), entry]);
      setTranscript((prev) => [...prev, { id: caption.id, text: caption.text, source: "STT" as const, speaker: user?.displayName || "You", timestamp: caption.timestamp }]);
    }, []),
  });

  // Wraps `send` so every INFER message carries the current targetLanguage + telemetry log.
  const sendInfer = useCallback(
    (inferPayload: Record<string, unknown>) => {
      addLog("WEBSOCKET_TX", "Payload: AWS Bedrock Ingestion");
      send({ ...inferPayload, targetLanguage });
    },
    [send, targetLanguage, addLog],
  );

  // Leave room — single handler for both "Leave Room" buttons
  const handleLeaveRoom = useCallback(() => {
    send({ action: "LEAVE_ROOM", sessionId, roomId, payload: {} });
    cleanupWebRTC();
    if (localStream) {
      localStream.getTracks().forEach((t) => t.stop());
    }
    navigate("/");
  }, [send, sessionId, roomId, cleanupWebRTC, localStream, navigate]);

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
          {/* ASL toggle */}
          <button
            onClick={() => setAslEnabled(!aslEnabled)}
            title={aslEnabled ? "Stop ASL translation" : "Start ASL translation"}
            className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              aslEnabled
                ? "bg-nimbus-teal/20 text-nimbus-teal"
                : "bg-nimbus-surface text-nimbus-mist hover:text-nimbus-text"
            }`}
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M7 4v16M7 4l4 4M7 4L3 8M17 4v7M17 11a3 3 0 000 6h1a3 3 0 010 6H14" />
            </svg>
            ASL
            {aslEnabled && <span className="w-1.5 h-1.5 rounded-full bg-nimbus-teal animate-pulse" />}
          </button>

          {/* STT mic toggle */}
          <button
            onClick={() => sttSupported && setSttEnabled(!sttEnabled)}
            title={sttSupported ? (sttEnabled ? "Stop speech captions" : "Start speech captions") : "Speech recognition not supported in this browser"}
            className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              !sttSupported
                ? "opacity-40 cursor-not-allowed bg-nimbus-surface text-nimbus-mist"
                : sttEnabled
                ? "bg-nimbus-coral/20 text-nimbus-coral"
                : "bg-nimbus-surface text-nimbus-mist hover:text-nimbus-text"
            }`}
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="9" y="2" width="6" height="12" rx="3" />
              <path d="M5 10a7 7 0 0014 0M12 19v3M8 22h8" />
            </svg>
            STT
            {sttEnabled && <span className="w-1.5 h-1.5 rounded-full bg-nimbus-coral animate-pulse" />}
          </button>

          {/* Output language selector */}
          <label className="flex items-center gap-1.5">
            <span className="sr-only">Output Language</span>
            <select
              value={targetLanguage}
              onChange={(e) => setTargetLanguage(e.target.value)}
              aria-label="Output Language"
              className="px-2 py-1.5 rounded-lg text-xs font-medium bg-nimbus-surface text-nimbus-text border border-nimbus-mist/20 focus:outline-none focus:ring-1 focus:ring-nimbus-teal cursor-pointer"
            >
              <option value="en">English</option>
              <option value="es">Spanish (es)</option>
              <option value="fr">French (fr)</option>
              <option value="ja">Japanese (ja)</option>
            </select>
          </label>

          {/* Toggle participants */}
          <button
            onClick={() => setPanelOpen(!panelOpen)}
            className="p-2 rounded-lg hover:bg-nimbus-surface text-nimbus-mist hover:text-nimbus-text transition-colors"
            title="Toggle participants"
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 12h18M3 6h18M3 18h18" />
            </svg>
          </button>

        </div>
      </div>

      {/* Main session layout */}
      <div className="flex-1 flex flex-col md:flex-row gap-4 p-4 overflow-hidden">
        {/* Video area — full width on mobile, left column on desktop */}
        <div className="flex-1 flex flex-col gap-3 min-w-0 min-h-0">
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
              <VideoFeed stream={localStream} showOverlay={false} isTracking={!!localStream} onInfer={sendInfer} />
            )}

            {/* Caption overlay INSIDE the video */}
            <div
              className={`absolute left-0 right-0 z-20 px-4 py-2 pointer-events-none ${
                settings.captionPos === "top" ? "top-0" : "bottom-0"
              }`}
            >
              <CaptionBar captions={captions} fontSize={captionFontSize} overlay />
              {interimText && (
                <div className="mt-1">
                  <span className={`inline-block px-3 py-1.5 rounded-lg bg-black/40 text-white/70 italic ${captionFontSize} leading-relaxed`}>
                    {interimText}
                  </span>
                </div>
              )}
            </div>
          </div>

        </div>

        {/* Right: Participants + Transcript Panel */}
        <ParticipantsPanel
          roomId={roomId}
          participants={participants}
          open={panelOpen}
          onToggle={() => setPanelOpen(false)}
          onLeaveRoom={handleLeaveRoom}
          transcript={transcript}
        />
      </div>
    </div>
  );
}
