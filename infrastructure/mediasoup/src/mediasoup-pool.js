'use strict';

const mediasoup = require('mediasoup');
const config = require('./config');

let workers = [];
let nextWorkerIdx = 0;

async function createWorkers() {
  const count = config.worker.numWorkers;
  for (let i = 0; i < count; i += 1) {
    const worker = await mediasoup.createWorker({
      logLevel: config.worker.logLevel,
      logTags: config.worker.logTags,
      rtcMinPort: config.worker.rtcMinPort,
      rtcMaxPort: config.worker.rtcMaxPort,
    });
    worker.on('died', (error) => {
      console.error(`[mediasoup] worker ${worker.pid} died:`, error);
      setTimeout(() => process.exit(1), 2000);
    });
    workers.push(worker);
  }
  console.log(`[mediasoup] spawned ${workers.length} worker(s)`);
}

function pickWorker() {
  if (!workers.length) throw new Error('mediasoup workers not initialised');
  const worker = workers[nextWorkerIdx];
  nextWorkerIdx = (nextWorkerIdx + 1) % workers.length;
  return worker;
}

async function createRouter() {
  const worker = pickWorker();
  return worker.createRouter({ mediaCodecs: config.router.mediaCodecs });
}

module.exports = { createWorkers, createRouter };
