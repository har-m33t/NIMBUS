'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');

const { Peer } = require('../src/peer');
const {
  fakeWs,
  fakeProducer,
  fakeConsumer,
  fakeTransport,
} = require('./helpers');

test('Peer generates a UUID and retains room/session', () => {
  const peer = new Peer(fakeWs(), 'room-42', 'session-abc');
  assert.match(peer.id, /^[0-9a-f-]{36}$/);
  assert.equal(peer.roomId, 'room-42');
  assert.equal(peer.sessionId, 'session-abc');
  assert.equal(peer.closed, false);
  assert.equal(peer.producers.size, 0);
  assert.equal(peer.consumers.size, 0);
});

test('send() writes JSON when socket is open', () => {
  const ws = fakeWs();
  const peer = new Peer(ws, 'room-42', 'session-abc');
  peer.send({ type: 'HELLO', payload: { n: 1 } });
  assert.equal(ws._state.sent.length, 1);
  assert.deepEqual(JSON.parse(ws._state.sent[0]), {
    type: 'HELLO',
    payload: { n: 1 },
  });
});

test('send() is a no-op after close()', () => {
  const ws = fakeWs();
  const peer = new Peer(ws, 'room', 'sess');
  peer.close();
  peer.send({ type: 'LATE' });
  assert.equal(ws._state.sent.length, 0);
});

test('send() is a no-op when readyState is not OPEN', () => {
  const ws = fakeWs({ readyState: 0 /* CONNECTING */ });
  const peer = new Peer(ws, 'room', 'sess');
  peer.send({ type: 'EARLY' });
  assert.equal(ws._state.sent.length, 0);
});

test('send() swallows ws.send errors so one bad peer does not crash the room', () => {
  const ws = fakeWs({
    send: () => {
      throw new Error('network down');
    },
  });
  const peer = new Peer(ws, 'room', 'sess');
  assert.doesNotThrow(() => peer.send({ type: 'HI' }));
});

test('trackProducer stores by id and removes on transportclose', () => {
  const peer = new Peer(fakeWs(), 'room', 'sess');
  const producer = fakeProducer('p-1');
  peer.trackProducer(producer);
  assert.equal(peer.producers.get('p-1'), producer);

  producer.emit('transportclose');
  assert.equal(peer.producers.has('p-1'), false);
});

test('trackConsumer removes on transportclose and producerclose', () => {
  const peer = new Peer(fakeWs(), 'room', 'sess');
  const c1 = fakeConsumer('c-1');
  const c2 = fakeConsumer('c-2');
  peer.trackConsumer(c1);
  peer.trackConsumer(c2);

  c1.emit('transportclose');
  c2.emit('producerclose');
  assert.equal(peer.consumers.size, 0);
});

test('close() closes producers, consumers, and transports', () => {
  const peer = new Peer(fakeWs(), 'room', 'sess');
  const producer = fakeProducer('p-1');
  const consumer = fakeConsumer('c-1');
  const sendTransport = fakeTransport();
  const recvTransport = fakeTransport();

  peer.trackProducer(producer);
  peer.trackConsumer(consumer);
  peer.sendTransport = sendTransport;
  peer.recvTransport = recvTransport;

  peer.close();

  assert.equal(peer.closed, true);
  assert.equal(producer.closed, true);
  assert.equal(consumer.closed, true);
  assert.equal(sendTransport.closed, true);
  assert.equal(recvTransport.closed, true);
});

test('close() is idempotent', () => {
  const ws = fakeWs();
  const peer = new Peer(ws, 'room', 'sess');
  peer.close();
  // Second close must not throw even though ws.close already flipped state.
  assert.doesNotThrow(() => peer.close());
  assert.equal(peer.closed, true);
});
