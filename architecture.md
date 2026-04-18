# NIMBUS — AWS Architecture Reference
> Aligned with PROTOCOLS.md (canonical). All resource names use the `NIMBUS_PROD_` prefix.
> Last updated: 2026-04-18

---

## Data Flow Overview

```
Browser (OpenCV + MediaPipe)
  │  10 FPS keypoints (258 floats/frame)
  │  face crop JPEG every 10th frame
  ▼
API Gateway WebSocket ──────────────────────────────────────────────────────┐
  │  INFER action                                                            │
  ▼                                                                          │
NIMBUS_PROD_ProcessFrame (Lambda)                                            │
  ├─► SageMaker nimbus-prod-asl-endpoint  →  gloss tokens + confidence      │
  ├─► DynamoDB NIMBUS_PROD_Sessions       →  glossBuffer, lastEmotion       │
  ├─► (on boundary flush) Bedrock Claude  →  English sentence               │
  ├─► (parallel, on face crop) Rekognition → emotion label                  │
  └─► Polly + S3 nimbus-prod-tts-audio    →  pre-signed MP3 URL            │
  │                                                                          │
  └─► WebSocket events (GLOSS, EMOTION, CAPTION, ERROR) ───────────────────►│
                                                                             │
NIMBUS_PROD_BroadcastCaption (Lambda) ◄──────────────────────────────────────┘
  └─► API Gateway Management API → all room connectionIds in NIMBUS_PROD_Rooms

EC2 mediasoup SFU (parallel, independent)
  Browser ◄──────────────────────────────── WebRTC video/audio relay
```

---

## AWS Services

### Amazon API Gateway v2 (WebSocket)
Routes all AI pipeline traffic between browser clients and Lambda. Manages WebSocket connections, assigns `connectionId` values, and routes `$connect`/`$disconnect`/`INFER` actions to the corresponding Lambda functions. Also used post-inference to push events back to clients via the Management API. **Failure mode:** if API Gateway is unavailable, clients cannot reach the AI pipeline at all — the frontend falls back to the 5-second offline timer and displays the gray signal indicator. No ASL interpretation is possible until connectivity is restored.

### AWS Lambda
Five functions handle all server-side logic with no persistent compute. `NIMBUS_PROD_WS_Connect` and `NIMBUS_PROD_WS_Disconnect` manage session registration in DynamoDB. `NIMBUS_PROD_ProcessFrame` orchestrates the full AI pipeline on every keypoint frame: SageMaker → Bedrock → Rekognition → Polly, emitting WebSocket events at each stage. `NIMBUS_PROD_BroadcastCaption` fan-outs final captions to all room participants. `NIMBUS_PROD_WarmEndpoint` runs on a schedule to eliminate SageMaker cold starts. **Failure mode:** Lambda errors emit `ERROR` WebSocket events with defined fallback values per service (see PROTOCOLS.md §4.1); silent failures are prohibited.

### Amazon SageMaker (Inference Endpoint)
Hosts the trained ASL Transformer model at endpoint `nimbus-prod-asl-endpoint` on an `ml.g5.xlarge` GPU instance. Accepts a `(1, T, 258)` float tensor and returns ordered gloss token strings with a confidence score. The `NIMBUS_PROD_WarmEndpoint` Lambda pings the endpoint on a schedule to prevent 30–90 second cold starts. **Failure mode:** Lambda catches non-200 responses and emits `glossFallback: "[UNKNOWN_SIGN]"` to the client; inference is skipped for that frame.

### Amazon DynamoDB
Two tables handle persistent state. `NIMBUS_PROD_Sessions` stores per-session gloss buffers, emotion state, caption history (for Bedrock context), and WebSocket connection IDs, with a 4-hour TTL. `NIMBUS_PROD_Rooms` maps `roomId` to active `connectionId`s for caption broadcast fan-out. `NIMBUS_PROD_Vocabulary` stores ASL vocabulary metadata. `NIMBUS_PROD_UserPreferences` stores per-user UI settings. **Failure mode:** DynamoDB unavailability blocks session writes; the ProcessFrame Lambda emits an `ERROR` event and cannot accumulate gloss buffers or broadcast captions.

### Amazon Bedrock (Claude)
Invoked by `NIMBUS_PROD_ProcessFrame` on each gloss-buffer flush to translate raw ASL gloss tokens into a grammatically correct English sentence. The prompt includes the current token buffer, the current emotion label, and the last 3 captions retrieved from DynamoDB for contextual continuity. **Failure mode:** on timeout or API error, Lambda returns the raw gloss token string as the caption text (no English translation), and Polly is still invoked with that fallback text.

### Amazon Rekognition
Called in parallel with SageMaker inference, once every 10 frames (≈1 second), when `includeFaceCrop: true`. Accepts a base64-encoded JPEG face crop (max 640×480 px) and returns emotion labels with confidence scores. The detected emotion is stored in DynamoDB `lastEmotion` and used to modulate Polly SSML prosody. **Failure mode:** Lambda defaults `lastEmotion` to `"CALM"` and continues silently; no `ERROR` event is emitted for Rekognition failures.

### Amazon Polly
Converts the Bedrock-generated English sentence to speech using SSML prosody parameters read from `nimbus-prod-config/ssml_prosody_map.json`. The MP3 output is stored in `nimbus-prod-tts-audio` and delivered to the client as a pre-signed S3 URL inside the `CAPTION` event. The client plays the audio via a virtual audio device routed into Zoom. **Failure mode:** the `CAPTION` event is still delivered with the full text; `audioUrl` is omitted and the frontend audio indicator turns gray.

### Amazon S3
Four buckets serve distinct roles: `nimbus-prod-model-artifacts` stores trained model tarballs and SageMaker model data; `nimbus-prod-tts-audio` stores generated MP3 files served via pre-signed URLs; `nimbus-prod-config` stores `ssml_prosody_map.json` (read once per Lambda cold start, cached in memory); `nimbus-prod-session-exports` stores session data exports for analytics. **Failure mode:** `nimbus-prod-config` unavailability prevents prosody config from loading at cold start — Lambda should cache a hardcoded default prosody map as fallback.

### AWS Systems Manager Parameter Store
Stores TURN server credentials (`/nimbus/prod/turn/*`) as `SecureString` parameters (KMS-encrypted). Read by Lambda at cold start to configure mediasoup TURN fallback for clients behind symmetric NATs. **Failure mode:** clients without TURN credentials may fail WebRTC connectivity behind restrictive firewalls; mediasoup falls back to STUN-only.

### Amazon EC2 (mediasoup SFU)
A `c5.xlarge` instance running Node.js 20 + mediasoup v3 handles the media plane: multi-party WebRTC video and audio routing. Browsers connect via WebRTC for media transport; SDP/ICE signaling travels over a direct WSS connection to the EC2 instance on port 443. This path is completely independent of API Gateway and Lambda. **Failure mode:** EC2 failure drops all active WebRTC connections; participants lose video/audio but the AI caption pipeline (API Gateway → Lambda) continues to function independently.

### Amazon CloudWatch
Receives logs from all Lambda functions (`/aws/lambda/<FunctionName>`, 14-day retention) and from the mediasoup EC2 instance (`/ec2/nimbus-prod/mediasoup`, 14-day retention via CloudWatch agent). Used for operational monitoring, latency tracking, and alerting. **Failure mode:** loss of CloudWatch does not affect the inference pipeline; logs are simply not captured.

### AWS IAM
Three roles enforce least-privilege access: `NIMBUS_PROD_LambdaExecutionRole` (Lambda → SageMaker, Bedrock, Rekognition, Polly, DynamoDB, S3, API Gateway Management API, CloudWatch, SSM); `NIMBUS_PROD_SageMakerTrainingRole` (training jobs → S3, CloudWatch); `NIMBUS_PROD_MediasoupEC2Role` (EC2 → CloudWatch, S3 config bucket, DynamoDB Rooms table). No role has admin access.

---

## Key Invariants

| Invariant | Value |
|---|---|
| Keypoint send rate | 10 FPS (100 ms minimum between frames) |
| Face crop frequency | Every 10th keypoint frame (≈ 1 s) |
| Feature vector width | 258 floats per frame |
| Sentence boundary — pause | 800 ms silence (Tier 1) |
| Sentence boundary — token ceiling | 8 gloss tokens (Tier 2) |
| Bedrock context window | Last 3 captions from DynamoDB |
| Session TTL | 4 hours (DynamoDB TTL) |
| SageMaker instance | `ml.g5.xlarge` |
| mediasoup instance | `c5.xlarge` |
| WebRTC media ports | UDP 40000–49999 |
