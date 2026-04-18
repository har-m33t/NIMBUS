'use strict';

const { randomUUID } = require('crypto');

/**
 * A Peer is one browser client joined to a Room. It owns its WebSocket, its
 * send/recv WebRtcTransports, its Producers, and its Consumers.
 *
 * Signaling messages (PROTOCOLS.md §1.2):
 *   Client → Server:  SDP_OFFER, SDP_ANSWER, ICE_CANDIDATE, RPC methods below
 *   Server → Client:  NEW_PRODUCER, PRODUCER_CLOSED, PEER_LEFT
 *
 * SDP_OFFER / SDP_ANSWER / ICE_CANDIDATE are the spec-level event names from
 * PROTOCOLS.md; under the hood they map to mediasoup's transport.connect +
 * produce RPCs. The server dispatcher (server.js) handles that translation.
 */
class Peer {
  constructor(ws, roomId, sessionId) {
    this.id = randomUUID();
    this.ws = ws;
    this.roomId = roomId;
    this.sessionId = sessionId;
    this.sendTransport = null;
    this.recvTransport = null;
    this.producers = new Map(); // producerId -> Producer
    this.consumers = new Map(); // consumerId -> Consumer
    this.closed = false;
  }

  send(message) {
    if (this.closed || this.ws.readyState !== this.ws.OPEN) return;
    try {
      this.ws.send(JSON.stringify(message));
    } catch (err) {
      console.error(`[peer ${this.id}] send failed`, err);
    }
  }

  trackProducer(producer) {
    this.producers.set(producer.id, producer);
    producer.on('transportclose', () => this.producers.delete(producer.id));
  }

  trackConsumer(consumer) {
    this.consumers.set(consumer.id, consumer);
    consumer.on('transportclose', () => this.consumers.delete(consumer.id));
    consumer.on('producerclose', () => this.consumers.delete(consumer.id));
  }

  close() {
    if (this.closed) return;
    this.closed = true;
    for (const producer of this.producers.values()) producer.close();
    for (const consumer of this.consumers.values()) consumer.close();
    if (this.sendTransport) this.sendTransport.close();
    if (this.recvTransport) this.recvTransport.close();
    try {
      this.ws.close();
    } catch {
      // already closed
    }
  }
}

module.exports = { Peer };
