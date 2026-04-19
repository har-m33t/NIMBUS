import { createContext, useCallback, useContext, useRef, useState } from "react";

export interface TelemetryLog {
  timestamp: string;
  system: string;
  message: string;
  latency?: string;
}

interface TelemetryContextValue {
  logs: TelemetryLog[];
  addLog: (system: string, message: string, latencyMs?: string) => void;
}

const TelemetryContext = createContext<TelemetryContextValue | null>(null);

function nowHMS(): string {
  const d = new Date();
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  const ms = String(d.getMilliseconds()).padStart(3, "0");
  return `${hh}:${mm}:${ss}.${ms}`;
}

const MAX_LOGS = 200;

export function TelemetryProvider({ children }: { children: React.ReactNode }) {
  const [logs, setLogs] = useState<TelemetryLog[]>([]);
  const counterRef = useRef(0);

  const addLog = useCallback((system: string, message: string, latencyMs?: string) => {
    const entry: TelemetryLog = {
      timestamp: nowHMS(),
      system,
      message,
      ...(latencyMs !== undefined ? { latency: latencyMs } : {}),
    };
    setLogs((prev) => {
      const next = [...prev, entry];
      return next.length > MAX_LOGS ? next.slice(next.length - MAX_LOGS) : next;
    });
    counterRef.current += 1;
  }, []);

  return (
    <TelemetryContext.Provider value={{ logs, addLog }}>
      {children}
    </TelemetryContext.Provider>
  );
}

export function useTelemetry(): TelemetryContextValue {
  const ctx = useContext(TelemetryContext);
  if (!ctx) throw new Error("useTelemetry must be used inside <TelemetryProvider>");
  return ctx;
}
