'use strict';

const fs = require('fs');
const https = require('https');
const { URL } = require('url');
const { WebSocketServer } = require('ws');

const config = require('./config');
const { createWorkers } = require('./mediasoup-pool');
const { RoomRegistry } = require('./room');
const { Peer } = require('./peer');

const rooms = new RoomRegistry();

async function bootstrap() {
  await createWorkers();

  const server = https.createServer({
    cert: fs.readFileSync(config.tlsCertPath),
    key: fs.readFileSync(config.tlsKeyPath),
  });

  const wss = new WebSocketServer({ server, path: '/' });
  wss.on('connection', handleConnection);

  server.listen(config.wssPort, () => {
    console.log(`[signaling] WSS listening on :${config.wssPort}`);
  });
}

function handleConnection(ws, request) {
  const url = new URL(request.url, 'https://placeholder');
  const roomId = url.searchParams.get('roomId');
  const sessionId = url.searchParams.get('sessionId');

  if (!roomId || !sessionId) {
    ws.close(4400, 'roomId and sessionId query params are required');
    return;
  }

  let peer;
  rooms.getOrCreate(roomId).then((room) => {
    peer = new Peer(ws, roomId, sessionId);
    room.addPeer(peer);
    peer.send({
      type: 'WELCOME',
      payload: {
        peerId: peer.id,
        rtpCapabilities: room.router.rtpCapabilities,
        existingPeers: room.otherPeers(peer.id).map((p) => ({
          peerId: p.id,
          producers: [...p.producers.values()].map((pr) => ({
            producerId: pr.id,
            kind: pr.kind,
          })),
        })),
      },
    });
  }).catch((err) => {
    console.error('[signaling] room init failed', err);
    ws.close(1011, 'room init failed');
  });

  ws.on('message', async (raw) => {
    if (!peer) return; // room still spinning up; client must wait for WELCOME
    let msg;
    try {
      msg = JSON.parse(raw.toString());
    } catch {
      peer.send({ type: 'ERROR', payload: { code: 'BAD_JSON' } });
      return;
    }
    try {
      await dispatch(peer, msg);
    } catch (err) {
      console.error(`[peer ${peer.id}] dispatch failed`, err);
      peer.send({
        type: 'ERROR',
        requestId: msg.requestId,
        payload: { code: 'INTERNAL', message: String(err.message || err) },
      });
    }
  });

  ws.on('close', () => {
    if (!peer) return;
    const room = rooms.get(peer.roomId);
    if (room) room.removePeer(peer.id);
  });
}

async function dispatch(peer, msg) {
  const room = rooms.get(peer.roomId);
  if (!room) throw new Error('room not found');

  switch (msg.type) {
    case 'CREATE_SEND_TRANSPORT':
    case 'CREATE_RECV_TRANSPORT': {
      const transport = await room.createWebRtcTransport();
      if (msg.type === 'CREATE_SEND_TRANSPORT') peer.sendTransport = transport;
      else peer.recvTransport = transport;
      return reply(peer, msg, {
        transportId: transport.id,
        iceParameters: transport.iceParameters,
        iceCandidates: transport.iceCandidates,
        dtlsParameters: transport.dtlsParameters,
      });
    }

    // Client has completed its DTLS handshake (equivalent to SDP_ANSWER in
    // the high-level protocol — mediasoup consumes dtlsParameters directly).
    case 'SDP_ANSWER':
    case 'CONNECT_TRANSPORT': {
      const transport = resolveTransport(peer, msg.payload.transportId);
      await transport.connect({ dtlsParameters: msg.payload.dtlsParameters });
      return reply(peer, msg, { connected: true });
    }

    // Trickle ICE candidate — mediasoup auto-selects during connect, so this
    // is accepted for protocol parity and logged.
    case 'ICE_CANDIDATE': {
      console.log(`[peer ${peer.id}] ICE candidate received (noop)`);
      return reply(peer, msg, { accepted: true });
    }

    // Client wants to publish a track. `SDP_OFFER` is the spec-level name; the
    // payload carries RTP parameters that mediasoup uses directly.
    case 'SDP_OFFER':
    case 'PRODUCE': {
      if (!peer.sendTransport) throw new Error('send transport not created');
      const producer = await peer.sendTransport.produce({
        kind: msg.payload.kind,
        rtpParameters: msg.payload.rtpParameters,
        appData: { peerId: peer.id },
      });
      peer.trackProducer(producer);
      producer.on('transportclose', () => room.announceProducerClosed(peer.id, producer.id));
      room.announceProducer(peer.id, producer);
      return reply(peer, msg, { producerId: producer.id });
    }

    case 'CONSUME': {
      if (!peer.recvTransport) throw new Error('recv transport not created');
      const { producerId, rtpCapabilities } = msg.payload;
      if (!room.router.canConsume({ producerId, rtpCapabilities })) {
        throw new Error('cannot consume producer');
      }
      const consumer = await peer.recvTransport.consume({
        producerId,
        rtpCapabilities,
        paused: false,
      });
      peer.trackConsumer(consumer);
      return reply(peer, msg, {
        consumerId: consumer.id,
        producerId: consumer.producerId,
        kind: consumer.kind,
        rtpParameters: consumer.rtpParameters,
      });
    }

    case 'CLOSE_PRODUCER': {
      const producer = peer.producers.get(msg.payload.producerId);
      if (producer) {
        producer.close();
        peer.producers.delete(producer.id);
        room.announceProducerClosed(peer.id, producer.id);
      }
      return reply(peer, msg, { closed: true });
    }

    default:
      throw new Error(`unknown message type: ${msg.type}`);
  }
}

function resolveTransport(peer, transportId) {
  if (peer.sendTransport && peer.sendTransport.id === transportId) return peer.sendTransport;
  if (peer.recvTransport && peer.recvTransport.id === transportId) return peer.recvTransport;
  throw new Error(`transport ${transportId} not found`);
}

function reply(peer, request, payload) {
  peer.send({
    type: `${request.type}_RESULT`,
    requestId: request.requestId || null,
    payload,
  });
}

bootstrap().catch((err) => {
  console.error('[mediasoup] bootstrap failed', err);
  process.exit(1);
});
