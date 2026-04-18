'use strict';

/**
 * Minimal stand-ins for the bits of `ws` and `mediasoup` that room.js / peer.js
 * actually call. Keeps unit tests off the native mediasoup worker entirely.
 */

function fakeWs(overrides = {}) {
  const state = {
    sent: [],
    closed: false,
    readyState: 1, // WebSocket.OPEN
    OPEN: 1,
    CLOSED: 3,
  };
  const ws = {
    get readyState() {
      return state.readyState;
    },
    OPEN: 1,
    CLOSED: 3,
    send(data) {
      state.sent.push(data);
    },
    close() {
      state.closed = true;
      state.readyState = 3;
    },
    ...overrides,
  };
  ws._state = state;
  return ws;
}

function fakeRouter() {
  const observer = {
    _handlers: {},
    on(event, cb) {
      this._handlers[event] = cb;
    },
    emit(event, ...args) {
      if (this._handlers[event]) this._handlers[event](...args);
    },
  };
  return {
    rtpCapabilities: { codecs: [], headerExtensions: [] },
    observer,
    closed: false,
    close() {
      this.closed = true;
      observer.emit('close');
    },
    createWebRtcTransport: async () => ({
      id: `transport-${Math.random().toString(36).slice(2, 8)}`,
      iceParameters: {},
      iceCandidates: [],
      dtlsParameters: {},
      closed: false,
      async connect() {},
      async produce() {
        return { id: 'producer-1', kind: 'video', on() {}, close() {} };
      },
      async consume() {
        return {
          id: 'consumer-1',
          producerId: 'producer-1',
          kind: 'video',
          rtpParameters: {},
          on() {},
          close() {},
        };
      },
      async setMaxIncomingBitrate() {},
      close() {
        this.closed = true;
      },
    }),
  };
}

function fakeProducer(id = 'producer-1', kind = 'video') {
  const listeners = {};
  return {
    id,
    kind,
    closed: false,
    on(event, cb) {
      listeners[event] = cb;
    },
    emit(event) {
      if (listeners[event]) listeners[event]();
    },
    close() {
      this.closed = true;
    },
  };
}

function fakeConsumer(id = 'consumer-1') {
  const listeners = {};
  return {
    id,
    closed: false,
    on(event, cb) {
      listeners[event] = cb;
    },
    emit(event) {
      if (listeners[event]) listeners[event]();
    },
    close() {
      this.closed = true;
    },
  };
}

function fakeTransport() {
  return {
    id: 'transport-1',
    closed: false,
    close() {
      this.closed = true;
    },
  };
}

/**
 * Pre-seed the require cache so `require('../src/room')` doesn't pull in the
 * real mediasoup-pool (which would try to spawn native workers).
 */
function stubMediasoupPool({ createRouter } = {}) {
  const modulePath = require.resolve('../src/mediasoup-pool');
  require.cache[modulePath] = {
    id: modulePath,
    filename: modulePath,
    loaded: true,
    exports: {
      createWorkers: async () => {},
      createRouter: createRouter || (async () => fakeRouter()),
    },
  };
}

module.exports = {
  fakeWs,
  fakeRouter,
  fakeProducer,
  fakeConsumer,
  fakeTransport,
  stubMediasoupPool,
};
