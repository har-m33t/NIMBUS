'use strict';

const os = require('os');

const num = (value, fallback) => {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
};

// PROTOCOLS.md §5.6 — media UDP range 40000-49999, signaling WSS on 443.
module.exports = {
  wssPort: num(process.env.WSS_PORT, 443),
  tlsCertPath: process.env.TLS_CERT_PATH || '/etc/nimbus/tls/fullchain.pem',
  tlsKeyPath: process.env.TLS_KEY_PATH || '/etc/nimbus/tls/privkey.pem',

  worker: {
    rtcMinPort: num(process.env.MEDIASOUP_MIN_PORT, 40000),
    rtcMaxPort: num(process.env.MEDIASOUP_MAX_PORT, 49999),
    logLevel: process.env.MEDIASOUP_LOG_LEVEL || 'warn',
    logTags: ['info', 'ice', 'dtls', 'rtp', 'srtp', 'rtcp'],
    numWorkers: num(process.env.MEDIASOUP_WORKERS, Math.max(1, os.cpus().length - 1)),
  },

  router: {
    mediaCodecs: [
      {
        kind: 'audio',
        mimeType: 'audio/opus',
        clockRate: 48000,
        channels: 2,
      },
      {
        kind: 'video',
        mimeType: 'video/VP8',
        clockRate: 90000,
        parameters: { 'x-google-start-bitrate': 1000 },
      },
      {
        kind: 'video',
        mimeType: 'video/H264',
        clockRate: 90000,
        parameters: {
          'packetization-mode': 1,
          'profile-level-id': '42e01f',
          'level-asymmetry-allowed': 1,
        },
      },
    ],
  },

  webRtcTransport: {
    listenIps: [
      {
        ip: '0.0.0.0',
        announcedIp: process.env.MEDIASOUP_ANNOUNCED_IP || null,
      },
    ],
    initialAvailableOutgoingBitrate: 1_000_000,
    maxIncomingBitrate: 1_500_000,
    enableUdp: true,
    enableTcp: true,
    preferUdp: true,
  },

  turnParameterName: process.env.TURN_PARAMETER || 'NIMBUS_PROD_TURNConfig',
  awsRegion: process.env.AWS_REGION || 'us-east-1',
};
