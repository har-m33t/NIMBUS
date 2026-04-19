import { useCallback, useEffect, useRef, useState } from "react";
import { buildWsUrl } from "../config/ws.ts";

// ── Types ────────────────────────────────────────────────────────────────────

export interface PeerInfo {
  connectionId: string;
  sessionId: string;
}

export interface SdpIceFromRelay {
  from: string;
  fromSessionId: string;
  sdp?: string;
  candidate?: RTCIceCandidateInit;
}

export type InboundSignal =
  | { type: "SIGNAL"; event: "JOIN_ROOM"; sessionId: string; roomId: string; payload: { status: string; peers: PeerInfo[] } }
  | { type: "SIGNAL"; event: "PEER_JOINED"; sessionId: string; roomId: string; payload: PeerInfo }
  | { type: "SIGNAL"; event: "PEER_LEFT"; sessionId: string; roomId: string; payload: PeerInfo }
  | { type: "SIGNAL"; event: "SDP_OFFER"; sessionId: string; roomId: string; payload: SdpIceFromRelay }
  | { type: "SIGNAL"; event: "SDP_ANSWER"; sessionId: string; roomId: string; payload: SdpIceFromRelay }
  | { type: "SIGNAL"; event: "ICE_CANDIDATE"; sessionId: string; roomId: string; payload: SdpIceFromRelay }
  | { type: "GLOSS"; sessionId: string; timestamp: string; sequenceNumber: number; payload: { tokens: string[]; confidence: number } }
  | { type: "EMOTION"; sessionId: string; timestamp: string; payload: { emotion: string; confidence: number; allEmotions: Record<string, number> } }
  | { type: "CAPTION"; sessionId: string; timestamp: string; sequenceNumber: number; roomId: string; payload: { text: string; ssmlUrl?: string; emotion: string; rawGlossFallback: boolean } }
  | { type: "ERROR"; payload: { code: string; message?: string; glossFallback?: string } };

export type SocketStatus = "idle" | "connecting" | "open" | "closed" | "error";

export interface UseSessionSocketOptions {
  token: string | null;
  sessionId: string;
  roomId: string;
  onMessage: (msg: InboundSignal) => void;
}

// ── Hook ─────────────────────────────────────────────────────────────────────

export function useSessionSocket({ token, sessionId, roomId, onMessage }: UseSessionSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const [status, setStatus] = useState<SocketStatus>("idle");
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  // Reconnect timer ref
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttempt = useRef(0);

  const cleanup = useCallback(() => {
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current);
      reconnectTimer.current = null;
    }
    if (wsRef.current) {
      wsRef.current.onopen = null;
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      wsRef.current.onmessage = null;
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!token || !sessionId || !roomId) {
      setStatus("idle");
      return;
    }

    function connect() {
      cleanup();
      setStatus("connecting");

      let url: string;
      try {
        url = buildWsUrl({ token: token!, sessionId, roomId });
      } catch {
        setStatus("error");
        return;
      }

      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setStatus("open");
        reconnectAttempt.current = 0;

        // Send JOIN_ROOM as first message
        ws.send(JSON.stringify({
          action: "JOIN_ROOM",
          sessionId,
          roomId,
          payload: {},
        }));
      };

      ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data) as InboundSignal;
          onMessageRef.current(msg);
        } catch {
          // Ignore malformed messages
        }
      };

      ws.onerror = () => {
        setStatus("error");
      };

      ws.onclose = () => {
        setStatus("closed");
        // Exponential backoff reconnect (max ~30s)
        const delay = Math.min(1000 * 2 ** reconnectAttempt.current, 30000);
        reconnectAttempt.current += 1;
        reconnectTimer.current = setTimeout(connect, delay);
      };
    }

    connect();

    return cleanup;
  }, [token, sessionId, roomId, cleanup]);

  const send = useCallback((data: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  const sendWebRtcSignal = useCallback(
    (signal: "SDP_OFFER" | "SDP_ANSWER" | "ICE_CANDIDATE", target: string, payload: Record<string, unknown>) => {
      return send({
        action: "WEBRTC_SIGNAL",
        signal,
        target,
        sessionId,
        roomId,
        payload,
      }) as unknown as boolean;
    },
    [send, sessionId, roomId],
  );

  return { status, send, sendWebRtcSignal };
}
