# NIMBUS Mediasoup SFU

Multi-party WebRTC routing for NIMBUS. Runs on the EC2 host provisioned by
`backend/template.yaml` (`NIMBUS_PROD_Mediasoup*` resources).

## Layout

```
src/
  server.js          HTTPS + WSS entrypoint, request dispatcher
  mediasoup-pool.js  Worker pool (one per core - 1)
  room.js            Router + peer registry per roomId
  peer.js            Per-connection state (transports, producers, consumers)
  config.js          Ports, codecs, announced IP, TLS paths
```

## Signaling protocol

Single WSS connection per peer. Connect URL:

```
wss://<eip>:443/?roomId=<room>&sessionId=<uuid-v4>
```

On connect the server sends `WELCOME` with `router.rtpCapabilities` and the
list of existing peers/producers. All client → server messages carry an
optional `requestId` that the server echoes in the `<type>_RESULT` reply.

| Client → Server        | Purpose |
|------------------------|---------|
| `CREATE_SEND_TRANSPORT` | Get a WebRtcTransport for publishing |
| `CREATE_RECV_TRANSPORT` | Get a WebRtcTransport for subscribing |
| `SDP_ANSWER` / `CONNECT_TRANSPORT` | Complete DTLS handshake |
| `ICE_CANDIDATE`        | Trickle ICE (accepted for protocol parity) |
| `SDP_OFFER` / `PRODUCE` | Publish an audio or video track |
| `CONSUME`              | Subscribe to another peer's producer |
| `CLOSE_PRODUCER`       | Stop publishing |

| Server → Client  | Purpose |
|------------------|---------|
| `WELCOME`        | Room joined; includes router caps |
| `NEW_PRODUCER`   | A peer started publishing |
| `PRODUCER_CLOSED` | A publish ended |
| `PEER_LEFT`      | A peer disconnected |
| `ERROR`          | Dispatch failure |

## Environment variables

| Var | Default | Notes |
|---|---|---|
| `WSS_PORT` | `443` | TLS signaling port |
| `TLS_CERT_PATH` | `/etc/nimbus/tls/fullchain.pem` | Provision via ACM/LetsEncrypt |
| `TLS_KEY_PATH`  | `/etc/nimbus/tls/privkey.pem` | |
| `MEDIASOUP_MIN_PORT` / `MEDIASOUP_MAX_PORT` | `40000` / `49999` | Must match SG ingress |
| `MEDIASOUP_ANNOUNCED_IP` | (unset) | Set to the Elastic IP before starting |
| `MEDIASOUP_WORKERS` | `cpus - 1` | One mediasoup Worker per core |
| `TURN_PARAMETER` | `NIMBUS_PROD_TURNConfig` | SSM parameter with iceServers |
| `AWS_REGION` | `us-east-1` | For SSM SDK |

## Deploy

The CloudFormation stack (SAM) provisions the EC2 host, EIP, security group,
systemd unit, and CloudWatch log group. After `sam deploy`:

1. Copy this directory to the instance:
   ```
   rsync -av infrastructure/mediasoup/ ec2-user@<eip>:/opt/nimbus-mediasoup/
   ```
2. Install dependencies:
   ```
   ssh ec2-user@<eip> 'cd /opt/nimbus-mediasoup && npm ci --omit=dev'
   ```
3. Place TLS cert + key at the paths above (or override via env vars).
4. Update the stack with `MediasoupAnnouncedIp=<eip>` so the systemd unit
   advertises the right IP in ICE candidates, then:
   ```
   ssh ec2-user@<eip> 'sudo systemctl restart nimbus-mediasoup'
   ```
5. Tail logs:
   ```
   aws logs tail /ec2/nimbus-prod/mediasoup --follow
   ```

## Tests

```
npm test
```

Runs `node --test` over `test/peer.test.js` and `test/room.test.js`. The
suite stubs `mediasoup-pool.js` via the require cache so no native mediasoup
workers are spawned — unit coverage is limited to `Peer`, `Room`, and
`RoomRegistry` behavior. Live WebRTC negotiation is out of scope for unit
tests and must be validated against a deployed SFU.
