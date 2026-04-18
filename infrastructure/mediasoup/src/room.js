'use strict';

const { createRouter } = require('./mediasoup-pool');
const config = require('./config');

/**
 * A Room owns one mediasoup Router. Peers join via a WebSocket; each peer has
 * one send transport and one recv transport. Producers (mic/cam tracks) are
 * fanned out to every other peer's recv transport as Consumers.
 */
class Room {
  constructor(roomId) {
    this.roomId = roomId;
    this.router = null;
    this.peers = new Map(); // peerId -> Peer
    this.closed = false;
  }

  static async create(roomId) {
    const room = new Room(roomId);
    room.router = await createRouter();
    return room;
  }

  addPeer(peer) {
    this.peers.set(peer.id, peer);
  }

  removePeer(peerId) {
    const peer = this.peers.get(peerId);
    if (!peer) return;
    peer.close();
    this.peers.delete(peerId);
    this._broadcast({ type: 'PEER_LEFT', payload: { peerId } }, peerId);
    if (this.peers.size === 0) this.close();
  }

  otherPeers(peerId) {
    return [...this.peers.values()].filter((p) => p.id !== peerId);
  }

  _broadcast(message, excludePeerId = null) {
    for (const peer of this.peers.values()) {
      if (peer.id === excludePeerId) continue;
      peer.send(message);
    }
  }

  async createWebRtcTransport() {
    const transport = await this.router.createWebRtcTransport(config.webRtcTransport);
    if (config.webRtcTransport.maxIncomingBitrate) {
      try {
        await transport.setMaxIncomingBitrate(config.webRtcTransport.maxIncomingBitrate);
      } catch {
        // non-fatal
      }
    }
    return transport;
  }

  announceProducer(peerId, producer) {
    this._broadcast(
      {
        type: 'NEW_PRODUCER',
        payload: { peerId, producerId: producer.id, kind: producer.kind },
      },
      peerId,
    );
  }

  announceProducerClosed(peerId, producerId) {
    this._broadcast(
      { type: 'PRODUCER_CLOSED', payload: { peerId, producerId } },
      peerId,
    );
  }

  close() {
    if (this.closed) return;
    this.closed = true;
    for (const peer of this.peers.values()) peer.close();
    this.peers.clear();
    if (this.router) this.router.close();
  }
}

class RoomRegistry {
  constructor() {
    this.rooms = new Map();
  }

  async getOrCreate(roomId) {
    let room = this.rooms.get(roomId);
    if (room && !room.closed) return room;
    room = await Room.create(roomId);
    this.rooms.set(roomId, room);
    room.router.observer.on('close', () => this.rooms.delete(roomId));
    console.log(`[room] created ${roomId}`);
    return room;
  }

  get(roomId) {
    return this.rooms.get(roomId);
  }
}

module.exports = { Room, RoomRegistry };
