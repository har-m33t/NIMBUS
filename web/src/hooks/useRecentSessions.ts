import { useState, useCallback } from "react";

export interface RecentSession {
  roomId: string;
  joinedAt: string;  // ISO timestamp
}

const STORAGE_KEY = "nimbus_recent_sessions";
const MAX_SESSIONS = 10;

function load(): RecentSession[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw) as RecentSession[];
  } catch { /* ignore */ }
  return [];
}

function save(sessions: RecentSession[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
}

export function useRecentSessions() {
  const [sessions, setSessions] = useState<RecentSession[]>(load);

  const addSession = useCallback((roomId: string) => {
    setSessions((prev) => {
      // Remove duplicate if exists, add to front
      const filtered = prev.filter((s) => s.roomId !== roomId);
      const next = [{ roomId, joinedAt: new Date().toISOString() }, ...filtered].slice(0, MAX_SESSIONS);
      save(next);
      return next;
    });
  }, []);

  const clearSessions = useCallback(() => {
    setSessions([]);
    save([]);
  }, []);

  return { sessions, addSession, clearSessions };
}
