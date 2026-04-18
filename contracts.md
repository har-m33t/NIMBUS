# NIMBUS — Interface Contracts
> Derived from PROTOCOLS.md (canonical). Any deviation requires a PR to PROTOCOLS.md first.
> Last updated: 2026-04-18

---

## 1. Browser → API Gateway WebSocket

**Route:** `INFER` action over API Gateway WebSocket (wss://)

```json
{
  "action": "INFER",
  "sessionId": "<uuid-v4>",
  "roomId": "<string>",
  "timestamp": "<ISO-8601-UTC>",
  "sequenceNumber": 1024,
  "payload": {
    "keypoints": {
      "leftHand":  [{ "x": 0.512, "y": 0.341, "z": -0.042 }],
      "rightHand": [{ "x": 0.488, "y": 0.298, "z": -0.031 }],
      "pose":      [{ "x": 0.500, "y": 0.700, "z": 0.000, "visibility": 0.99 }]
    },
    "includeFaceCrop": false
  }
}
```

**Constraints:**
- `leftHand` and `rightHand`: exactly 21 landmarks each (empty array `[]` if hand absent)
- `pose`: exactly 33 landmarks, each with a `visibility` float
- All `x`, `y` ∈ [0.0, 1.0] (MediaPipe normalized). `z` is relative depth (may be negative).
- `sequenceNumber`: monotonically increasing integer per session
- Send rate: **10 FPS** (100 ms minimum between frames), 1 frame per message (no batching)
- When `includeFaceCrop: true` (every 10th frame), add `payload.faceCropBase64: "<base64-JPEG>"`, max 640×480 px

---

## 2. Lambda → SageMaker (`invoke_endpoint`)

**Endpoint:** `nimbus-prod-asl-endpoint`  
**ContentType:** `application/json`

```json
{
  "instances": [
    {
      "keypoints": [0.512, 0.341, -0.042, 0.488, 0.298, -0.031]
    }
  ]
}
```

**Actual shape contract (from PROTOCOLS.md §7):**

The keypoint array is flattened in landmark order to a tensor of shape `(1, T, 258)`:

| Landmark group | Points | Coords each | Flat floats |
|---|---|---|---|
| Left hand | 21 | x, y, z | 63 |
| Right hand | 21 | x, y, z | 63 |
| Pose | 33 | x, y, z, visibility | 132 |
| **Total per frame** | | | **258** |

- Missing hands are **zero-padded** (63 zeros)
- `T` = number of frames in the current gloss buffer flush
- Batch size is always 1

---

## 3. SageMaker → Lambda (inference response)

```json
{
  "predictions": [
    {
      "tokens": ["STORE", "I", "GO"],
      "confidence": 0.87
    }
  ]
}
```

**Field rules:**
| Field | Type | Notes |
|---|---|---|
| `tokens` | `list[str]` | Ordered gloss token strings; may include `[EOS]` |
| `confidence` | `float` | Scalar in [0.0, 1.0]; overall sequence confidence |

**Failure contract:** If endpoint returns non-200, Lambda MUST emit `ERROR` with `code: "SAGEMAKER_INFERENCE_FAILED"` and `glossFallback: "[UNKNOWN_SIGN]"`. Never propagate raw exceptions to client.

---

## 4. Lambda → SSM Parameter Store

TURN server credentials for mediasoup NAT traversal are read from Parameter Store at Lambda cold start.

| Parameter Name | Type | Format |
|---|---|---|
| `/nimbus/prod/turn/uri` | `String` | `turn:<host>:<port>` |
| `/nimbus/prod/turn/username` | `String` | plaintext username |
| `/nimbus/prod/turn/credential` | `SecureString` | plaintext secret (KMS-encrypted at rest) |

**Usage pattern:**
```python
ssm.get_parameter(Name="/nimbus/prod/turn/credential", WithDecryption=True)
```

The Lambda (`NIMBUS_PROD_LambdaExecutionRole`) requires `ssm:GetParameter` and `kms:Decrypt` on the relevant key ARN.

---

## 5. Lambda → S3 (SSML prosody config)

Read once per cold start, cached in module-level variable.

| Field | Value |
|---|---|
| Bucket | `nimbus-prod-config` |
| Key | `ssml_prosody_map.json` |
| Access | `s3:GetObject` on `arn:aws:s3:::nimbus-prod-config/ssml_prosody_map.json` |

Schema defined in PROTOCOLS.md §6.2. Allowed emotion keys: `HAPPY | SAD | ANGRY | CALM | SURPRISED | FEAR | DISGUSTED | CONFUSED`.

---

## 6. Lambda → DynamoDB (session state)

**Table:** `NIMBUS_PROD_Sessions`

Write on every `INFER` frame:
```
PK: sessionId
SK: "STATE"
glossBuffer:   list<str>   — append new tokens from SageMaker
lastEmotion:   str         — overwrite on each Rekognition result
lastCaptionAt: str         — ISO-8601, set on each Bedrock flush
connectionId:  str         — API Gateway connection ID (set on $connect)
ttl:           number      — epoch seconds, now + 14400 (4 hours)
```

Caption history written on Bedrock flush:
```
PK: sessionId
SK: "CAPTION#<ISO-8601-UTC>"
text:      str   — final English sentence
emotion:   str   — emotion label at time of flush
```

Query for context window: `KeyConditionExpression = PK=sessionId AND SK begins_with "CAPTION#"`, `ScanIndexForward=False`, `Limit=3`.

---

## 7. Backend → Client (WebSocket response events)

All events include `sessionId` and `timestamp`. See PROTOCOLS.md §1.2 for full schemas.

| `type` | Trigger | Key payload fields |
|---|---|---|
| `GLOSS` | SageMaker returns tokens | `tokens: list[str]`, `confidence: float` |
| `EMOTION` | Rekognition processes face crop | `emotion: str`, `confidence: float`, `allEmotions: dict` |
| `CAPTION` | Bedrock flush completes | `text: str`, `emotion: str`, `audioUrl: str`, `latencyMs: int` |
| `ERROR` | Any service failure | `code: str`, `glossFallback: str`, `message: str` |
| `SIGNAL` | Room lifecycle events | `event: JOIN_ROOM\|LEAVE_ROOM\|NEW_CAPTION\|ENDPOINT_WARMING` |
