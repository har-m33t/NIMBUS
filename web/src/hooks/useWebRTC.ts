import { useCallback, useEffect, useRef, useState } from "react";
import type { PeerInfo, SdpIceFromRelay } from "./useSessionSocket.ts";

export interface RemotePeer {
  connectionId: string;
  sessionId: string;
  stream: MediaStream;
}

const ICE_SERVERS: RTCIceServer[] = [
  { urls: ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"] },
  {
    urls: "turn:openrelay.metered.ca:80",
    username: "openrelayproject",
    credential: "openrelayproject",
  },
  {
    urls: "turn:openrelay.metered.ca:443",
    username: "openrelayproject",
    credential: "openrelayproject",
  },
  {
    urls: "turn:openrelay.metered.ca:443?transport=tcp",
    username: "openrelayproject",
    credential: "openrelayproject",
  },
];

export interface UseWebRTCArgs {
  localStream: MediaStream | null;
  ownSessionId: string;
  sendWebRtcSignal: (
    signal: "SDP_OFFER" | "SDP_ANSWER" | "ICE_CANDIDATE",
    target: string,
    payload: Record<string, unknown>,
  ) => boolean;
}

export function useWebRTC({ localStream, ownSessionId, sendWebRtcSignal }: UseWebRTCArgs) {
  const sendRef = useRef(sendWebRtcSignal);
  sendRef.current = sendWebRtcSignal;
  const localStreamRef = useRef(localStream);
  localStreamRef.current = localStream;
  const ownSessionIdRef = useRef(ownSessionId);
  ownSessionIdRef.current = ownSessionId;
  const pcsRef = useRef<Map<string, RTCPeerConnection>>(new Map());
  const [peers, setPeers] = useState<RemotePeer[]>([]);

  // Queue for operations deferred until localStream is available
  const pendingOpsRef = useRef<Array<() => Promise<void>>>([]);
  // Buffer for ICE candidates that arrive before their PC exists
  const pendingIceRef = useRef<Map<string, RTCIceCandidateInit[]>>(new Map());
  // Peers for whom we've sent or queued an outgoing offer
  const makingOfferRef = useRef<Set<string>>(new Set());
  // Peers for whom a queued offer should be dropped (we yielded to their offer)
  const cancelledOffersRef = useRef<Set<string>>(new Set());

  // Drain pending operations when localStream becomes available
  useEffect(() => {
    if (!localStream) return;
    const ops = [...pendingOpsRef.current];
    pendingOpsRef.current = [];
    if (ops.length > 0) {
      console.log("[WebRTC] draining", ops.length, "pending ops (localStream ready)");
      for (const op of ops) {
        op();
      }
    }
  }, [localStream]);

  // Helpers to update peers state
  const addRemotePeer = useCallback((connectionId: string, sessionId: string, stream: MediaStream) => {
    setPeers((prev) => {
      if (prev.some((p) => p.connectionId === connectionId)) return prev;
      return [...prev, { connectionId, sessionId, stream }];
    });
  }, []);

  const removeRemotePeer = useCallback((connectionId: string) => {
    setPeers((prev) => prev.filter((p) => p.connectionId !== connectionId));
  }, []);

  // Create an RTCPeerConnection for a given remote peer
  // IMPORTANT: callers must ensure localStreamRef.current is non-null before calling
  const createPc = useCallback(
    (remoteConnectionId: string, remoteSessionId: string): RTCPeerConnection => {
      const existing = pcsRef.current.get(remoteConnectionId);
      if (existing) {
        // Null handlers before close so stale events don't kill the replacement PC
        existing.onconnectionstatechange = null;
        existing.onicecandidate = null;
        existing.ontrack = null;
        existing.close();
        pcsRef.current.delete(remoteConnectionId);
      }

      const pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
      pcsRef.current.set(remoteConnectionId, pc);

      // Add local tracks — callers guarantee localStream is ready
      const stream = localStreamRef.current;
      if (stream) {
        stream.getTracks().forEach((track) => {
          pc.addTrack(track, stream);
        });
        console.log("[WebRTC] added", stream.getTracks().length, "local tracks to PC for", remoteConnectionId);
      } else {
        console.warn("[WebRTC] createPc called without localStream for", remoteConnectionId);
      }

      // Handle remote stream
      const remoteStream = new MediaStream();
      pc.ontrack = (evt) => {
        console.log("[WebRTC] ontrack from", remoteConnectionId, evt.track.kind);
        evt.streams[0]?.getTracks().forEach((t) => remoteStream.addTrack(t));
        if (!evt.streams[0]) {
          remoteStream.addTrack(evt.track);
        }
        addRemotePeer(remoteConnectionId, remoteSessionId, remoteStream);
      };

      // ICE candidates → relay to remote peer
      pc.onicecandidate = (evt) => {
        if (evt.candidate) {
          sendRef.current("ICE_CANDIDATE", remoteConnectionId, {
            candidate: evt.candidate.toJSON(),
          });
        }
      };

      pc.onconnectionstatechange = () => {
        console.log("[WebRTC] connectionState", remoteConnectionId, pc.connectionState);
        if (pc.connectionState === "failed" || pc.connectionState === "closed") {
          removePeer(remoteConnectionId);
        }
      };

      return pc;
    },
    [addRemotePeer],
  );

  // Initiate an offer to a remote peer (caller side)
  const startOffer = useCallback(
    async (peer: PeerInfo) => {
      const existingPc = pcsRef.current.get(peer.connectionId);
      if (existingPc?.connectionState === "connected") {
        console.log("[WebRTC] startOffer skipped — already connected to", peer.connectionId);
        return;
      }
      if (!localStreamRef.current) {
        console.log("[WebRTC] startOffer queued (waiting for localStream) →", peer.connectionId);
        makingOfferRef.current.add(peer.connectionId);
        pendingOpsRef.current.push(async () => {
          if (cancelledOffersRef.current.has(peer.connectionId)) {
            cancelledOffersRef.current.delete(peer.connectionId);
            makingOfferRef.current.delete(peer.connectionId);
            console.log("[WebRTC] startOffer cancelled (yielded) for", peer.connectionId);
            return;
          }
          const currentPc = pcsRef.current.get(peer.connectionId);
          if (currentPc?.connectionState === "connected") {
            makingOfferRef.current.delete(peer.connectionId);
            return;
          }
          console.log("[WebRTC] startOffer executing (deferred) →", peer.connectionId);
          const pc = createPc(peer.connectionId, peer.sessionId);
          const offer = await pc.createOffer();
          await pc.setLocalDescription(offer);
          sendRef.current("SDP_OFFER", peer.connectionId, { sdp: offer.sdp });
          makingOfferRef.current.delete(peer.connectionId);
        });
        return;
      }
      console.log("[WebRTC] startOffer →", peer.connectionId);
      makingOfferRef.current.add(peer.connectionId);
      const pc = createPc(peer.connectionId, peer.sessionId);
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      sendRef.current("SDP_OFFER", peer.connectionId, { sdp: offer.sdp });
      makingOfferRef.current.delete(peer.connectionId);
    },
    [createPc],
  );

  // Handle an incoming signaling message
  const handleSignal = useCallback(
    async (event: string, payload: SdpIceFromRelay) => {
      const remoteConnectionId = payload.from;
      const remoteSessionId = payload.fromSessionId;
      console.log("[WebRTC] handleSignal", event, "from", remoteConnectionId);

      if (event === "SDP_OFFER") {
        const existingPc = pcsRef.current.get(remoteConnectionId);
        if (existingPc?.connectionState === "connected") {
          console.log("[WebRTC] ignoring SDP_OFFER — already connected to", remoteConnectionId);
          return;
        }

        // Perfect negotiation: detect glare (both sides offered simultaneously)
        const collision =
          makingOfferRef.current.has(remoteConnectionId) ||
          (!!existingPc && existingPc.signalingState !== "stable");

        if (collision) {
          // Polite peer (larger sessionId) yields to the incoming offer.
          // Impolite peer (smaller sessionId) ignores the incoming offer and waits for its own answer.
          const isPolite = ownSessionIdRef.current > remoteSessionId;
          if (!isPolite) {
            console.log("[WebRTC] SDP_OFFER collision — impolite, ignoring offer from", remoteConnectionId);
            return;
          }
          console.log("[WebRTC] SDP_OFFER collision — polite, yielding to offer from", remoteConnectionId);
          cancelledOffersRef.current.add(remoteConnectionId);
          makingOfferRef.current.delete(remoteConnectionId);
          // createPc below will close the existing PC
        }

        // Need localStream before answering so tracks are present → sendrecv SDP
        if (!localStreamRef.current) {
          console.log("[WebRTC] SDP_OFFER queued (waiting for localStream)");
          pendingOpsRef.current.push(async () => {
            console.log("[WebRTC] SDP_OFFER executing (deferred) from", remoteConnectionId);
            const pc = createPc(remoteConnectionId, remoteSessionId);
            await pc.setRemoteDescription(
              new RTCSessionDescription({ type: "offer", sdp: payload.sdp! }),
            );
            // Flush any ICE candidates that arrived before this PC existed
            const buffered = pendingIceRef.current.get(remoteConnectionId);
            if (buffered) {
              pendingIceRef.current.delete(remoteConnectionId);
              for (const c of buffered) {
                await pc.addIceCandidate(new RTCIceCandidate(c));
              }
            }
            const answer = await pc.createAnswer();
            await pc.setLocalDescription(answer);
            sendRef.current("SDP_ANSWER", remoteConnectionId, { sdp: answer.sdp });
          });
          return;
        }
        const pc = createPc(remoteConnectionId, remoteSessionId);
        await pc.setRemoteDescription(
          new RTCSessionDescription({ type: "offer", sdp: payload.sdp! }),
        );
        // Flush any buffered ICE candidates
        const buffered = pendingIceRef.current.get(remoteConnectionId);
        if (buffered) {
          pendingIceRef.current.delete(remoteConnectionId);
          for (const c of buffered) {
            await pc.addIceCandidate(new RTCIceCandidate(c));
          }
        }
        const answer = await pc.createAnswer();
        await pc.setLocalDescription(answer);
        sendRef.current("SDP_ANSWER", remoteConnectionId, { sdp: answer.sdp });
      } else if (event === "SDP_ANSWER") {
        const pc = pcsRef.current.get(remoteConnectionId);
        // Only apply the answer when we are in the have-local-offer state.
        // Glare (both sides offered simultaneously) can leave the PC in stable
        // state already; applying a stale answer would throw.
        if (pc && pc.signalingState === "have-local-offer") {
          await pc.setRemoteDescription(
            new RTCSessionDescription({ type: "answer", sdp: payload.sdp! }),
          );
        }
      } else if (event === "ICE_CANDIDATE") {
        const pc = pcsRef.current.get(remoteConnectionId);
        if (pc && payload.candidate) {
          await pc.addIceCandidate(new RTCIceCandidate(payload.candidate));
        } else if (payload.candidate) {
          // Buffer until PC is created (e.g. during deferred SDP_OFFER processing)
          const arr = pendingIceRef.current.get(remoteConnectionId) || [];
          arr.push(payload.candidate);
          pendingIceRef.current.set(remoteConnectionId, arr);
          console.log("[WebRTC] buffered ICE candidate for", remoteConnectionId);
        }
      }
    },
    [createPc],
  );

  // Remove a peer and close its connection
  const removePeer = useCallback(
    (connectionId: string) => {
      const pc = pcsRef.current.get(connectionId);
      if (pc) {
        pc.close();
        pcsRef.current.delete(connectionId);
      }
      removeRemotePeer(connectionId);
    },
    [removeRemotePeer],
  );

  // Tear down all connections (used when leaving the session)
  const cleanup = useCallback(() => {
    pcsRef.current.forEach((pc) => pc.close());
    pcsRef.current.clear();
    pendingOpsRef.current = [];
    pendingIceRef.current.clear();
    makingOfferRef.current.clear();
    cancelledOffersRef.current.clear();
    setPeers([]);
  }, []);

  return { peers, startOffer, handleSignal, removePeer, cleanup };
}
