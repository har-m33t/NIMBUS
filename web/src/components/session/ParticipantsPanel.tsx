interface Participant {
  id: string;
  displayName: string;
  isSigning: boolean;
}

export default function ParticipantsPanel({
  roomId,
  participants,
  open,
  onToggle,
  onLeaveRoom,
}: {
  roomId: string;
  participants: Participant[];
  open: boolean;
  onToggle: () => void;
  onLeaveRoom: () => void;
}) {
  return (
    <div
      className={`flex flex-col gap-4 transition-all duration-300 ${
        open ? "w-72" : "w-0 overflow-hidden"
      }`}
    >
      {open && (
        <div className="flex flex-col gap-4 bg-white/80 backdrop-blur-sm rounded-2xl border border-nimbus-mist/10 shadow-soft p-4 h-full">
          {/* Room ID */}
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-medium text-nimbus-mist uppercase tracking-wider">Room</h3>
            <button
              onClick={onToggle}
              className="text-nimbus-mist hover:text-nimbus-text transition-colors"
              aria-label="Close participants panel"
            >
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

          {/* Participants */}
          <div className="flex-1">
            <h3 className="text-xs font-medium text-nimbus-mist uppercase tracking-wider mb-2">
              Participants ({participants.length})
            </h3>
            <div className="space-y-2">
              {participants.map((p) => (
                <div key={p.id} className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-nimbus-surface/50 transition-colors">
                  <div className="w-7 h-7 rounded-full bg-nimbus-surface flex items-center justify-center text-xs font-semibold text-nimbus-gold">
                    {p.displayName[0]?.toUpperCase()}
                  </div>
                  <span className="text-sm text-nimbus-text flex-1 truncate">{p.displayName}</span>
                  <span className={`text-[10px] ${p.isSigning ? "text-nimbus-teal" : "text-nimbus-mist"}`}>
                    {p.isSigning ? "signing" : "viewing"}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Leave Room */}
          <button
            onClick={onLeaveRoom}
            className="mt-auto px-4 py-2 rounded-xl border border-nimbus-coral/30 text-nimbus-coral text-sm font-medium hover:bg-nimbus-coral/10 transition-colors"
          >
            Leave Room
          </button>
        </div>
      )}
    </div>
  );
}
