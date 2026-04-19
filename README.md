https://d3w45x42zio2oi.cloudfront.net/

# ASL Live Video Caption Interpretation (NIMBUS)

Real-time ASL recognition with facial emotion detection, natural language interpretation, and expressive text-to-speech — integrated with Zoom.

## Overview
This system captures a signer's webcam feed in real-time, recognizes American Sign Language (ASL) signs and facial expressions, translates raw ASL gloss into natural English sentences using an LLM, generates emotionally expressive speech, and delivers both native captions and TTS audio directly into a Zoom meeting.

## Project Structure
We have split the functionality across the `frontend` (local application logic), `backend` (cloud orchestration), and `infrastructure` (long-running hosts):

* **`frontend/`**: Contains the local desktop Python application. Captures the webcam via OpenCV, tracks pose keypoints via MediaPipe Holistic, establishes a WebSocket connection, and loops interpretations into Zoom via its API and local audio tunneling.
* **`backend/`**: Contains the AWS Serverless (SAM) template plus Python Lambda handlers for the API Gateway WebSocket signaling plane, DynamoDB tables (Sessions, Rooms, UserPreferences), and caption broadcast. Inside `backend/ml_pipeline`, you will find SageMaker-specific scripts for training the core Transformer ASL model.
* **`infrastructure/mediasoup/`**: Node.js mediasoup v3 SFU that runs on the EC2 host provisioned by the SAM template. Handles multi-party WebRTC routing and WSS signaling.
* **`docs/`**: Key architecture diagrams and API definitions.

## Getting Started
1. **Frontend Setup**:
   - `cd frontend/`
   - `pip install -r requirements.txt`
   - Entry point: `src/main.py`
   
2. **Backend Setup** (Member 1 scope — signaling & DynamoDB):
   - `cd backend/`
   - `pip install -r requirements.txt`
   - `sam build && sam deploy --guided` (supply VPC, public subnet, and key pair for the mediasoup EC2 host)
   - After first deploy, note the `MediasoupPublicIp` output and re-deploy with `MediasoupAnnouncedIp=<that-ip>` so the SFU advertises the right address in ICE candidates.

3. **Mediasoup SFU** (runs on the EC2 host from step 2):
   - `rsync -av infrastructure/mediasoup/ ec2-user@<eip>:/opt/nimbus-mediasoup/`
   - `ssh ec2-user@<eip> 'cd /opt/nimbus-mediasoup && npm ci --omit=dev && sudo systemctl restart nimbus-mediasoup'`
   - Full protocol + env var reference: `infrastructure/mediasoup/README.md`.

4. **Machine Learning Pipeline**:
   - `cd backend/ml_pipeline/`
   - Use SageMaker Notebook `notebooks/data_preparation.ipynb` to process training vectors.

## Running tests

| Suite | Location | Command |
|---|---|---|
| Backend (handlers + services) | `backend/tests/` | `cd backend && pip install -r requirements-dev.txt && python -m pytest tests/` |
| Mediasoup SFU (Peer + Room) | `infrastructure/mediasoup/test/` | `cd infrastructure/mediasoup && npm test` |

The Python suite mocks DynamoDB and API Gateway Management via
`unittest.mock`, so no AWS credentials are required. The Node suite stubs the
`mediasoup-pool` require entry to avoid spawning native workers.
