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
  const [captionMode, setCaptionMode] = useState<"off" | "asl" | "stt">(() =>
    settings.aslEnabled ? "asl" : "off"
  );
  const [viewMode, setViewMode] = useState<"speaker" | "gallery">("speaker");
  const [pinnedId, setPinnedId] = useState<string | null>(null);

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

  const aslEnabled = captionMode === "asl";
  const seqRef = useRef(0);

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
          console.log("[Session] JOIN_ROOM ack — existing peers:", existingPeers.length, existingPeers);
          existingPeers.forEach((peer) => startOffer(peer));
          break;
        }
        case "PEER_JOINED": {
          // The joining peer initiates the offer via their JOIN_ROOM ack.
          // We wait for their SDP_OFFER — no need to offer from our side.
          console.log("[Session] PEER_JOINED — waiting for their offer:", msg.payload);
          break;
        }
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
    enabled: captionMode === "stt",
    onCaption: useCallback((caption) => {
      const entry = { id: caption.id, text: caption.text, source: "STT" as const, isMine: true, timestamp: caption.timestamp };
      setCaptions((prev) => [...prev.slice(-9), entry]);
      setTranscript((prev) => [...prev, { id: caption.id, text: caption.text, source: "STT" as const, speaker: user?.displayName || "You", timestamp: caption.timestamp }]);
    }, []),
  });

  // Leave room — single handler for both "Leave Room" buttons
  const handleLeaveRoom = useCallback(() => {
    send({ action: "LEAVE_ROOM", sessionId, roomId, payload: {} });
    cleanupWebRTC();
    if (localStream) {
      localStream.getTracks().forEach((t) => t.stop());
    }
    navigate("/");
  }, [send, sessionId, roomId, cleanupWebRTC, localStream, navigate]);

  // Send edge-inferred gloss token to the backend over WebSocket
  const handleGloss = useCallback((token: string) => {
    seqRef.current += 1;
    addLog("WEBSOCKET_TX", "Payload: AWS Bedrock Ingestion");
    send({
      action: "INFER",
      sessionId,
      roomId,
      timestamp: new Date().toISOString(),
      sequenceNumber: seqRef.current,
      payload: { token },
    });
  }, [send, sessionId, roomId, addLog]);

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

  // Clear pin when the pinned peer leaves
  useEffect(() => {
    if (pinnedId && pinnedId !== sessionId && !remotePeers.some((p) => p.sessionId === pinnedId)) {
      setPinnedId(null);
    }
  }, [remotePeers, pinnedId, sessionId]);

  // Speaker view focus — who occupies the large tile?
  const isLocalFocused = hasRemote && pinnedId === sessionId;
  const focusedRemotePeer = isLocalFocused
    ? remotePeers[0]
    : (remotePeers.find((p) => p.sessionId === pinnedId) ?? remotePeers[0]);
  const pipPeers = isLocalFocused ? remotePeers : remotePeers.filter((p) => p !== focusedRemotePeer);
  const showLocalPip = hasRemote && !isLocalFocused;

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
          {/* Caption mode — joined ASL | STT pill */}
          <div className="flex items-center rounded-lg overflow-hidden border border-nimbus-mist/10 text-xs font-medium">
            <button
              onClick={() => setCaptionMode((prev) => (prev === "asl" ? "off" : "asl"))}
              title={captionMode === "asl" ? "Stop ASL translation" : "Start ASL translation"}
              className={`flex items-center gap-1 px-2.5 py-1.5 transition-colors ${
                captionMode === "asl"
                  ? "bg-nimbus-teal/20 text-nimbus-teal"
                  : "bg-nimbus-surface text-nimbus-mist hover:text-nimbus-text"
              }`}
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M7 4v16M7 4l4 4M7 4L3 8M17 4v7M17 11a3 3 0 000 6h1a3 3 0 010 6H14" />
              </svg>
              ASL
              {captionMode === "asl" && <span className="w-1.5 h-1.5 rounded-full bg-nimbus-teal animate-pulse" />}
            </button>
            <div className="w-px h-4 bg-nimbus-mist/20 shrink-0" />
            <button
              onClick={() => sttSupported && setCaptionMode((prev) => (prev === "stt" ? "off" : "stt"))}
              title={
                sttSupported
                  ? captionMode === "stt" ? "Stop speech captions" : "Start speech captions"
                  : "Speech recognition not supported in this browser"
              }
              className={`flex items-center gap-1 px-2.5 py-1.5 transition-colors ${
                !sttSupported
                  ? "opacity-40 cursor-not-allowed bg-nimbus-surface text-nimbus-mist"
                  : captionMode === "stt"
                  ? "bg-nimbus-coral/20 text-nimbus-coral"
                  : "bg-nimbus-surface text-nimbus-mist hover:text-nimbus-text"
              }`}
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="9" y="2" width="6" height="12" rx="3" />
                <path d="M5 10a7 7 0 0014 0M12 19v3M8 22h8" />
              </svg>
              STT
              {captionMode === "stt" && <span className="w-1.5 h-1.5 rounded-full bg-nimbus-coral animate-pulse" />}
            </button>
          </div>

          {/* View toggle — only when remote peers present */}
          {hasRemote && (
            <button
              onClick={() => setViewMode((v) => (v === "speaker" ? "gallery" : "speaker"))}
              title={viewMode === "speaker" ? "Switch to gallery view" : "Switch to speaker view"}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-nimbus-surface text-nimbus-mist hover:text-nimbus-text transition-colors"
            >
              {viewMode === "speaker" ? (
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="3" y="3" width="8" height="8" rx="1" />
                  <rect x="13" y="3" width="8" height="8" rx="1" />
                  <rect x="3" y="13" width="8" height="8" rx="1" />
                  <rect x="13" y="13" width="8" height="8" rx="1" />
                </svg>
              ) : (
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="2" y="3" width="15" height="18" rx="1" />
                  <rect x="19" y="3" width="3" height="8" rx="0.5" />
                  <rect x="19" y="13" width="3" height="8" rx="0.5" />
                </svg>
              )}
              {viewMode === "speaker" ? "Gallery" : "Speaker"}
            </button>
          )}

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
            {hasRemote && viewMode === "gallery" ? (
              /* Gallery view — equal grid of all participants */
              <div
                className="grid h-full gap-1.5 p-1.5"
                style={{
                  gridTemplateColumns: "repeat(2, 1fr)",
                  gridTemplateRows: `repeat(${Math.ceil((remotePeers.length + 1) / 2)}, 1fr)`,
                }}
              >
                {/* Local tile */}
                <div
                  onClick={() => setPinnedId((prev) => (prev === sessionId ? null : sessionId))}
                  className="relative rounded-xl overflow-hidden cursor-pointer"
                  title={pinnedId === sessionId ? "Unpin" : "Pin your view"}
                >
                  <video
                    autoPlay
                    playsInline
                    muted
                    ref={(el) => { if (el) el.srcObject = localStream; }}
                    className="absolute inset-0 w-full h-full object-cover"
                    style={{ transform: "scaleX(-1)" }}
                  />
                  <div className="absolute bottom-2 left-2 text-[10px] text-white/80 bg-black/40 px-1.5 py-0.5 rounded-md z-10">You</div>
                  {pinnedId === sessionId && (
                    <div className="absolute top-2 right-2 bg-nimbus-gold rounded-full p-1 z-10">
                      <svg className="w-2.5 h-2.5 text-white" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M16 12V4h1a1 1 0 000-2H7a1 1 0 000 2h1v8l-2 2v2h4v4l1 1 1-1v-4h4v-2l-2-2z" />
                      </svg>
                    </div>
                  )}
                </div>
                {/* Remote tiles */}
                {remotePeers.map((peer, i) => (
                  <div
                    key={peer.sessionId}
                    onClick={() => setPinnedId((prev) => (prev === peer.sessionId ? null : peer.sessionId))}
                    className="relative rounded-xl overflow-hidden cursor-pointer"
                    title={pinnedId === peer.sessionId ? "Unpin" : "Pin to main view"}
                  >
                    <RemoteVideo stream={peer.stream} label={`Participant ${i + 1}`} className="absolute inset-0 w-full h-full" />
                    {pinnedId === peer.sessionId && (
                      <div className="absolute top-2 right-2 bg-nimbus-gold rounded-full p-1 z-10">
                        <svg className="w-2.5 h-2.5 text-white" viewBox="0 0 24 24" fill="currentColor">
                          <path d="M16 12V4h1a1 1 0 000-2H7a1 1 0 000 2h1v8l-2 2v2h4v4l1 1 1-1v-4h4v-2l-2-2z" />
                        </svg>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : hasRemote ? (
              /* Speaker view — one large tile + PIPs */
              <>
                {isLocalFocused ? (
                  <video
                    autoPlay
                    playsInline
                    muted
                    ref={(el) => { if (el) el.srcObject = localStream; }}
                    className="absolute inset-0 w-full h-full object-cover"
                    style={{ transform: "scaleX(-1)" }}
                  />
                ) : (
                  <RemoteVideo
                    stream={focusedRemotePeer.stream}
                    label={`Participant ${remotePeers.indexOf(focusedRemotePeer) + 1}`}
                    className="absolute inset-0 w-full h-full"
                  />
                )}
                {/* PIPs — click any to focus */}
                <div className="absolute bottom-4 right-4 flex flex-col gap-2 z-10">
                  {showLocalPip && (
                    <div
                      onClick={() => setPinnedId(sessionId)}
                      className="w-36 h-28 rounded-xl overflow-hidden border-2 border-white/30 shadow-lg cursor-pointer hover:border-nimbus-gold/60 transition-colors"
                      title="Pin your view"
                    >
                      <video
                        autoPlay
                        playsInline
                        muted
                        ref={(el) => { if (el) el.srcObject = localStream; }}
                        className="w-full h-full object-cover"
                        style={{ transform: "scaleX(-1)" }}
                      />
                    </div>
                  )}
                  {pipPeers.map((peer, i) => (
                    <div
                      key={peer.sessionId}
                      onClick={() => setPinnedId(peer.sessionId)}
                      className="w-36 h-28 rounded-xl overflow-hidden border-2 border-white/30 shadow-lg cursor-pointer hover:border-nimbus-gold/60 transition-colors"
                      title="Pin this participant"
                    >
                      <RemoteVideo stream={peer.stream} label={`P${i + 1}`} className="w-full h-full" />
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <VideoFeed stream={localStream} showOverlay={aslEnabled} enabled={aslEnabled} onGloss={handleGloss} />
            )}

            {/* Hidden VideoFeed keeps the ONNX worker + MediaPipe running during calls */}
            {aslEnabled && hasRemote && (
              <div className="absolute opacity-0 pointer-events-none w-px h-px overflow-hidden" aria-hidden="true">
                <VideoFeed stream={localStream} showOverlay={false} enabled={true} onGloss={handleGloss} />
              </div>
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
          pinnedId={pinnedId}
          onPin={(id) => setPinnedId((prev) => (prev === id ? null : id))}
        />
      </div>
    </div>
  );
}
