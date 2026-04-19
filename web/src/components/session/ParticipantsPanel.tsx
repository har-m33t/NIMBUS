import { useEffect, useRef, useState } from "react";

interface Participant {
  id: string;
  displayName: string;
  isSigning: boolean;
}

interface TranscriptEntry {
  id: string;
  text: string;
  source: "STT" | "ASL";
  speaker: string;
  timestamp: string;
}

const TABS = ["Room", "People", "Transcript"] as const;

export default function ParticipantsPanel({
  roomId,
  participants,
  open,
  onToggle,
  onLeaveRoom,
  transcript,
}: {
  roomId: string;
  participants: Participant[];
  open: boolean;
  onToggle: () => void;
  onLeaveRoom: () => void;
  transcript: TranscriptEntry[];
}) {
  const [transcriptOpen, setTranscriptOpen] = useState(true);
  const [mobileTab, setMobileTab] = useState(2); // default to Transcript
  const touchStartX = useRef(0);
  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const desktopTranscriptEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
    desktopTranscriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript.length]);

  function handleTouchStart(e: React.TouchEvent) {
    touchStartX.current = e.touches[0].clientX;
  }
  function handleTouchEnd(e: React.TouchEvent) {
    const delta = e.changedTouches[0].clientX - touchStartX.current;
    if (Math.abs(delta) < 40) return;
    setMobileTab((t) => delta < 0 ? Math.min(t + 1, 2) : Math.max(t - 1, 0));
  }

  const transcriptRows = (endRef: React.RefObject<HTMLDivElement | null>) =>
    transcript.length === 0 ? (
      <p className="text-xs text-nimbus-mist/50 italic">Captions will appear here…</p>
    ) : (
      <>
        {transcript.map((t) => (
          <div key={t.id} className="flex flex-col gap-0.5 pb-1.5 border-b border-nimbus-mist/8 last:border-0">
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] font-semibold text-nimbus-text truncate">{t.speaker}</span>
              <span className={`text-[10px] px-1 py-0.5 rounded font-medium shrink-0 ${t.source === "ASL" ? "bg-nimbus-teal/20 text-nimbus-teal" : "bg-nimbus-gold/20 text-nimbus-gold"}`}>
                {t.source}
              </span>
              <span className="text-[10px] text-nimbus-mist ml-auto shrink-0">
                {new Date(t.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              </span>
            </div>
            <p className="text-xs text-nimbus-text leading-relaxed">{t.text}</p>
          </div>
        ))}
        <div ref={endRef} />
      </>
    );

  return (
    <div
      className={`flex-shrink-0 transition-all duration-300 ${
        open ? "w-full md:w-72 h-56 md:h-auto" : "h-0 md:h-auto md:w-0 overflow-hidden"
      }`}
    >
      {open && (
        <div className="flex flex-col bg-white/80 backdrop-blur-sm rounded-2xl border border-nimbus-mist/10 shadow-soft p-4 h-full overflow-hidden">

          {/* ── MOBILE: swipe carousel ── */}
          <div className="flex md:hidden flex-col flex-1 min-h-0 overflow-hidden gap-2">
            {/* Tab bar */}
            <div className="flex-shrink-0 flex items-center justify-between">
              <div className="flex gap-4">
                {TABS.map((label, i) => (
                  <button
                    key={i}
                    onClick={() => setMobileTab(i)}
                    className={`text-xs font-medium pb-0.5 border-b-2 transition-colors ${
                      mobileTab === i
                        ? "text-nimbus-text border-nimbus-gold"
                        : "text-nimbus-mist border-transparent"
                    }`}
                  >
                    {label}
                    {label === "Transcript" && transcript.length > 0 && (
                      <span className="ml-1 text-[10px] text-nimbus-mist/60">({transcript.length})</span>
                    )}
                  </button>
                ))}
              </div>
              <button onClick={onToggle} className="text-nimbus-mist hover:text-nimbus-text transition-colors" aria-label="Close panel">
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M18 6L6 18M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Swipeable panels */}
            <div
              className="flex-1 overflow-hidden"
              onTouchStart={handleTouchStart}
              onTouchEnd={handleTouchEnd}
            >
              <div
                className="flex h-full transition-transform duration-200 ease-out"
                style={{ width: "300%", transform: `translateX(${-mobileTab * 33.333}%)` }}
              >
                {/* Panel 0: Room */}
                <div className="w-1/3 h-full overflow-y-auto flex flex-col gap-2 pr-1">
                  <button
                    className="text-left px-3 py-2 rounded-lg bg-nimbus-surface text-nimbus-text text-sm font-mono truncate hover:bg-nimbus-surface/80 transition-colors"
                    onClick={() => navigator.clipboard.writeText(roomId)}
                    title="Click to copy"
                  >
                    {roomId}
                  </button>
                  <p className="text-xs text-nimbus-mist">Tap to copy room code</p>
                </div>

                {/* Panel 1: Participants */}
                <div className="w-1/3 h-full overflow-y-auto space-y-1.5 pr-1">
                  {participants.map((p) => (
                    <div key={p.id} className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-nimbus-surface/50 transition-colors">
                      <div className="w-7 h-7 rounded-full bg-nimbus-surface flex items-center justify-center text-xs font-semibold text-nimbus-gold shrink-0">
                        {p.displayName[0]?.toUpperCase()}
                      </div>
                      <span className="text-sm text-nimbus-text flex-1 truncate">{p.displayName}</span>
                      <span className={`text-[10px] shrink-0 ${p.isSigning ? "text-nimbus-teal" : "text-nimbus-mist"}`}>
                        {p.isSigning ? "signing" : "viewing"}
                      </span>
                    </div>
                  ))}
                </div>

                {/* Panel 2: Transcript */}
                <div className="w-1/3 h-full overflow-y-auto space-y-1.5 pr-1">
                  {transcriptRows(transcriptEndRef)}
                </div>
              </div>
            </div>

            {/* Leave Room */}
            <button
              onClick={onLeaveRoom}
              className="flex-shrink-0 px-4 py-2 rounded-xl border border-nimbus-coral/30 text-nimbus-coral text-sm font-medium hover:bg-nimbus-coral/10 transition-colors"
            >
              Leave Room
            </button>
          </div>

          {/* ── DESKTOP: vertical sidebar ── */}
          <div className="hidden md:flex flex-col flex-1 min-h-0 gap-3 overflow-hidden">
            {/* Room header */}
            <div className="flex-shrink-0 flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-medium text-nimbus-mist uppercase tracking-wider">Room</h3>
                <button onClick={onToggle} className="text-nimbus-mist hover:text-nimbus-text transition-colors" aria-label="Close panel">
                  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M18 6L6 18M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <button
                className="text-left px-3 py-2 rounded-lg bg-nimbus-surface text-nimbus-text text-sm font-mono truncate hover:bg-nimbus-surface/80 transition-colors"
                onClick={() => navigator.clipboard.writeText(roomId)}
                title="Click to copy Room ID"
              >
                {roomId}
              </button>
            </div>

            {/* Participants */}
            <div className={`flex flex-col overflow-hidden ${transcriptOpen ? "flex-shrink-0 max-h-40" : "flex-1 min-h-0"}`}>
              <h3 className="flex-shrink-0 text-xs font-medium text-nimbus-mist uppercase tracking-wider mb-2">
                Participants ({participants.length})
              </h3>
              <div className="flex-1 overflow-y-auto min-h-0 space-y-2">
                {participants.map((p) => (
                  <div key={p.id} className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-nimbus-surface/50 transition-colors">
                    <div className="w-7 h-7 rounded-full bg-nimbus-surface flex items-center justify-center text-xs font-semibold text-nimbus-gold shrink-0">
                      {p.displayName[0]?.toUpperCase()}
                    </div>
                    <span className="text-sm text-nimbus-text flex-1 truncate">{p.displayName}</span>
                    <span className={`text-[10px] shrink-0 ${p.isSigning ? "text-nimbus-teal" : "text-nimbus-mist"}`}>
                      {p.isSigning ? "signing" : "viewing"}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Transcript */}
            {transcriptOpen ? (
              <div className="flex-1 flex flex-col min-h-0 border-t border-nimbus-mist/10 pt-3 overflow-hidden">
                <div className="flex-shrink-0 flex items-center justify-between mb-2">
                  <h3 className="text-xs font-medium text-nimbus-mist uppercase tracking-wider">Transcript</h3>
                  <button
                    onClick={() => setTranscriptOpen(false)}
                    className="text-nimbus-mist hover:text-nimbus-text transition-colors"
                    aria-label="Collapse transcript"
                  >
                    <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M18 6L6 18M6 6l12 12" />
                    </svg>
                  </button>
                </div>
                <div className="flex-1 overflow-y-auto min-h-0 space-y-2">
                  {transcriptRows(desktopTranscriptEndRef)}
                </div>
              </div>
            ) : (
              <button
                onClick={() => setTranscriptOpen(true)}
                className="flex-shrink-0 flex items-center gap-2 border-t border-nimbus-mist/10 pt-3 text-xs text-nimbus-mist hover:text-nimbus-text transition-colors"
              >
                <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />
                </svg>
                Transcript
                {transcript.length > 0 && (
                  <span className="ml-auto bg-nimbus-mist/20 rounded px-1.5 py-0.5 font-medium">{transcript.length}</span>
                )}
              </button>
            )}

            {/* Leave Room */}
            <button
              onClick={onLeaveRoom}
              className="flex-shrink-0 mt-auto px-4 py-2 rounded-xl border border-nimbus-coral/30 text-nimbus-coral text-sm font-medium hover:bg-nimbus-coral/10 transition-colors"
            >
              Leave Room
            </button>
          </div>

        </div>
      )}
    </div>
  );
}
