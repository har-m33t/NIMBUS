'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');

const { stubMediasoupPool, fakeRouter, fakeWs, fakeProducer } = require('./helpers');

// Seed the require cache before pulling in room.js so the native mediasoup
// worker is never spawned during tests.
stubMediasoupPool();

const { Room, RoomRegistry } = require('../src/room');
const { Peer } = require('../src/peer');

function peerWithCapturedSends(roomId) {
  const ws = fakeWs();
  const peer = new Peer(ws, roomId, 'session');
  return { peer, ws };
}

test('Room.create attaches a router', async () => {
  const room = await Room.create('r');
  assert.ok(room.router, 'router was assigned');
  assert.equal(room.roomId, 'r');
  assert.equal(room.peers.size, 0);
});

test('addPeer / removePeer maintain the peer set', async () => {
  const room = await Room.create('r');
  const { peer: p1 } = peerWithCapturedSends('r');
  const { peer: p2 } = peerWithCapturedSends('r');

  room.addPeer(p1);
  room.addPeer(p2);
  assert.equal(room.peers.size, 2);

  room.removePeer(p1.id);
  assert.equal(room.peers.size, 1);
  assert.equal(p1.closed, true, 'removed peer is closed');
});

test('otherPeers excludes the caller', async () => {
  const room = await Room.create('r');
  const { peer: p1 } = peerWithCapturedSends('r');
  const { peer: p2 } = peerWithCapturedSends('r');
  room.addPeer(p1);
  room.addPeer(p2);

  const others = room.otherPeers(p1.id);
  assert.equal(others.length, 1);
  assert.equal(others[0].id, p2.id);
});

test('removePeer broadcasts PEER_LEFT to remaining peers only', async () => {
  const room = await Room.create('r');
  const a = peerWithCapturedSends('r');
  const b = peerWithCapturedSends('r');
  const c = peerWithCapturedSends('r');
  room.addPeer(a.peer);
  room.addPeer(b.peer);
  room.addPeer(c.peer);

  room.removePeer(b.peer.id);

  // b was closed, so only a and c should have received PEER_LEFT.
  const messages = [
    ...a.ws._state.sent.map(JSON.parse),
    ...c.ws._state.sent.map(JSON.parse),
  ];
  const peerLeft = messages.filter((m) => m.type === 'PEER_LEFT');
  assert.equal(peerLeft.length, 2);
  assert.ok(peerLeft.every((m) => m.payload.peerId === b.peer.id));

  // b's socket must not receive its own PEER_LEFT.
  const bMessages = b.ws._state.sent.map(JSON.parse);
  assert.equal(bMessages.filter((m) => m.type === 'PEER_LEFT').length, 0);
});

test('removePeer of unknown id is a no-op', async () => {
  const room = await Room.create('r');
  assert.doesNotThrow(() => room.removePeer('nope'));
});

test('removing the last peer closes the room', async () => {
  const room = await Room.create('r');
  const { peer } = peerWithCapturedSends('r');
  room.addPeer(peer);
  room.removePeer(peer.id);
  assert.equal(room.closed, true);
  assert.equal(room.router.closed, true);
});

test('announceProducer notifies peers other than the publisher', async () => {
  const room = await Room.create('r');
  const pub = peerWithCapturedSends('r');
  const sub = peerWithCapturedSends('r');
  room.addPeer(pub.peer);
  room.addPeer(sub.peer);

  const producer = fakeProducer('p-1', 'video');
  room.announceProducer(pub.peer.id, producer);

  const subMsgs = sub.ws._state.sent.map(JSON.parse);
  const pubMsgs = pub.ws._state.sent.map(JSON.parse);
  assert.equal(subMsgs.filter((m) => m.type === 'NEW_PRODUCER').length, 1);
  assert.equal(pubMsgs.filter((m) => m.type === 'NEW_PRODUCER').length, 0);

  const evt = subMsgs.find((m) => m.type === 'NEW_PRODUCER');
  assert.deepEqual(evt.payload, {
    peerId: pub.peer.id,
    producerId: 'p-1',
    kind: 'video',
  });
});

test('announceProducerClosed fans out PRODUCER_CLOSED', async () => {
  const room = await Room.create('r');
  const pub = peerWithCapturedSends('r');
  const sub = peerWithCapturedSends('r');
  room.addPeer(pub.peer);
  room.addPeer(sub.peer);

  room.announceProducerClosed(pub.peer.id, 'p-1');
  const subMsgs = sub.ws._state.sent.map(JSON.parse);
  const closed = subMsgs.find((m) => m.type === 'PRODUCER_CLOSED');
  assert.ok(closed);
  assert.equal(closed.payload.producerId, 'p-1');
});

test('close() cascades to peers and router', async () => {
  const room = await Room.create('r');
  const { peer } = peerWithCapturedSends('r');
  room.addPeer(peer);

  room.close();

  assert.equal(room.closed, true);
  assert.equal(peer.closed, true);
  assert.equal(room.router.closed, true);
  assert.equal(room.peers.size, 0);
});

test('RoomRegistry.getOrCreate reuses existing rooms', async () => {
  const reg = new RoomRegistry();
  const r1 = await reg.getOrCreate('r');
  const r2 = await reg.getOrCreate('r');
  assert.equal(r1, r2);
});

test('RoomRegistry drops the room when the router emits close', async () => {
  const reg = new RoomRegistry();
  const room = await reg.getOrCreate('r');
  assert.equal(reg.get('r'), room);

  room.router.observer.emit('close');

  assert.equal(reg.get('r'), undefined);
});

test('RoomRegistry.getOrCreate creates a new room after a previous one closed', async () => {
  const reg = new RoomRegistry();
  const first = await reg.getOrCreate('r');
  first.close(); // cascades to router.close → observer 'close' → registry drops 'r'

  const second = await reg.getOrCreate('r');
  assert.notEqual(first, second);
  assert.equal(second.closed, false);
});
